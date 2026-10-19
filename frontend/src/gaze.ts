/**
 * Gaze cursor math: features from a MediaPipe face result, and a calibrated linear mapping from
 * those features to a point on the screen. Pure, so the tests run it without a camera.
 */

/** A face landmark in image coordinates normalized to 0–1, as MediaPipe reports it. */
export interface Landmark { x: number; y: number; z: number }

/** Where the head points and where the irises sit in the eyes, for one camera frame. */
export interface FaceFeatures {
  /** The face's forward direction, x and y, in the camera's frame. */
  headX: number;
  headY: number;
  /** The head's offset from the camera in centimeters, x and y. */
  offsetX: number;
  offsetY: number;
  /** The irises' mean offset from the eye centers, in eye widths. */
  eyeX: number;
  eyeY: number;
}

export type CursorMode = 'head' | 'eyes';

/** A point on the screen, 0–1 across and down. */
export interface ScreenPoint { x: number; y: number }

// MediaPipe face mesh indices: each eye's corners, upper and lower lid, and iris center.
const EYES = [
  { corners: [33, 133], lids: [159, 145], iris: 468 },
  { corners: [362, 263], lids: [386, 374], iris: 473 },
] as const;
const MESH_WITH_IRISES = 478;

/**
 * The features of one face. `transform` is MediaPipe's column-major 4 x 4 facial transformation
 * matrix; `aspect` is the video's width over its height, so eye offsets are measured in pixels.
 */
export function faceFeatures(landmarks: readonly Landmark[], transform: readonly number[], aspect: number): FaceFeatures | null {
  if (landmarks.length < MESH_WITH_IRISES || transform.length !== 16) return null;
  let eyeX = 0;
  let eyeY = 0;
  for (const eye of EYES) {
    const [a, b] = eye.corners.map(index => landmarks[index]);
    const [upper, lower] = eye.lids.map(index => landmarks[index]);
    const iris = landmarks[eye.iris];
    const width = Math.hypot((b.x - a.x) * aspect, b.y - a.y);
    if (!(width > 0)) return null;
    eyeX += (iris.x - (a.x + b.x) / 2) * aspect / width;
    eyeY += (iris.y - (upper.y + lower.y) / 2) / width;
  }
  return {
    headX: transform[8], headY: transform[9],
    offsetX: transform[12], offsetY: transform[13],
    eyeX: eyeX / EYES.length, eyeY: eyeY / EYES.length,
  };
}

/** The averaged features of several frames, or null without any. */
export function meanFeatures(samples: readonly FaceFeatures[]): FaceFeatures | null {
  if (samples.length === 0) return null;
  const sum = { headX: 0, headY: 0, offsetX: 0, offsetY: 0, eyeX: 0, eyeY: 0 };
  for (const sample of samples) {
    for (const key of Object.keys(sum) as (keyof FaceFeatures)[]) sum[key] += sample[key];
  }
  for (const key of Object.keys(sum) as (keyof FaceFeatures)[]) sum[key] /= samples.length;
  return sum;
}

/**
 * The inputs each cursor uses, the head alone or the head with the eyes, each divided by how far it
 * typically moves while looking around a phone screen.
 */
function inputs(features: FaceFeatures, mode: CursorMode): number[] {
  const head = [features.headX / 0.2, features.headY / 0.2, features.offsetX / 3, features.offsetY / 3];
  return mode === 'head' ? head : [...head, features.eyeX / 0.1, features.eyeY / 0.1];
}

export interface Mapping {
  mode: CursorMode;
  mean: number[];
  /** Weights for x and for y: an intercept, then one per centered input. */
  x: number[];
  y: number[];
}

export interface CalibrationSample { features: FaceFeatures; target: ScreenPoint }

/** Solves `matrix · result = vector` by Gaussian elimination with partial pivoting. */
function solve(matrix: number[][], vector: number[]): number[] {
  const n = vector.length;
  const rows = matrix.map((row, index) => [...row, vector[index]]);
  for (let column = 0; column < n; column++) {
    let pivot = column;
    for (let row = column + 1; row < n; row++) {
      if (Math.abs(rows[row][column]) > Math.abs(rows[pivot][column])) pivot = row;
    }
    [rows[column], rows[pivot]] = [rows[pivot], rows[column]];
    for (let row = column + 1; row < n; row++) {
      const factor = rows[row][column] / rows[column][column];
      for (let k = column; k <= n; k++) rows[row][k] -= factor * rows[column][k];
    }
  }
  const result = new Array<number>(n).fill(0);
  for (let row = n - 1; row >= 0; row--) {
    let sum = rows[row][n];
    for (let k = row + 1; k < n; k++) sum -= rows[row][k] * result[k];
    result[row] = sum / rows[row][row];
  }
  return result;
}

/**
 * Fits a linear mapping from features to screen points. Inputs are centered and ridge regularized
 * on their typical range, so an input that barely varied during calibration, such as head position
 * while only the eyes moved, cannot turn its noise into cursor movement.
 */
export function fitMapping(samples: readonly CalibrationSample[], mode: CursorMode, ridge = 0.005): Mapping {
  const rows = samples.map(sample => inputs(sample.features, mode));
  const count = rows[0]?.length ?? 0;
  const mean = new Array<number>(count).fill(0);
  for (const row of rows) row.forEach((value, index) => { mean[index] += value / rows.length; });
  const design = rows.map(row => [1, ...row.map((value, index) => value - mean[index])]);
  const size = count + 1;
  const normal = Array.from({ length: size }, (_, i) => Array.from({ length: size }, (_, j) =>
    design.reduce((sum, row) => sum + row[i] * row[j], 0) + (i === j && i > 0 ? ridge * design.length : 0)));
  const weights = (axis: 'x' | 'y') => solve(normal, Array.from({ length: size }, (_, i) =>
    design.reduce((sum, row, index) => sum + row[i] * samples[index].target[axis], 0)));
  return { mode, mean, x: weights('x'), y: weights('y') };
}

/** The screen point a mapping gives for some features. */
export function predict(mapping: Mapping, features: FaceFeatures): ScreenPoint {
  const row = [1, ...inputs(features, mapping.mode).map((value, index) => value - mapping.mean[index])];
  const dot = (weights: number[]) => weights.reduce((sum, weight, index) => sum + weight * row[index], 0);
  return { x: dot(mapping.x), y: dot(mapping.y) };
}

/** Calibration targets: a 3 x 3 grid inset from the screen's edges. */
export const CALIBRATION_POINTS: ScreenPoint[] = [0.12, 0.5, 0.88].flatMap(y =>
  [0.12, 0.5, 0.88].map(x => ({ x, y })));
/** Accuracy targets, away from the calibration points. */
export const TEST_POINTS: ScreenPoint[] = [
  { x: 0.3, y: 0.3 }, { x: 0.7, y: 0.3 }, { x: 0.5, y: 0.6 }, { x: 0.25, y: 0.75 }, { x: 0.75, y: 0.8 },
];
