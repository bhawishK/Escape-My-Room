import { expect, test } from '@playwright/test';
import { looksToTake } from '../src/quest/dollhouse';
import { PALM_HOLD_MS, PalmToggle, pageAt, wristChoice, wristMenu } from '../src/quest/wrist-menu';
import type { Position } from '../src/protocol';

// #204: the wrist menu, a slider of Objects, Make, Edit and Exit, shown on an open left palm.

function close(actual: Position | undefined, expected: Position): void {
  expect(actual).toBeDefined();
  expect(actual!.x).toBeCloseTo(expected.x, 5);
  expect(actual!.y).toBeCloseTo(expected.y, 5);
  expect(actual!.z).toBeCloseTo(expected.z, 5);
}

const HAND = { x: 0, y: 1, z: -0.4 };

test('the slider has a stop for each page in a row above the hand, Objects on the left', () => {
  const menu = wristMenu(HAND, 0, 'objects', 2);
  // Objects, Make, Drill (#234), Edit, Exit.
  expect(menu.stops).toHaveLength(5);
  close(menu.stops[0], { x: -0.13, y: 1.22, z: -0.4 });
  close(menu.stops[4], { x: 0.13, y: 1.22, z: -0.4 });
  // Facing left (-x), the person's right is -z.
  close(wristMenu(HAND, Math.PI / 2, 'objects', 2).stops[0], { x: 0, y: 1.22, z: -0.4 + 0.13 });
});

test('each page shows only its own things: pieces, speak and make, pick and run, move and resize, or exit', () => {
  const objects = wristMenu(HAND, 0, 'objects', 3);
  expect(objects.pieces).toHaveLength(3);
  close(objects.pieces[0], { x: -0.06, y: 1.12, z: -0.4 });
  expect(objects.buttons).toEqual({});

  const make = wristMenu(HAND, 0, 'make', 3);
  expect(make.pieces).toEqual([]);
  close(make.buttons.speak, { x: -0.04, y: 1.12, z: -0.4 });
  close(make.buttons.make, { x: 0.04, y: 1.12, z: -0.4 });

  const drill = wristMenu(HAND, 0, 'drill', 3);
  close(drill.buttons.pick, { x: -0.04, y: 1.12, z: -0.4 });
  close(drill.buttons.run, { x: 0.04, y: 1.12, z: -0.4 });

  const edit = wristMenu(HAND, 0, 'edit', 3);
  close(edit.buttons.move, { x: -0.04, y: 1.12, z: -0.4 });
  close(edit.buttons.resize, { x: 0.04, y: 1.12, z: -0.4 });

  expect(Object.keys(wristMenu(HAND, 0, 'exit', 3).buttons)).toEqual(['exit']);
});

test('a pinch chooses the piece or button it is on, the track, or nothing', () => {
  const objects = wristMenu(HAND, 0, 'objects', 3);
  expect(wristChoice(objects, { x: 0.055, y: 1.125, z: -0.4 })).toEqual({ kind: 'piece', index: 2 });
  expect(wristChoice(objects, { x: 0.3, y: 1.12, z: -0.4 })).toBeNull();
  const edit = wristMenu(HAND, 0, 'edit', 3);
  expect(wristChoice(edit, { x: 0.035, y: 1.12, z: -0.41 })).toEqual({ kind: 'button', button: 'resize' });
  // Anywhere along the track, between its stops too, is the track.
  expect(wristChoice(edit, { x: 0.02, y: 1.23, z: -0.4 })).toEqual({ kind: 'track' });
  expect(wristChoice(edit, { x: 0.2, y: 1.22, z: -0.4 })).toBeNull();
});

test('sliding along the track goes to the page whose stop is nearest, and no further than its ends', () => {
  const menu = wristMenu(HAND, 0, 'objects', 0);
  expect(pageAt(menu, { x: -0.12, y: 1.22, z: -0.4 })).toBe('objects');
  expect(pageAt(menu, { x: -0.06, y: 1.22, z: -0.4 })).toBe('make');
  expect(pageAt(menu, { x: 0.01, y: 1.22, z: -0.4 })).toBe('drill');
  expect(pageAt(menu, { x: 0.06, y: 1.22, z: -0.4 })).toBe('edit');
  expect(pageAt(menu, { x: 0.5, y: 1.22, z: -0.4 })).toBe('exit');
  expect(pageAt(menu, { x: -0.5, y: 1.22, z: -0.4 })).toBe('objects');
});

test('an open palm held a moment opens the menu, and a fist held a moment closes it', () => {
  const palm = new PalmToggle();
  expect(palm.update('open-palm', 0)).toBe(false);
  expect(palm.update('open-palm', PALM_HOLD_MS)).toBe(true);
  // Relaxing the hand a little keeps it open; a fist only passing by does too.
  expect(palm.update('none', 300)).toBe(true);
  expect(palm.update('fist', 400)).toBe(true);
  expect(palm.update('fist', 400 + PALM_HOLD_MS)).toBe(false);
  expect(palm.closingFist).toBe(true);
  expect(palm.update('none', 700)).toBe(false);
  expect(palm.closingFist).toBe(false);
});

test('a fist with the menu already closed is free to mute, and a hand out of sight closes it', () => {
  const palm = new PalmToggle();
  palm.update('fist', 0);
  palm.update('fist', 500);
  expect(palm.closingFist).toBe(false);
  palm.update('open-palm', 600);
  expect(palm.update('open-palm', 800)).toBe(true);
  expect(palm.update(null, 900)).toBe(false);
});

test('looking at a piece and pinching takes it only in the small dollhouse, not at life size', () => {
  expect(looksToTake(1)).toBe(false);
  expect(looksToTake(0.1)).toBe(true);
});
