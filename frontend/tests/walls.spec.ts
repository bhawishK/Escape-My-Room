import { expect, test } from '@playwright/test';
import { cutAway, wallBox, wallsMiddle, type WallSegment } from '../src/quest/walls';

// The room's walls in the dollhouse (#269): the cut-away, and each wall's place.

const wall = (start: [number, number], end: [number, number]): WallSegment => ({ start, end, height: 2.5, thickness: 0.08 });
// A 4 x 3 m room round (2, 1.5): walls along z = 0 (near... -z side), x = 4, z = 3 and x = 0.
const ROOM = [wall([0, 0], [4, 0]), wall([4, 0], [4, 3]), wall([4, 3], [0, 3]), wall([0, 3], [0, 0])];

test('the room\'s middle is the middle of its walls', () => {
  expect(wallsMiddle(ROOM)).toEqual([2, 1.5]);
});

test('looking from outside beyond one wall cuts that wall away, and only that one', () => {
  // Beyond z = 3, looking in.
  expect(cutAway(ROOM, [2, 5])).toEqual([false, false, true, false]);
  // Beyond the corner at x = 4, z = 0: both walls meeting there.
  expect(cutAway(ROOM, [6, -2])).toEqual([true, true, false, false]);
  // Inside the room: none.
  expect(cutAway(ROOM, [2, 1.5])).toEqual([false, false, false, false]);
});

test('a wall split by a doorway is cut away piece by piece the same', () => {
  const split = [wall([4, 0], [4, 1]), wall([4, 2], [4, 3])];
  expect(cutAway([...ROOM.slice(0, 1), ...split, ...ROOM.slice(2)], [7, 1.5])).toEqual([false, true, true, false, false]);
});

test('each wall\'s box lies along it', () => {
  const along = wallBox(wall([0, 0], [4, 0]));
  expect(along).toEqual({ x: 2, z: 0, yaw: -0, length: 4 });
  const across = wallBox(wall([4, 0], [4, 3]));
  expect(across.x).toBe(4);
  expect(across.z).toBe(1.5);
  expect(across.length).toBe(3);
  // Running along +z: a quarter turn, local x to +z.
  expect(Math.cos(across.yaw)).toBeCloseTo(0, 9);
  expect(-Math.sin(across.yaw)).toBeCloseTo(1, 9);
});
