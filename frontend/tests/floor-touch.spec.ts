import { expect, test } from '@playwright/test';
import { FLOOR_TOUCH_MS, FloorTouch, JOINT_ABOVE_FLOOR, refloored, withFloor } from '../src/quest/floor-touch';
import type { Position } from '../src/protocol';

// #218: touching the real floor sets the room's floor on the headset. Joint positions are in the
// headset's reference space, whose y = 0 is where the Quest thinks the floor is.

/** A hand lying flat at `y` (its joints' centres), fingers along -z, `tilt` metres higher at the tips. */
function flatHand(y: number, x = 0.3, z = -0.4, tilt = 0): Position[] {
  const along = [0, 0.04, 0.07, 0.1, 0.13, 0.16, 0.18, 0.19, 0.17, 0.15];
  return along.map((distance, index) => ({
    x: x + (index % 5 - 2) * 0.02,
    y: y + tilt * distance / 0.19,
    z: z - distance,
  }));
}

function hold(touch: FloorTouch, joints: (at: number) => Position[], from: number, ms: number): number | null {
  let found: number | null = null;
  for (let at = from; at <= from + ms; at += 50) found = touch.add(joints(at), at) ?? found;
  return found;
}

test('a palm resting flat and still on the floor for a second sets the floor there', () => {
  // The Quest thinks the floor is 12 cm higher than it is: the palm rests at -0.12.
  const touch = new FloorTouch();
  const resting = -0.12 + JOINT_ABOVE_FLOOR;
  expect(hold(touch, () => flatHand(resting), 0, FLOOR_TOUCH_MS - 100)).toBeNull();
  const floor = hold(touch, () => flatHand(resting), FLOOR_TOUCH_MS - 50, 200);
  expect(floor).not.toBeNull();
  expect(floor!).toBeCloseTo(-0.12, 3);
});

test('a hand that moves, is not flat, or is high above the floor sets nothing', () => {
  const resting = JOINT_ABOVE_FLOOR;
  // Sliding along the floor.
  expect(hold(new FloorTouch(), at => flatHand(resting, 0.3 + at / 5000), 0, 2000)).toBeNull();
  // Fingers pointing down at the floor, not lying on it.
  expect(hold(new FloorTouch(), () => flatHand(resting, 0.3, -0.4, 0.15), 0, 2000)).toBeNull();
  // Flat and still, but held at waist height.
  expect(hold(new FloorTouch(), () => flatHand(0.9), 0, 2000)).toBeNull();
  // No hand seen.
  expect(hold(new FloorTouch(), () => [], 0, 2000)).toBeNull();
});

test('a measured floor moves the room down to it and keeps the rest of the alignment', () => {
  const aligned = { yaw: 0.4, origin: { x: 1.2, y: 0, z: -0.3 } };
  const moved = withFloor(aligned, -0.12);
  // A room point at y = 0 (its floor) is drawn at -0.12 in the headset's space: room = space + origin.
  expect(moved.origin.y).toBeCloseTo(0.12, 6);
  expect(moved.yaw).toBe(0.4);
  expect(moved.origin.x).toBe(1.2);
  expect(moved.origin.z).toBe(-0.3);
  expect(withFloor(aligned, null)).toEqual(aligned);
});

test('touching the floor again after lining up moves the room by the difference, and nothing else', () => {
  // Lined up with the floor touched at -0.12; touched again at -0.05.
  const lined = withFloor({ yaw: 0.4, origin: { x: 1.2, y: 0, z: -0.3 } }, -0.12);
  const again = refloored(lined, -0.12, -0.05);
  expect(again).toEqual(withFloor({ yaw: 0.4, origin: { x: 1.2, y: 0, z: -0.3 } }, -0.05));
  // Lined up before any touch: the first touch moves it the whole way.
  const first = refloored({ yaw: 0, origin: { x: 0, y: 0, z: 0 } }, null, -0.1);
  expect(first.origin.y).toBeCloseTo(0.1, 9);
});
