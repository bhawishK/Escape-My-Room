import { assumedIntrinsics } from '../src/marker-geometry';
import type { CameraIntrinsics, Position, TrackingMarker } from '../src/protocol';

/* What the synthetic fake-camera videos show, shared by their setup and the tests that check them. */

/** The fake marker camera: 1280 x 720 with the same lens the phone page assumes for the iPhone. */
export const MARKER_CAMERA: CameraIntrinsics = assumedIntrinsics(1280, 720);
/** The stand-in room's tag, as its manifest places it. */
export const DESK_MARKER: TrackingMarker = {
  id: 0, label: 'Desk front', size: 0.15, position: { x: 0, y: 0.6, z: -0.9 }, rotation: { x: 0, y: 0, z: 0, w: 1 },
};
/** Where the fake camera stands, looking at the desk tag. */
export const STANDING_AT: Position = { x: 0.2, y: 1.3, z: 0.1 };
