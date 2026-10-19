import type { CameraIntrinsics, Position, TrackingMarker } from '../src/protocol';

/* What the synthetic fake-camera videos show, shared by their setup and the tests that check them. */

/** The fake marker camera: 1280 x 720 with a known pinhole and no distortion. */
export const MARKER_CAMERA: CameraIntrinsics = {
  width: 1280, height: 720, fx: 1000, fy: 1000, cx: 639.5, cy: 359.5, distortion: [0, 0, 0, 0, 0],
};
/** The stand-in room's tag, as its manifest places it. */
export const DESK_MARKER: TrackingMarker = {
  id: 0, label: 'Desk front', size: 0.15, position: { x: 0, y: 0.6, z: -0.9 }, rotation: { x: 0, y: 0, z: 0, w: 1 },
};
/** Where the fake camera stands, looking at the desk tag. */
export const STANDING_AT: Position = { x: 0.2, y: 1.3, z: 0.1 };

/** The fake board camera, smaller so the looping video stays small. */
export const BOARD_CAMERA: CameraIntrinsics = {
  width: 640, height: 360, fx: 520, fy: 522, cx: 322, cy: 178, distortion: [0, 0, 0, 0, 0],
};
export const BOARD_TILTS: [number, number, number][] = [
  [0, 0, 0], [0.35, 0, 0], [-0.35, 0, 0], [0, 0.35, 0], [0, -0.35, 0], [0.25, 0.25, 0.1], [-0.25, 0.3, -0.1],
  [0.3, -0.25, 0.2], [-0.3, -0.3, 0], [0.15, 0.4, 0.3], [0.4, 0.1, -0.2], [-0.1, -0.4, 0.1], [0.2, -0.1, -0.3],
  [-0.2, 0.15, 0.25], [0.05, 0.3, -0.15], [-0.35, -0.1, 0.2], [0.3, 0.3, 0], [-0.15, -0.35, -0.2],
];
