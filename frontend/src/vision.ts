/**
 * Camera measurement with OpenCV.js: locating the phone in the room from the room's AprilTags.
 * OpenCV is passed in, so the worker and the Node tests share this code.
 */
import {
  markerCorners, roomFromMarkerPnP, roomPoseFromPnP, squareCorners, type RoomPose,
} from './marker-geometry';
import type { CameraIntrinsics, TrackingMarker } from './protocol';

/* The part of OpenCV.js this module uses. The package's own declarations omit the ArUco classes. */
export interface Mat {
  rows: number;
  cols: number;
  data: Uint8Array;
  data32F: Float32Array;
  data32S: Int32Array;
  data64F: Float64Array;
  delete(): void;
}
export interface MatVector { size(): number; get(index: number): Mat; delete(): void }
interface Deletable { delete(): void }
interface Dictionary extends Deletable { generateImageMarker(id: number, side: number, out: Mat, borderBits: number): void }
interface DetectorParameters extends Deletable { cornerRefinementMethod: number }
interface ArucoDetector extends Deletable { detectMarkers(image: Mat, corners: MatVector, ids: Mat, rejected: MatVector): void }
export interface OpenCV {
  Mat: { new(): Mat; new(rows: number, cols: number, type: number): Mat };
  MatVector: new () => MatVector;
  Size: new (width: number, height: number) => object;
  matFromArray(rows: number, cols: number, type: number, data: ArrayLike<number>): Mat;
  cvtColor(src: Mat, dst: Mat, code: number): void;
  solvePnP(object: Mat, image: Mat, camera: Mat, distortion: Mat, rvec: Mat, tvec: Mat, guess: boolean, flags: number): boolean;
  Rodrigues(src: Mat, dst: Mat): void;
  projectPoints(object: Mat, rvec: Mat, tvec: Mat, camera: Mat, distortion: Mat, out: Mat): void;
  getPredefinedDictionary(id: number): Dictionary;
  aruco_DetectorParameters: new () => DetectorParameters;
  aruco_RefineParameters: new (minRepDistance: number, errorCorrectionRate: number, checkAllOrders: boolean) => Deletable;
  aruco_ArucoDetector: new (dictionary: Dictionary, parameters: DetectorParameters, refine: Deletable) => ArucoDetector;
  CV_8UC1: number; CV_8UC4: number; CV_32FC2: number; CV_32FC3: number; CV_64F: number; CV_64FC2: number; CV_64FC3: number;
  COLOR_RGBA2GRAY: number; CORNER_REFINE_SUBPIX: number;
  SOLVEPNP_IPPE_SQUARE: number; SOLVEPNP_SQPNP: number;
  DICT_APRILTAG_36h11: number;
}

/**
 * OpenCV.js's module object is a thenable that resolves to itself, so awaiting it, or resolving a
 * promise with it, never settles. The ready module is handed over inside a plain object instead.
 */
export function openCV(module: unknown): Promise<{ cv: OpenCV }> {
  return new Promise(resolve => {
    (module as { then(ready: (cv: OpenCV) => void): void }).then(cv => resolve({ cv }));
  });
}

/** A marker smaller than this in the processed frame gives too coarse a pose to publish. */
export const MIN_MARKER_SIDE_PX = 20;
/** Mean corner reprojection error above which a pose is refused as a misfit. */
export const MAX_REPROJECTION_PX = 3;
/** Positions outside the shared pose contract's bounds are refused. */
const MAX_COORDINATE = 100;

export type Located =
  | { kind: 'tracked'; pose: RoomPose; markerIds: number[]; reprojectionPx: number }
  | { kind: 'unseen'; reason: string };

/** Runs `work`, then frees every OpenCV object it put in `owned`, however it ends. */
function freeAfter<T>(work: (owned: Deletable[]) => T): T {
  const owned: Deletable[] = [];
  try {
    return work(owned);
  } finally {
    for (const item of owned) item.delete();
  }
}

/** An RGBA frame as a canvas delivers it. */
export interface Frame { width: number; height: number; rgba: Uint8ClampedArray }

function grayFrom(cv: OpenCV, frame: Frame, owned: Deletable[]): Mat {
  const rgba = new cv.Mat(frame.height, frame.width, cv.CV_8UC4);
  owned.push(rgba);
  rgba.data.set(frame.rgba);
  const gray = new cv.Mat();
  owned.push(gray);
  cv.cvtColor(rgba, gray, cv.COLOR_RGBA2GRAY);
  return gray;
}

function cameraMats(cv: OpenCV, intrinsics: CameraIntrinsics, owned: Deletable[]): [Mat, Mat] {
  const { fx, fy, cx, cy } = intrinsics;
  const camera = cv.matFromArray(3, 3, cv.CV_64F, [fx, 0, cx, 0, fy, cy, 0, 0, 1]);
  const distortion = cv.matFromArray(1, 5, cv.CV_64F, intrinsics.distortion);
  owned.push(camera, distortion);
  return [camera, distortion];
}

