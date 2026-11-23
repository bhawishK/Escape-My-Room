import { expect, test } from '@playwright/test';
import { floorSpot, guidePath, spotUnder } from '../src/guide';

// Guiding from the dollhouse (#248): where a pointing ray meets the floor, and the phone's path to it.

test('a ray pointing down meets the floor where it is aimed', () => {
  // From 1.5 m up, down at 45 degrees towards -z: the floor 1.5 m ahead.
  const spot = floorSpot({ x: 0, y: 1.5, z: 0 }, { x: 0, y: 1, z: -0.5 });
  expect(spot!.x).toBeCloseTo(0, 9);
  expect(spot!.y).toBe(0);
  expect(spot!.z).toBeCloseTo(-1.5, 9);
});

test('a ray running level or upwards, or meeting the floor too far away, has no spot', () => {
  expect(floorSpot({ x: 0, y: 1.5, z: 0 }, { x: 0, y: 1.5, z: -1 })).toBeNull();
  expect(floorSpot({ x: 0, y: 1.5, z: 0 }, { x: 0, y: 2, z: -1 })).toBeNull();
  // Almost level: it would meet the floor 150 m away.
  expect(floorSpot({ x: 0, y: 1.5, z: 0 }, { x: 0, y: 1.49, z: -1 })).toBeNull();
});

test('the phone\'s path runs from its user\'s feet to the spot, along the floor', () => {
  const path = guidePath({ x: 1, y: 1.4, z: 2 }, { x: 1, y: 0, z: -1 });
  expect(path.from).toEqual({ x: 1, y: 0, z: 2 });
  expect(path.to).toEqual({ x: 1, y: 0, z: -1 });
  expect(path.length).toBeCloseTo(3, 9);
  // Straight ahead (-z) needs no turn; to the +x side, a quarter turn right (-pi/2).
  expect(path.yaw).toBeCloseTo(0, 9);
  expect(guidePath({ x: 0, y: 0, z: 0 }, { x: 2, y: 0, z: 0 }).yaw).toBeCloseTo(-Math.PI / 2, 9);
});

test('a pinch while guiding sets the floor spot under the fingertip (#273)', () => {
  expect(spotUnder({ x: 1.2, y: 0.35, z: -0.8 })).toEqual({ x: 1.2, y: 0, z: -0.8 });
});
