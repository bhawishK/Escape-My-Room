import type { Position } from './protocol';

export interface CalibrationInput {
  yaw: number;
  origin: Position;
}

/** Map the current view onto the floor center, facing the desk. */
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
      y: 0,
      z: -(-sine * position.x + cosine * position.z),
    },
  };
}
