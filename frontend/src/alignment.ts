import type { Position } from './protocol';

export interface CalibrationInput {
  yaw: number;
  origin: Position;
}

/** How high both people's eyes start above the room's floor, in meters: the phone's view and the headset's. */
export const STANDING_EYE_HEIGHT = 1.5;

/**
 * Map the current view onto the floor center, facing the desk, with the eyes at
 * `STANDING_EYE_HEIGHT`. The `local` space has no floor, so the head's height when confirming
 * becomes standing eye height; moving up or down afterwards still moves the view.
 */
export function alignmentFromPose(
  position: Position,
  orientation: { x: number; y: number; z: number; w: number },
): CalibrationInput {
  const { x: qx, y: qy, z: qz, w: qw } = orientation;
  const forwardX = -2 * (qw * qy + qx * qz);
  const forwardZ = -1 + 2 * (qx * qx + qy * qy);
  const yaw = Math.atan2(forwardX, -forwardZ);
  const cosine = Math.cos(yaw);
  const sine = Math.sin(yaw);
  return {
    yaw,
    origin: {
      x: -(cosine * position.x + sine * position.z),
      y: STANDING_EYE_HEIGHT - position.y,
      z: -(-sine * position.x + cosine * position.z),
    },
  };
}

/** A WebXR point in room meters, using the same yaw and origin Python stores. */
export function roomPoint(alignment: CalibrationInput, point: Position): Position {
  const cosine = Math.cos(alignment.yaw);
  const sine = Math.sin(alignment.yaw);
  return {
    x: cosine * point.x + sine * point.z + alignment.origin.x,
    y: point.y + alignment.origin.y,
    z: -sine * point.x + cosine * point.z + alignment.origin.z,
  };
}

/**
 * Heading in the room for a WebXR viewer quaternion (x, y, z, w).
 * 0 faces the desk. Positive turns left. This matches `room_heading` in Python.
 */
export function roomHeading(
  alignment: CalibrationInput,
  orientation: { x: number; y: number; z: number; w: number },
): number {
  const { x: qx, y: qy, z: qz, w: qw } = orientation;
  const forwardX = -2 * (qw * qy + qx * qz);
  const forwardZ = -1 + 2 * (qx * qx + qy * qy);
  const cosine = Math.cos(alignment.yaw);
  const sine = Math.sin(alignment.yaw);
  const roomX = cosine * forwardX + sine * forwardZ;
  const roomZ = -sine * forwardX + cosine * forwardZ;
  return Math.atan2(-roomX, -roomZ);
}
