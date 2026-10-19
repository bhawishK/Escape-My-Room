import { markerCorners, roomFromMarkerPnP, roomPoseFromPnP, squareCorners, type RoomPose } from './marker-geometry';
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
export interface MatVector { size(): number; get(index: number): Mat; push_back(mat: Mat): void; delete(): void }
interface Deletable { delete(): void }
interface Dictionary extends Deletable { generateImageMarker(id: number, side: number, out: Mat, borderBits: number): void }
interface DetectorParameters extends Deletable { cornerRefinementMethod: number }
interface ArucoDetector extends Deletable { detectMarkers(image: Mat, corners: MatVector, ids: Mat, rejected: MatVector): void }
interface CharucoBoard extends Deletable {
  generateImage(size: object, out: Mat, margin: number, borderBits: number): void;
  getChessboardCorners(): { size(): number; get(index: number): { x: number; y: number } };
}
interface CharucoDetector extends Deletable {
  detectBoard(image: Mat, corners: Mat, ids: Mat, markerCorners: MatVector, markerIds: Mat): void;
}
export interface OpenCV {
  Mat: { new(): Mat; new(rows: number, cols: number, type: number): Mat };
  MatVector: new () => MatVector;
  Size: new (width: number, height: number) => object;
  TermCriteria: new (type: number, count: number, epsilon: number) => object;
  matFromArray(rows: number, cols: number, type: number, data: ArrayLike<number>): Mat;
  cvtColor(src: Mat, dst: Mat, code: number): void;
  solvePnP(object: Mat, image: Mat, camera: Mat, distortion: Mat, rvec: Mat, tvec: Mat, guess: boolean, flags: number): boolean;
  Rodrigues(src: Mat, dst: Mat): void;
  projectPoints(object: Mat, rvec: Mat, tvec: Mat, camera: Mat, distortion: Mat, out: Mat): void;
  calibrateCameraExtended(
    object: MatVector, image: MatVector, size: object, camera: Mat, distortion: Mat, rvecs: MatVector, tvecs: MatVector,
    intrinsicDeviations: Mat, extrinsicDeviations: Mat, viewErrors: Mat, flags: number, criteria: object,
  ): number;
  getPredefinedDictionary(id: number): Dictionary;
  aruco_DetectorParameters: new () => DetectorParameters;
  aruco_RefineParameters: new (minRepDistance: number, errorCorrectionRate: number, checkAllOrders: boolean) => Deletable;
  aruco_ArucoDetector: new (dictionary: Dictionary, parameters: DetectorParameters, refine: Deletable) => ArucoDetector;
  aruco_CharucoBoard: new (size: object, square: number, marker: number, dictionary: Dictionary, ids: Mat) => CharucoBoard;
  aruco_CharucoParameters: new () => Deletable;
  aruco_CharucoDetector: new (
    board: CharucoBoard, charuco: Deletable, parameters: DetectorParameters, refine: Deletable,
  ) => CharucoDetector;
  CV_8UC1: number; CV_8UC4: number; CV_32FC2: number; CV_32FC3: number; CV_64F: number; CV_64FC2: number; CV_64FC3: number;
  COLOR_RGBA2GRAY: number; CORNER_REFINE_SUBPIX: number;
  SOLVEPNP_IPPE_SQUARE: number; SOLVEPNP_SQPNP: number;
  DICT_APRILTAG_36h11: number; DICT_5X5_100: number;
  CALIB_FIX_K3: number; CALIB_ZERO_TANGENT_DIST: number;
  TermCriteria_COUNT: number; TermCriteria_EPS: number;
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

/** An RGBA frame as a canvas delivers it. */
export interface Frame { width: number; height: number; rgba: Uint8ClampedArray }

function grayFrom(cv: OpenCV, frame: Frame, tracked: Deletable[]): Mat {
  const rgba = new cv.Mat(frame.height, frame.width, cv.CV_8UC4);
  tracked.push(rgba);
  rgba.data.set(frame.rgba);
  const gray = new cv.Mat();
  tracked.push(gray);
  cv.cvtColor(rgba, gray, cv.COLOR_RGBA2GRAY);
  return gray;
}

function cameraMats(cv: OpenCV, intrinsics: CameraIntrinsics, tracked: Deletable[]): [Mat, Mat] {
  const { fx, fy, cx, cy } = intrinsics;
  const camera = cv.matFromArray(3, 3, cv.CV_64F, [fx, 0, cx, 0, fy, cy, 0, 0, 1]);
  const distortion = cv.matFromArray(1, 5, cv.CV_64F, intrinsics.distortion);
  tracked.push(camera, distortion);
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
    this.refine = new cv.aruco_RefineParameters(10, 3, true);
    this.detector = new cv.aruco_ArucoDetector(this.dictionary, this.parameters, this.refine);
  }

