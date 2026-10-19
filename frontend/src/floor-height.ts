/**
 * The phone's height above the floor from one depth map: pixels on upward-facing surfaces are
 * placed in 3D, a plane is fitted through the lowest level surface, and the camera's distance from
 * it is its height. Also the depth model's input and output formats. Pure, so the tests run it on
 * synthetic depth maps.
 */
import type { Rotation } from './protocol';

/** A direction or point in the camera's image frame: x right, y down, z forward. */
export type Vec3 = readonly [number, number, number];

/** Metric depth along the camera's z axis, with surface normals, for one camera frame. */
export interface DepthMap {
  width: number;
  height: number;
  /** Meters, row by row; 0 where unknown. */
  depth: Float32Array;
  /** Unit normals pointing out of each surface toward the camera, x, y, z per pixel. */
  normals: Float32Array;
  fx: number;
  fy: number;
  cx: number;
  cy: number;
}

export type FloorResult =
  | { kind: 'measured'; height: number }
  | { kind: 'none'; reason: string };

/** Surfaces tilted further than this from level are not floor. */
const MAX_TILT = Math.cos(20 * Math.PI / 180);
const BIN_M = 0.02;
/** A level surface needs this share of the busiest one's points to count, so specks are ignored. */
const MIN_SUPPORT = 0.15;
/** Points this close to the lowest level, along the sensor's gravity, start the floor plane fit. */
const FIRST_BAND_M = 0.15;
/** Points this close to the fitted floor plane are the floor. */
const SURFACE_BAND_M = 0.05;
const PLANE_FITS = 3;
/** Less floor than this share of the picture is too little to measure from. */
const MIN_FLOOR_SHARE = 0.05;

/** The component of `p` along the unit direction `n`. */
const along = (p: Vec3, n: Vec3) => p[0] * n[0] + p[1] * n[1] + p[2] * n[2];

/**
 * The plane best fitting `points` (least squares): its unit normal, on gravity's side, and its
 * distance from the camera along it.
 */
function fitPlane(points: Vec3[], down: Vec3): { normal: Vec3; distance: number } {
  const c = [0, 0, 0];
  for (const p of points) for (let k = 0; k < 3; k++) c[k] += p[k] / points.length;
  let xx = 0, xy = 0, xz = 0, yy = 0, yz = 0, zz = 0;
  for (const p of points) {
    const x = p[0] - c[0], y = p[1] - c[1], z = p[2] - c[2];
    xx += x * x; xy += x * y; xz += x * z; yy += y * y; yz += y * z; zz += z * z;
  }
  // The normal is the direction of least spread; solve with the axis whose determinant is largest.
  const dx = yy * zz - yz * yz, dy = xx * zz - xz * xz, dz = xx * yy - xy * xy;
  let n: Vec3 = dx >= dy && dx >= dz ? [dx, xz * yz - xy * zz, xy * yz - xz * yy] :
    dy >= dz ? [xz * yz - xy * zz, dy, xy * xz - yz * xx] : [xy * yz - xz * yy, xy * xz - yz * xx, dz];
  const length = Math.hypot(...n);
  const center: Vec3 = [c[0], c[1], c[2]];
  if (!(length > 0)) return { normal: down, distance: along(center, down) };
  const sign = along(n, down) < 0 ? -1 : 1;
  n = [sign * n[0] / length, sign * n[1] / length, sign * n[2] / length];
  return { normal: n, distance: along(center, n) };
}

/**
 * The camera's height above the floor: its distance from the plane of the lowest level surface in
 * view. `down` is gravity in the image frame; it only needs to be roughly right, since the floor's
 * own plane is fitted.
 */
