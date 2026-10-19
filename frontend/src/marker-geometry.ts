import type { CameraIntrinsics, Position, Rotation, TrackingMarker } from './protocol';

/** Where the phone is in the room and which way its camera faces, as a Three.js camera would. */
export interface RoomPose {
  position: Position;
  /** Unit quaternion (x, y, z, w); the camera looks along its local -Z with +Y up. */
  orientation: Rotation;
}

function rotate(q: Rotation, x: number, y: number, z: number): Position {
  // v' = v + 2w(u × v) + 2u × (u × v), where u is the quaternion's vector part.
  const tx = 2 * (q.y * z - q.z * y);
  const ty = 2 * (q.z * x - q.x * z);
  const tz = 2 * (q.x * y - q.y * x);
  return {
    x: x + q.w * tx + (q.y * tz - q.z * ty),
    y: y + q.w * ty + (q.z * tx - q.x * tz),
    z: z + q.w * tz + (q.x * ty - q.y * tx),
  };
}

/** The black square's corners in the tag's own frame, in the order OpenCV's detector reports them. */
export function squareCorners(size: number): Position[] {
  const half = size / 2;
  return [{ x: -half, y: half, z: 0 }, { x: half, y: half, z: 0 }, { x: half, y: -half, z: 0 }, { x: -half, y: -half, z: 0 }];
}

/**
 * The marker's black-square corners in room coordinates, in the order OpenCV's ArUco detector
 * reports them: the printed tag's top-left, top-right, bottom-right, then bottom-left.
 */
export function markerCorners(marker: TrackingMarker): Position[] {
  return squareCorners(marker.size).map(({ x, y }) => {
    const turned = rotate(marker.rotation, x, y, 0);
    return {
      x: marker.position.x + turned.x,
      y: marker.position.y + turned.y,
      z: marker.position.z + turned.z,
    };
  });
}

/**
 * Re-expresses a solvePnP result in the tag's own frame (a tag point X lands at R X + t) as one in
 * the room's frame. Rotations are row-major 3 x 3 matrices.
 */
export function roomFromMarkerPnP(
  marker: TrackingMarker, rotation: ArrayLike<number>, translation: ArrayLike<number>,
): { rotation: number[]; translation: number[] } {
  const r = Array.from(rotation);
  const t = Array.from(translation);
  // The tag's axes in room coordinates, as the columns of M; a room point X is Mᵀ (X - p) in the tag.
  const axes = [rotate(marker.rotation, 1, 0, 0), rotate(marker.rotation, 0, 1, 0), rotate(marker.rotation, 0, 0, 1)];
  const m = [0, 1, 2].map(row => axes.map(axis => [axis.x, axis.y, axis.z][row]));
  // R' = R Mᵀ and t' = t - R' p.
  const combined: number[] = [];
  for (let row = 0; row < 3; row++) {
    for (let column = 0; column < 3; column++) {
      combined.push(r[row * 3] * m[column][0] + r[row * 3 + 1] * m[column][1] + r[row * 3 + 2] * m[column][2]);
    }
  }
  const { x, y, z } = marker.position;
  return {
    rotation: combined,
    translation: [0, 1, 2].map(row => t[row] - (combined[row * 3] * x + combined[row * 3 + 1] * y + combined[row * 3 + 2] * z)),
  };
}

/**
 * The phone's room pose from OpenCV's solvePnP result, where a room point X lands in the camera
 * as R X + t. `rotation` is R in row-major order. OpenCV's camera looks along +Z with +Y down;
 * the returned orientation is turned to look along -Z with +Y up, as Three.js cameras do.
 */
export function roomPoseFromPnP(rotation: ArrayLike<number>, translation: ArrayLike<number>): RoomPose {
  const r = Array.from(rotation);
  const [tx, ty, tz] = Array.from(translation);
  // The camera center is -Rᵀ t.
  const position = {
    x: -(r[0] * tx + r[3] * ty + r[6] * tz),
    y: -(r[1] * tx + r[4] * ty + r[7] * tz),
    z: -(r[2] * tx + r[5] * ty + r[8] * tz),
  };
  // Rᵀ holds the camera axes in room coordinates as columns; negate its Y and Z columns.
  const m = [
    [r[0], -r[3], -r[6]],
    [r[1], -r[4], -r[7]],
    [r[2], -r[5], -r[8]],
  ];
  return { position, orientation: quaternionFromMatrix(m) };
}

function quaternionFromMatrix(m: number[][]): Rotation {
  const trace = m[0][0] + m[1][1] + m[2][2];
  let q: Rotation;
  if (trace > 0) {
    const s = 0.5 / Math.sqrt(trace + 1);
    q = { w: 0.25 / s, x: (m[2][1] - m[1][2]) * s, y: (m[0][2] - m[2][0]) * s, z: (m[1][0] - m[0][1]) * s };
  } else if (m[0][0] > m[1][1] && m[0][0] > m[2][2]) {
    const s = 2 * Math.sqrt(1 + m[0][0] - m[1][1] - m[2][2]);
    q = { w: (m[2][1] - m[1][2]) / s, x: 0.25 * s, y: (m[0][1] + m[1][0]) / s, z: (m[0][2] + m[2][0]) / s };
  } else if (m[1][1] > m[2][2]) {
    const s = 2 * Math.sqrt(1 + m[1][1] - m[0][0] - m[2][2]);
    q = { w: (m[0][2] - m[2][0]) / s, x: (m[0][1] + m[1][0]) / s, y: 0.25 * s, z: (m[1][2] + m[2][1]) / s };
  } else {
    const s = 2 * Math.sqrt(1 + m[2][2] - m[0][0] - m[1][1]);
    q = { w: (m[1][0] - m[0][1]) / s, x: (m[0][2] + m[2][0]) / s, y: (m[1][2] + m[2][1]) / s, z: 0.25 * s };
  }
  const norm = Math.hypot(q.x, q.y, q.z, q.w);
  return { x: q.x / norm, y: q.y / norm, z: q.z / norm, w: q.w / norm };
}

/**
 * The same camera's intrinsics for its frames resized to `width` x `height`. Pixel centers stay
 * aligned, so a principal point c becomes (c + 0.5) · scale - 0.5. Distortion is unit-free.
 */
export function resizeIntrinsics(intrinsics: CameraIntrinsics, width: number, height: number): CameraIntrinsics {
  const sx = width / intrinsics.width;
  const sy = height / intrinsics.height;
  return {
    width,
    height,
    fx: intrinsics.fx * sx,
    fy: intrinsics.fy * sy,
    cx: (intrinsics.cx + 0.5) * sx - 0.5,
    cy: (intrinsics.cy + 0.5) * sy - 0.5,
    distortion: [...intrinsics.distortion],
  };
}

/** The processing size for a video frame: its long side at most `longSide`, aspect kept. */
export function processingSize(width: number, height: number, longSide: number): { width: number; height: number } {
  const scale = Math.min(1, longSide / Math.max(width, height));
  return { width: Math.round(width * scale), height: Math.round(height * scale) };
}
