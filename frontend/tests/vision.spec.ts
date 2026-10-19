import { expect, test } from '@playwright/test';
import { processingSize, resizeIntrinsics, type RoomPose } from '../src/marker-geometry';
import type { CameraIntrinsics, Position, TrackingMarker } from '../src/protocol';
import { BoardCalibrator, MarkerLocator, type OpenCV } from '../src/vision';
import { loadOpenCV, lookAt, renderBoard, renderMarkers, type CameraView } from './synthetic';

// Synthetic frames from known poses check the measurement math; they are not device evidence.
const CAMERA: CameraIntrinsics = { width: 960, height: 540, fx: 760, fy: 760, cx: 479.5, cy: 269.5, distortion: [0, 0, 0, 0, 0] };
const IDENTITY = { x: 0, y: 0, z: 0, w: 1 };
// The stand-in room's tag: upright on the desk's front face, facing the viewer.
const DESK: TrackingMarker = { id: 0, label: 'Desk front', size: 0.15, position: { x: 0, y: 0.6, z: -0.9 }, rotation: IDENTITY };
const HALF_TURN_Y = Math.SQRT1_2;
// A tag on a wall to the room's left, facing +X.
const WALL: TrackingMarker = {
  id: 5, label: 'Left wall', size: 0.15, position: { x: -0.9, y: 0.9, z: -0.3 }, rotation: { x: 0, y: HALF_TURN_Y, z: 0, w: HALF_TURN_Y },
};
const STANDING = { x: 0, y: 1.4, z: 0 };

let cv: OpenCV;
let locator: MarkerLocator;
test.beforeAll(async () => {
  ({ cv } = await loadOpenCV());
  locator = new MarkerLocator(cv);
});

function track(view: CameraView, markers: TrackingMarker[], seen = markers, camera = CAMERA): RoomPose {
  const result = locator.locate(renderMarkers(cv, CAMERA, view, seen), camera, markers);
  if (result.kind !== 'tracked') throw new Error(result.reason);
  return result.pose;
}

function expectNear(actual: Position, expected: Position, tolerance: number): void {
  expect(Math.hypot(actual.x - expected.x, actual.y - expected.y, actual.z - expected.z)).toBeLessThan(tolerance);
}

/** The direction the returned orientation looks along: its local -Z turned into the room. */
function viewDirection(q: RoomPose['orientation']): Position {
  return { x: -2 * (q.x * q.z + q.w * q.y), y: -2 * (q.y * q.z - q.w * q.x), z: -(1 - 2 * (q.x * q.x + q.y * q.y)) };
}

test('the phone is placed where it stands, looking where it looks', () => {
  const view = lookAt(STANDING, DESK.position);
  const pose = track(view, [DESK]);
  expectNear(pose.position, STANDING, 0.01);
  const direction = viewDirection(pose.orientation);
  expect(direction.x * view.forward.x + direction.y * view.forward.y + direction.z * view.forward.z).toBeGreaterThan(Math.cos(Math.PI / 180));
});

test('moving the phone along each room axis moves it that far along that axis', () => {
  const start = track(lookAt(STANDING, DESK.position), [DESK]).position;
  for (const step of [{ x: 0.3, y: 0, z: 0 }, { x: 0, y: -0.3, z: 0 }, { x: 0, y: 0, z: -0.3 }]) {
    const moved = { x: STANDING.x + step.x, y: STANDING.y + step.y, z: STANDING.z + step.z };
    // Keep the camera's heading while it moves, so only translation changes.
    const view = { ...lookAt(STANDING, DESK.position), center: moved };
    const end = track(view, [DESK]).position;
    expectNear({ x: end.x - start.x, y: end.y - start.y, z: end.z - start.z }, step, 0.01);
  }
});

test('turning the phone in place does not move it', () => {
  // A lone 15 cm tag seen off-center from 1.2 m measures depth to about 1 %, so allow 2 cm.
  for (const target of [{ x: 0.12, y: 0.6, z: -0.9 }, { x: -0.1, y: 0.72, z: -0.9 }]) {
    expectNear(track(lookAt(STANDING, target), [DESK]).position, STANDING, 0.02);
  }
});

test('a rotated tag and two tags at once give the same room position', () => {
  const corner = { x: 0.3, y: 1.3, z: 0.4 };
  expectNear(track(lookAt(corner, WALL.position), [DESK, WALL], [WALL]).position, corner, 0.015);
  expectNear(track(lookAt(corner, { x: -0.45, y: 0.75, z: -0.6 }), [DESK, WALL]).position, corner, 0.015);
});

test('frames without a known tag are reported unseen with a reason', () => {
  const view = lookAt(STANDING, DESK.position);
  const other = { ...DESK, id: 9 };
  const unknown = locator.locate(renderMarkers(cv, CAMERA, view, [other]), CAMERA, [DESK]);
  expect(unknown).toEqual({ kind: 'unseen', reason: 'Only markers this room does not use are in view.' });
  const empty = locator.locate(renderMarkers(cv, CAMERA, view, []), CAMERA, [DESK]);
  expect(empty).toEqual({ kind: 'unseen', reason: 'No room marker in view.' });
  const far = locator.locate(renderMarkers(cv, CAMERA, lookAt({ x: 0, y: 1.0, z: 4.8 }, DESK.position), [DESK]), CAMERA, [DESK]);
  expect(far).toEqual({ kind: 'unseen', reason: 'The marker is too far away. Move closer.' });
});

test('intrinsics follow a frame resized for processing', () => {
  const video: CameraIntrinsics = { ...CAMERA, width: 1920, height: 1080, fx: 1520, fy: 1520, cx: 959.5, cy: 539.5 };
  const size = processingSize(video.width, video.height, 960);
  expect(size).toEqual({ width: 960, height: 540 });
  const resized = resizeIntrinsics(video, size.width, size.height);
  expect(resized).toEqual({ ...CAMERA });
  expect(processingSize(720, 1280, 960)).toEqual({ width: 540, height: 960 });
});

test('board views recover the camera intrinsics', () => {
  const truth: CameraIntrinsics = { ...CAMERA, fx: 742, fy: 745, cx: 486, cy: 262 };
  const calibrator = new BoardCalibrator(cv);
  const tilts: [number, number, number][] = [
    [0, 0, 0], [0.35, 0, 0], [-0.35, 0, 0], [0, 0.35, 0], [0, -0.35, 0], [0.25, 0.25, 0.1],
    [-0.25, 0.3, -0.1], [0.3, -0.25, 0.2], [-0.3, -0.3, 0], [0.15, 0.4, 0.3], [0.4, 0.1, -0.2], [-0.1, -0.4, 0.1],
  ];
  for (const [index, tilt] of tilts.entries()) {
    expect(calibrator.addView(renderBoard(cv, truth, tilt, 0.32 + 0.02 * (index % 3))).kept).toBe(true);
  }
  const { intrinsics, rmsPx } = calibrator.solve();
  expect(rmsPx).toBeLessThan(0.5);
  expect(Math.abs(intrinsics.fx / truth.fx - 1)).toBeLessThan(0.01);
  expect(Math.abs(intrinsics.fy / truth.fy - 1)).toBeLessThan(0.01);
  expect(Math.abs(intrinsics.cx - truth.cx)).toBeLessThan(6);
  expect(Math.abs(intrinsics.cy - truth.cy)).toBeLessThan(6);
  expect(intrinsics.distortion).toHaveLength(5);
});