export function floorHeight(map: DepthMap, down: Vec3): FloorResult {
  const points: Vec3[] = [];
  const heights: number[] = [];
  let seen = 0;
  for (let v = 0; v < map.height; v++) {
    for (let u = 0; u < map.width; u++) {
      const index = v * map.width + u;
      const z = map.depth[index];
      if (!(z > 0)) continue;
      seen++;
      const n = index * 3;
      const upward = -along([map.normals[n], map.normals[n + 1], map.normals[n + 2]], down);
      if (upward < MAX_TILT) continue;
      const point: Vec3 = [(u - map.cx) / map.fx * z, (v - map.cy) / map.fy * z, z];
      points.push(point);
      heights.push(along(point, down));
    }
  }
  if (heights.length === 0) return { kind: 'none', reason: 'No floor in view. Tilt the phone down.' };
  // Level surfaces: the floor is the lowest one, the furthest below the camera, not the biggest.
  const bins = new Map<number, number>();
  for (const h of heights) bins.set(Math.round(h / BIN_M), (bins.get(Math.round(h / BIN_M)) ?? 0) + 1);
  const busiest = Math.max(...bins.values());
  let lowest = -Infinity;
  for (const [bin, count] of bins) if (count >= MIN_SUPPORT * busiest && bin > lowest) lowest = bin;
  const level = lowest * BIN_M;
  let floor = points.filter((_, index) => Math.abs(heights[index] - level) <= FIRST_BAND_M);
  for (let fit = 0; fit < PLANE_FITS && floor.length >= 3; fit++) {
    const plane = fitPlane(floor, down);
    floor = points.filter(p => Math.abs(along(p, plane.normal) - plane.distance) <= SURFACE_BAND_M);
    if (fit === PLANE_FITS - 1 && floor.length >= MIN_FLOOR_SHARE * seen) {
      const distances = floor.map(p => along(p, plane.normal)).sort((a, b) => a - b);
      return { kind: 'measured', height: distances[Math.floor(distances.length / 2)] };
    }
  }
  return { kind: 'none', reason: 'Too little floor in view. Tilt the phone down.' };
}

export type Settled =
  | { kind: 'settled'; height: number }
  | { kind: 'more' }
  | { kind: 'failed'; reason: string };

/** Readings this close together, highest to lowest, agree. */
const AGREEMENT_M = 0.1;
const AGREEING_READINGS = 3;
/** Readings, and frames tried, after which a measurement stops waiting. */
const MAX_READINGS = 6;
const MAX_ATTEMPTS = 8;

/**
 * Whether a height measurement is done: it settles on the median of the last three readings once
 * they agree, so one outlier is waited out. `attempts` counts every frame tried, floor seen or not.
 */
export function settledHeight(readings: readonly number[], attempts: number): Settled {
  const last = readings.slice(-AGREEING_READINGS);
  if (last.length === AGREEING_READINGS && Math.max(...last) - Math.min(...last) <= AGREEMENT_M) {
    return { kind: 'settled', height: [...last].sort((a, b) => a - b)[1] };
  }
  if (readings.length >= MAX_READINGS) {
    return { kind: 'failed', reason: 'The readings kept disagreeing. Hold the phone still with the floor in view, then measure again.' };
  }
  if (attempts >= MAX_ATTEMPTS) {
    return { kind: 'failed', reason: 'Too little floor was seen. Point the camera at open floor, then measure again.' };
  }
  return { kind: 'more' };
}

/**
 * Gravity's direction in the camera's image frame, from the camera's room orientation as a
 * Three.js camera holds it (looking along -Z with +Y up, in a frame whose +Y is up).
 */
export function gravityInCamera(orientation: Rotation): Vec3 {
  // World up seen from the camera: (0, 1, 0) turned by the inverse rotation.
  const { x, y, z, w } = orientation;
  const up: Vec3 = [2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)];
  // Three.js camera axes to image axes flip y and z; gravity is the opposite of up.
  return [-up[0], up[1], up[2]];
}

export interface Size { width: number; height: number }

/**
 * The image the depth model sees: Metric3D's own 616 x 1064 canvas, turned to match the camera
 * frame. Smaller canvases were tried on NYU Depth V2 photos and lost the floor or read 15-22 % low.
 */
export function modelCanvas(frame: Size): Size {
  return frame.height >= frame.width ? { width: 616, height: 1064 } : { width: 1064, height: 616 };
}

/** Where a camera frame lands when shrunk to fit inside the canvas, centered. */
export interface Placement { scale: number; width: number; height: number; left: number; top: number }

