/**
 * Guiding from the dollhouse (#248, part of #221): the commander points with an index finger, and
 * where that ray meets the floor is sent to the phone, which draws a path along its real floor to
 * it. The literature says a remote hand alone is hard to read from another viewpoint; pairing it
 * with a pointer helps (Kim et al., CHI 2019). Shared by the headset (the spot) and the phone (the
 * path).
 */
import type { Position } from './protocol';

/** A spot further than this from where the ray starts, in room metres, is no spot. */
export const GUIDE_REACH_METRES = 30;

/**
 * Where the ray from `from` through `through` (room metres) meets the floor at `floorY`, or null
 * if it runs level, upwards, or further than `reach`.
 */
export function floorSpot(from: Position, through: Position, floorY = 0, reach = GUIDE_REACH_METRES): Position | null {
  const dx = through.x - from.x;
  const dy = through.y - from.y;
  const dz = through.z - from.z;
  if (dy >= -1e-9) return null;
  const t = (floorY - from.y) / dy;
  if (t < 0) return null;
  const spot = { x: from.x + t * dx, y: floorY, z: from.z + t * dz };
  return Math.hypot(spot.x - from.x, spot.y - from.y, spot.z - from.z) <= reach ? spot : null;
}

/** The floor spot under a point in room metres, as a pinch sets the guide's spot (#273). */
export function spotUnder(point: Position, floorY = 0): Position {
  return { x: point.x, y: floorY, z: point.z };
}

/** The path the phone draws: from where its user stands to the spot, along the floor. */
export interface GuidePath {
  from: Position;
  to: Position;
  length: number;
  /** Radians about the vertical, as three.js turns rotation.y, for a strip lying along it. */
  yaw: number;
}

/** The path from the phone user's feet (`at`, any height) to `spot`, on the floor at `floorY`. */
export function guidePath(at: Position, spot: Position, floorY = 0): GuidePath {
  const from = { x: at.x, y: floorY, z: at.z };
  const to = { x: spot.x, y: floorY, z: spot.z };
  const dx = to.x - from.x;
  const dz = to.z - from.z;
  // A strip's length lies along its local -z; turned by yaw it runs from `from` to `to`.
  return { from, to, length: Math.hypot(dx, dz), yaw: Math.atan2(-dx, -dz) };
}
