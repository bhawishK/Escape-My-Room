/**
 * Where a carried object goes: where the ray from the phone's screen centre meets the floor.
 * Python places the object with the same rule (backend/sessions.py `carry`); the phone uses this to
 * draw it there at once, rather than waiting for Python's answer.
 */
import type { Position } from './protocol';
import type { Floorplan } from './steps';

export const CARRY_NEAREST = 0.3;
export const CARRY_FARTHEST = 4.0;

/**
 * The point on the floor at height `floorY` that the screen centre aims at, from `eye`, facing
 * `heading` (0 toward the desk, positive left) and tilted by `pitch` (negative looks down).
 * Level, upward or a phone below the floor never meets it, so the point is at the furthest. A point
 * past the floor's edge is pulled back by `margin`, so an object that wide stays whole on it.
 */
export function floorPoint(
  eye: Position, heading: number, pitch: number, floorY: number, floor: Floorplan['floor'], margin: number,
): Position {
  const drop = eye.y - floorY;
  const ahead = pitch < 0 && drop > 0 ? drop / Math.tan(-pitch) : CARRY_FARTHEST;
  const distance = Math.max(CARRY_NEAREST, Math.min(CARRY_FARTHEST, ahead));
  let x = eye.x - Math.sin(heading) * distance;
  let z = eye.z - Math.cos(heading) * distance;
  if (floor) {
    x = Math.max(floor.minX + margin, Math.min(floor.maxX - margin, x));
    z = Math.max(floor.minZ + margin, Math.min(floor.maxZ - margin, z));
  }
  const bounded = (value: number) => Math.max(-100, Math.min(100, value));
  return { x: bounded(x), y: floorY, z: bounded(z) };
}