export function placeFrame(frame: Size, canvas: Size): Placement {
  const scale = Math.min(canvas.width / frame.width, canvas.height / frame.height);
  const width = Math.round(frame.width * scale);
  const height = Math.round(frame.height * scale);
  return { scale, width, height, left: Math.floor((canvas.width - width) / 2), top: Math.floor((canvas.height - height) / 2) };
}

const f32 = new Float32Array(1);
const f32Bits = new Uint32Array(f32.buffer);

/** Encodes numbers as IEEE 754 half precision, rounding to nearest even; the model's input format. */
export function toFloat16(values: Float32Array): Uint16Array {
  const out = new Uint16Array(values.length);
  for (let index = 0; index < values.length; index++) {
    f32[0] = values[index];
    const bits = f32Bits[0];
    const sign = (bits >>> 16) & 0x8000;
    const exponent = ((bits >>> 23) & 0xff) - 127 + 15;
    let mantissa = bits & 0x7fffff;
    if (((bits >>> 23) & 0xff) === 0xff) {
      out[index] = sign | 0x7c00 | (mantissa ? 0x200 : 0);
      continue;
    }
    if (exponent >= 31) {
      out[index] = sign | 0x7c00;
      continue;
    }
    let shift = 13;
    let half = sign | (exponent << 10);
    if (exponent <= 0) {
      if (exponent < -10) {
        out[index] = sign;
        continue;
      }
      mantissa |= 0x800000;
      shift = 14 - exponent;
      half = sign;
    }
    half += mantissa >>> shift;
    const rest = mantissa & ((1 << shift) - 1);
    const midpoint = 1 << (shift - 1);
    // Round to nearest, ties to even; a carry correctly moves into the exponent.
    if (rest > midpoint || (rest === midpoint && (half & 1))) half++;
    out[index] = half;
  }
  return out;
}

/** Decodes IEEE 754 half precision numbers; the model's output format. */
export function fromFloat16(bits: Uint16Array): Float32Array {
  const out = new Float32Array(bits.length);
  for (let index = 0; index < bits.length; index++) {
    const half = bits[index];
    const sign = half & 0x8000 ? -1 : 1;
    const exponent = (half >> 10) & 0x1f;
    const mantissa = half & 0x3ff;
    out[index] = exponent === 0 ? sign * mantissa * 2 ** -24 :
      exponent === 31 ? (mantissa ? NaN : sign * Infinity) :
      sign * (1 + mantissa / 1024) * 2 ** (exponent - 15);
  }
  return out;
}

/** The model's output at its own resolution: canonical depth, and normals as three planes x, y, z. */
export interface ModelOutput { width: number; height: number; depth: Float32Array; normals: Float32Array }

/** Metric3D predicts depth as a camera with this focal length, in pixels, would see it. */
const CANONICAL_FOCAL = 1000;

/**
 * The depth map of the camera frame alone: the canvas padding cropped away, depth turned into
 * meters for the frame's focal length (`frameFocal`, in the frame's pixels), normals per pixel.
 */
export function frameDepth(output: ModelOutput, canvas: Size, placement: Placement, frameFocal: number): DepthMap {
  const sx = output.width / canvas.width;
  const sy = output.height / canvas.height;
  const left = Math.round(placement.left * sx);
  const top = Math.round(placement.top * sy);
  const width = Math.round(placement.width * sx);
  const height = Math.round(placement.height * sy);
  const meters = frameFocal * placement.scale / CANONICAL_FOCAL;
  const plane = output.width * output.height;
  const depth = new Float32Array(width * height);
  const normals = new Float32Array(width * height * 3);
  for (let v = 0; v < height; v++) {
    for (let u = 0; u < width; u++) {
      const from = (v + top) * output.width + u + left;
      const to = v * width + u;
      depth[to] = output.depth[from] * meters;
      normals[to * 3] = output.normals[from];
      normals[to * 3 + 1] = output.normals[plane + from];
      normals[to * 3 + 2] = output.normals[2 * plane + from];
    }
  }
  const focal = frameFocal * placement.scale * sx;
  return { width, height, depth, normals, fx: focal, fy: focal, cx: width / 2, cy: height / 2 };
}