  /** `intrinsics` must describe frames of exactly this frame's size. */
  locate(frame: Frame, intrinsics: CameraIntrinsics, markers: readonly TrackingMarker[]): Located {
    const cv = this.cv;
    const tracked: Deletable[] = [];
    try {
      const gray = grayFrom(cv, frame, tracked);
      const corners = new cv.MatVector();
      const ids = new cv.Mat();
      const rejected = new cv.MatVector();
      tracked.push(corners, ids, rejected);
      this.detector.detectMarkers(gray, corners, ids, rejected);
      const known = new Map(markers.map(marker => [marker.id, marker]));
      const room: number[] = [];
      const image: number[] = [];
      const used: number[] = [];
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
        for (const point of markerCorners(marker)) room.push(point.x, point.y, point.z);
        image.push(...points);
        used.push(marker.id);
      }
      if (used.length === 0) {
        const reason = tooSmall ? 'The marker is too far away. Move closer.' :
          ids.rows > 0 ? 'Only markers this room does not use are in view.' : 'No room marker in view.';
        return { kind: 'unseen', reason };
      }
      // A single square is solved in its own frame, where IPPE_SQUARE resolves it exactly; OpenCV.js's
      // general IPPE misplaces a square lying off the z = 0 plane. SQPnP takes several tags in room
      // coordinates. Doubles in, so the projected points come back as doubles too.
      const single = used.length === 1 ? known.get(used[0]) : undefined;
      const corners3d = single ? squareCorners(single.size).flatMap(point => [point.x, point.y, point.z]) : room;
      const objectPoints = cv.matFromArray(used.length * 4, 1, cv.CV_64FC3, corners3d);
      const imagePoints = cv.matFromArray(used.length * 4, 1, cv.CV_64FC2, image);
      const [camera, distortion] = cameraMats(cv, intrinsics, tracked);
      const rvec = new cv.Mat();
      const tvec = new cv.Mat();
      const rotation = new cv.Mat();
      const projected = new cv.Mat();
      tracked.push(objectPoints, imagePoints, rvec, tvec, rotation, projected);
      const method = single ? cv.SOLVEPNP_IPPE_SQUARE : cv.SOLVEPNP_SQPNP;
      if (!cv.solvePnP(objectPoints, imagePoints, camera, distortion, rvec, tvec, false, method)) {
        return { kind: 'unseen', reason: 'The marker pose could not be solved.' };
      }
      cv.projectPoints(objectPoints, rvec, tvec, camera, distortion, projected);
      const reprojected = projected.data64F;
      let error = 0;
      for (let index = 0; index < image.length; index += 2) {
        error += Math.hypot(reprojected[index] - image[index], reprojected[index + 1] - image[index + 1]);
      }
      const reprojectionPx = error / (image.length / 2);
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
      return { kind: 'tracked', pose, markerIds: used, reprojectionPx };
    } finally {
      for (const item of tracked) item.delete();
    }
  }
}

/**
 * The printed calibration board: 7 x 5 squares of 30 mm with 22 mm 5x5 ArUco markers. It uses a
 * different dictionary from the room's AprilTags, so neither is mistaken for the other.
 */
export const BOARD = { columns: 7, rows: 5, squareMeters: 0.03, markerMeters: 0.022 } as const;
/** A view with fewer inner board corners than this does not constrain the camera well. */
export const MIN_BOARD_CORNERS = 12;

export function createBoard(cv: OpenCV): { board: CharucoBoard; dictionary: Dictionary } {
  const dictionary = cv.getPredefinedDictionary(cv.DICT_5X5_100);
  const ids = new cv.Mat();
  const board = new cv.aruco_CharucoBoard(
    new cv.Size(BOARD.columns, BOARD.rows), BOARD.squareMeters, BOARD.markerMeters, dictionary, ids);
  ids.delete();
  return { board, dictionary };
}

/** Collects views of the printed board and solves the camera's intrinsics from them. */
export class BoardCalibrator {
  private readonly board: CharucoBoard;
  private readonly detector: CharucoDetector;
  private readonly parameters: DetectorParameters;
  private readonly refine: Deletable;
  private readonly charuco: Deletable;
  private readonly boardCorners: { x: number; y: number }[] = [];
  private readonly objectViews: number[][] = [];
  private readonly imageViews: number[][] = [];
  private size: { width: number; height: number } | null = null;

