/**
 * Synthetic camera frames for tests: printed tags and the calibration board drawn in perspective
 * from a known camera pose and known intrinsics. These are fixtures, not device evidence.
 */
import cvModule from '@techstark/opencv-js';
import { BOARD, createBoard, openCV, type Frame, type Mat, type OpenCV } from '../src/vision';
import type { CameraIntrinsics, Position, TrackingMarker } from '../src/protocol';

let loaded: Promise<{ cv: OpenCV }> | null = null;
export function loadOpenCV(): Promise<{ cv: OpenCV }> {
  loaded ??= openCV(cvModule);
  return loaded;
}

/** OpenCV's camera axes in room coordinates: +X right, +Y down, +Z along the view. */
export interface CameraView { center: Position; right: Position; down: Position; forward: Position }

function normalize(v: Position): Position {
  const length = Math.hypot(v.x, v.y, v.z);
  return { x: v.x / length, y: v.y / length, z: v.z / length };
}
function cross(a: Position, b: Position): Position {
  return { x: a.y * b.z - a.z * b.y, y: a.z * b.x - a.x * b.z, z: a.x * b.y - a.y * b.x };
}

/** A level camera at `center` looking at `target`, as a person holds a phone upright. */
export function lookAt(center: Position, target: Position): CameraView {
  const forward = normalize({ x: target.x - center.x, y: target.y - center.y, z: target.z - center.z });
  const right = normalize(cross(forward, { x: 0, y: 1, z: 0 }));
  return { center, right, down: cross(forward, right), forward };
}

function project(view: CameraView, intrinsics: CameraIntrinsics, point: Position): [number, number] {
  const d = { x: point.x - view.center.x, y: point.y - view.center.y, z: point.z - view.center.z };
  const x = d.x * view.right.x + d.y * view.right.y + d.z * view.right.z;
  const y = d.x * view.down.x + d.y * view.down.y + d.z * view.down.z;
  const z = d.x * view.forward.x + d.y * view.forward.y + d.z * view.forward.z;
  if (z <= 0.05) throw new Error('A fixture point is behind the camera.');
  return [intrinsics.fx * x / z + intrinsics.cx, intrinsics.fy * y / z + intrinsics.cy];
}

function rotate(q: TrackingMarker['rotation'], x: number, y: number): Position {
  const tx = 2 * (-q.z * y), ty = 2 * (q.z * x), tz = 2 * (q.x * y - q.y * x);
  return {
    x: x + q.w * tx + (q.y * tz - q.z * ty),
    y: y + q.w * ty + (q.z * tx - q.x * tz),
    z: q.w * tz + (q.x * ty - q.y * tx),
  };
}

/** Pastes `source` so its corners land on `targets` (top-left, top-right, bottom-right, bottom-left). */
function paste(cv: OpenCV, canvas: Mat, source: Mat, targets: [number, number][]): void {
  const raw = cv as unknown as {
    getPerspectiveTransform(a: Mat, b: Mat): Mat;
    warpPerspective(a: Mat, b: Mat, m: Mat, size: object, flags: number, border: number): void;
    INTER_LINEAR: number; BORDER_TRANSPARENT: number;
  };
  const w = source.cols - 1, h = source.rows - 1;
  const from = cv.matFromArray(4, 1, cv.CV_32FC2, [0, 0, w, 0, w, h, 0, h]);
  const to = cv.matFromArray(4, 1, cv.CV_32FC2, targets.flat());
  const transform = raw.getPerspectiveTransform(from, to);
  raw.warpPerspective(source, canvas, transform, new cv.Size(canvas.cols, canvas.rows), raw.INTER_LINEAR, raw.BORDER_TRANSPARENT);
  for (const mat of [from, to, transform]) mat.delete();
}

function toFrame(cv: OpenCV, gray: Mat): Frame {
  const rgba = new cv.Mat();
  cv.cvtColor(gray, rgba, (cv as unknown as { COLOR_GRAY2RGBA: number }).COLOR_GRAY2RGBA);
  const frame = { width: gray.cols, height: gray.rows, rgba: new Uint8ClampedArray(rgba.data) };
  rgba.delete();
  return frame;
}

function blank(cv: OpenCV, intrinsics: CameraIntrinsics): Mat {
  const gray = new cv.Mat(intrinsics.height, intrinsics.width, cv.CV_8UC1);
  gray.data.fill(150);
  return gray;
}