/** Locates the camera in the room from the known AprilTags in one frame. */
export class MarkerLocator {
  private readonly dictionary: Dictionary;
  private readonly parameters: DetectorParameters;
  private readonly refine: Deletable;
  private readonly detector: ArucoDetector;

  constructor(private readonly cv: OpenCV) {
    this.dictionary = cv.getPredefinedDictionary(cv.DICT_APRILTAG_36h11);
    this.parameters = new cv.aruco_DetectorParameters();
    this.parameters.cornerRefinementMethod = cv.CORNER_REFINE_SUBPIX;
    // OpenCV's default refinement: 10 px, error-correction rate 3, all corner orders checked.
    this.refine = new cv.aruco_RefineParameters(10, 3, true);
    this.detector = new cv.aruco_ArucoDetector(this.dictionary, this.parameters, this.refine);
  }

  /** `intrinsics` must describe frames of exactly this frame's size. */
  locate(frame: Frame, intrinsics: CameraIntrinsics, markers: readonly TrackingMarker[]): Located {
    const cv = this.cv;
    return freeAfter(owned => {
      const gray = grayFrom(cv, frame, owned);
      const corners = new cv.MatVector();
      const ids = new cv.Mat();
      const rejected = new cv.MatVector();
      owned.push(corners, ids, rejected);
      this.detector.detectMarkers(gray, corners, ids, rejected);
      const known = new Map(markers.map(marker => [marker.id, marker]));
      const roomCoordinates: number[] = [];
      const imageCoordinates: number[] = [];
      const usedIds: number[] = [];
      let tooSmall = false;
      for (let index = 0; index < ids.rows; index++) {
        const marker = known.get(ids.data32S[index]);
        if (!marker) continue;
        const points = Array.from(corners.get(index).data32F);
        let shortest = Infinity;
        for (let corner = 0; corner < 4; corner++) {
          const next = (corner + 1) % 4;
          shortest = Math.min(shortest, Math.hypot(
            points[next * 2] - points[corner * 2], points[next * 2 + 1] - points[corner * 2 + 1]));
        }
        if (shortest < MIN_MARKER_SIDE_PX) {
          tooSmall = true;
          continue;
        }
        for (const point of markerCorners(marker)) roomCoordinates.push(point.x, point.y, point.z);
        imageCoordinates.push(...points);
        usedIds.push(marker.id);
      }
      if (usedIds.length === 0) {
        const reason = tooSmall ? 'The marker is too far away. Move closer.' :
          ids.rows > 0 ? 'Only markers this room does not use are in view.' : 'No room marker in view.';
        return { kind: 'unseen', reason };
      }
      // A single square is solved in its own frame, where IPPE_SQUARE resolves it exactly; OpenCV.js's
      // general IPPE misplaces a square lying off the z = 0 plane. SQPnP takes several tags in room
      // coordinates. Doubles in, so the projected points come back as doubles too.
      const single = usedIds.length === 1 ? known.get(usedIds[0]) : undefined;
      const corners3d = single ?
        squareCorners(single.size).flatMap(point => [point.x, point.y, point.z]) : roomCoordinates;
      const objectPoints = cv.matFromArray(usedIds.length * 4, 1, cv.CV_64FC3, corners3d);
      const imagePoints = cv.matFromArray(usedIds.length * 4, 1, cv.CV_64FC2, imageCoordinates);
      const [camera, distortion] = cameraMats(cv, intrinsics, owned);
      const rvec = new cv.Mat();
      const tvec = new cv.Mat();
      const rotation = new cv.Mat();
      const projected = new cv.Mat();
      owned.push(objectPoints, imagePoints, rvec, tvec, rotation, projected);
      const method = single ? cv.SOLVEPNP_IPPE_SQUARE : cv.SOLVEPNP_SQPNP;
      if (!cv.solvePnP(objectPoints, imagePoints, camera, distortion, rvec, tvec, false, method)) {
        return { kind: 'unseen', reason: 'The marker pose could not be solved.' };
      }
      cv.projectPoints(objectPoints, rvec, tvec, camera, distortion, projected);
      const reprojected = projected.data64F;
      let error = 0;
      for (let index = 0; index < imageCoordinates.length; index += 2) {
        error += Math.hypot(
          reprojected[index] - imageCoordinates[index], reprojected[index + 1] - imageCoordinates[index + 1]);
      }
      const reprojectionPx = error / (imageCoordinates.length / 2);
      if (!(reprojectionPx <= MAX_REPROJECTION_PX)) {
        return { kind: 'unseen', reason: 'The marker view did not fit its known shape.' };
      }
      cv.Rodrigues(rvec, rotation);
      const inRoom = single ?
        roomFromMarkerPnP(single, rotation.data64F, tvec.data64F) :
        { rotation: rotation.data64F, translation: tvec.data64F };
      const pose = roomPoseFromPnP(inRoom.rotation, inRoom.translation);
      const { x, y, z } = pose.position;
      if (![x, y, z].every(value => Number.isFinite(value) && Math.abs(value) <= MAX_COORDINATE)) {
        return { kind: 'unseen', reason: 'The marker pose was out of range.' };
      }
      return { kind: 'tracked', pose, markerIds: usedIds, reprojectionPx };
    });
  }
}