  constructor(private readonly cv: OpenCV) {
    const { board, dictionary } = createBoard(cv);
    // The board keeps its own copy of the dictionary.
    dictionary.delete();
    this.board = board;
    this.parameters = new cv.aruco_DetectorParameters();
    this.refine = new cv.aruco_RefineParameters(10, 3, true);
    this.charuco = new cv.aruco_CharucoParameters();
    this.detector = new cv.aruco_CharucoDetector(this.board, this.charuco, this.parameters, this.refine);
    const corners = this.board.getChessboardCorners();
    for (let index = 0; index < corners.size(); index++) this.boardCorners.push(corners.get(index));
  }

  get views(): number { return this.imageViews.length; }

  /** Detects the board; keeps the view when enough corners are found. Returns the corner count. */
  addView(frame: Frame): { corners: number; kept: boolean } {
    const cv = this.cv;
    const tracked: Deletable[] = [];
    try {
      if (this.size && (this.size.width !== frame.width || this.size.height !== frame.height)) {
        this.reset();
      }
      const gray = grayFrom(cv, frame, tracked);
      const corners = new cv.Mat();
      const ids = new cv.Mat();
      const markerCorners = new cv.MatVector();
      const markerIds = new cv.Mat();
      tracked.push(corners, ids, markerCorners, markerIds);
      this.detector.detectBoard(gray, corners, ids, markerCorners, markerIds);
      const count = corners.rows;
      if (count < MIN_BOARD_CORNERS) return { corners: count, kept: false };
      const object: number[] = [];
      for (const id of Array.from(ids.data32S)) {
        const point = this.boardCorners[id];
        object.push(point.x, point.y, 0);
      }
      this.objectViews.push(object);
      this.imageViews.push(Array.from(corners.data32F));
      this.size = { width: frame.width, height: frame.height };
      return { corners: count, kept: true };
    } finally {
      for (const item of tracked) item.delete();
    }
  }

  /** Intrinsics for frames of the kept views' size, and the RMS reprojection error in pixels. */
  solve(): { intrinsics: CameraIntrinsics; rmsPx: number } {
    const cv = this.cv;
    if (!this.size || this.views === 0) throw new Error('No board views were kept.');
    const tracked: Deletable[] = [];
    try {
      const objects = new cv.MatVector();
      const images = new cv.MatVector();
      tracked.push(objects, images);
      this.objectViews.forEach((object, index) => {
        const objectMat = cv.matFromArray(object.length / 3, 1, cv.CV_32FC3, object);
        const imageMat = cv.matFromArray(object.length / 3, 1, cv.CV_32FC2, this.imageViews[index]);
        objects.push_back(objectMat);
        images.push_back(imageMat);
        objectMat.delete();
        imageMat.delete();
      });
      const camera = new cv.Mat();
      const distortion = new cv.Mat();
      const rvecs = new cv.MatVector();
      const tvecs = new cv.MatVector();
      const intrinsicDeviations = new cv.Mat();
      const extrinsicDeviations = new cv.Mat();
      const viewErrors = new cv.Mat();
      tracked.push(camera, distortion, rvecs, tvecs, intrinsicDeviations, extrinsicDeviations, viewErrors);
      // Phone video is largely corrected for lens distortion; k1 and k2 absorb what remains.
      const flags = cv.CALIB_FIX_K3 | cv.CALIB_ZERO_TANGENT_DIST;
      const criteria = new cv.TermCriteria(cv.TermCriteria_COUNT + cv.TermCriteria_EPS, 50, 1e-7);
      const rmsPx = cv.calibrateCameraExtended(
        objects, images, new cv.Size(this.size.width, this.size.height), camera, distortion, rvecs, tvecs,
        intrinsicDeviations, extrinsicDeviations, viewErrors, flags, criteria);
      const k = camera.data64F;
      return {
        intrinsics: {
          width: this.size.width, height: this.size.height,
          fx: k[0], fy: k[4], cx: k[2], cy: k[5],
          distortion: Array.from(distortion.data64F).slice(0, 5),
        },
        rmsPx,
      };
    } finally {
      for (const item of tracked) item.delete();
    }
  }

  reset(): void {
    this.objectViews.length = 0;
    this.imageViews.length = 0;
    this.size = null;
  }
}