/** Draws each tag, black square plus a white border one square-eighth wide, as the camera sees it. */
export function renderMarkers(
  cv: OpenCV, intrinsics: CameraIntrinsics, view: CameraView, markers: readonly TrackingMarker[],
): Frame {
  const gray = blank(cv, intrinsics);
  const dictionary = cv.getPredefinedDictionary(cv.DICT_APRILTAG_36h11);
  for (const marker of markers) {
    // 8 modules of 40 px: the black border ring and the 6 x 6 code.
    const tag = new cv.Mat();
    dictionary.generateImageMarker(marker.id, 320, tag, 1);
    const paper = new cv.Mat(400, 400, cv.CV_8UC1);
    paper.data.fill(255);
    for (let row = 0; row < 320; row++) paper.data.set(tag.data.subarray(row * 320, row * 320 + 320), (row + 40) * 400 + 40);
    // The paper's corners are 400/320 times the black square's.
    const half = marker.size / 2 * 400 / 320;
    const targets = ([[-half, half], [half, half], [half, -half], [-half, -half]] as const).map(([x, y]) => {
      const turned = rotate(marker.rotation, x, y);
      return project(view, intrinsics, {
        x: marker.position.x + turned.x, y: marker.position.y + turned.y, z: marker.position.z + turned.z,
      });
    });
    paste(cv, gray, paper, targets);
    tag.delete();
    paper.delete();
  }
  dictionary.delete();
  const frame = toFrame(cv, gray);
  gray.delete();
  return frame;
}

/**
 * The calibration board held `distance` meters in front of the camera, turned by the Rodrigues
 * vector `tilt`. The board's own frame is the one its corner coordinates use.
 */
export function renderBoard(cv: OpenCV, intrinsics: CameraIntrinsics, tilt: [number, number, number], distance: number): Frame {
  const raw = cv as unknown as { Rodrigues(a: Mat, b: Mat): void };
  const { board, dictionary } = createBoard(cv);
  const margin = 60;
  const pixelsPerMeter = 6000;
  const image = new cv.Mat();
  const width = Math.round(BOARD.columns * BOARD.squareMeters * pixelsPerMeter) + 2 * margin;
  const height = Math.round(BOARD.rows * BOARD.squareMeters * pixelsPerMeter) + 2 * margin;
  board.generateImage(new cv.Size(width, height), image, margin, 1);
  const rvec = cv.matFromArray(3, 1, cv.CV_64F, tilt);
  const rotation = new cv.Mat();
  raw.Rodrigues(rvec, rotation);
  const r = rotation.data64F;
  const center = [BOARD.columns * BOARD.squareMeters / 2, BOARD.rows * BOARD.squareMeters / 2];
  const targets = ([[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]] as const).map(([u, v]) => {
    // Board coordinates relative to its center, turned, then pushed out to the distance.
    const x = (u - margin) / pixelsPerMeter - center[0];
    const y = (v - margin) / pixelsPerMeter - center[1];
    const cam = [r[0] * x + r[1] * y, r[3] * x + r[4] * y, r[6] * x + r[7] * y + distance];
    return [intrinsics.fx * cam[0] / cam[2] + intrinsics.cx, intrinsics.fy * cam[1] / cam[2] + intrinsics.cy] as [number, number];
  });
  const gray = blank(cv, intrinsics);
  paste(cv, gray, image, targets);
  const frame = toFrame(cv, gray);
  for (const item of [image, rvec, rotation, gray, board, dictionary]) item.delete();
  return frame;
}

/** Raw YUV4MPEG2 video of gray frames, which Chromium's fake camera plays in a loop. */
export function y4m(frames: readonly Frame[], fps: number): Buffer {
  const { width, height } = frames[0];
  const header = Buffer.from(`YUV4MPEG2 W${width} H${height} F${fps}:1 Ip A1:1 C420jpeg\n`);
  const chroma = Buffer.alloc((width / 2) * (height / 2) * 2, 128);
  const parts: Buffer[] = [header];
  for (const frame of frames) {
    const luma = Buffer.alloc(width * height);
    for (let index = 0; index < luma.length; index++) luma[index] = frame.rgba[index * 4];
    parts.push(Buffer.from('FRAME\n'), luma, chroma);
  }
  return Buffer.concat(parts);
}
