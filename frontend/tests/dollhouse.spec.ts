import { expect, test } from '@playwright/test';
import { pinchPoint } from '../src/quest/gestures';
import {
  DollhouseScaling, LIFE_SIZE, fromDollhouse, scaleLabel, orientationFromDollhouse, orientationToDollhouse, toDollhouse,
  velocityFromDollhouse, velocityToDollhouse, type DollhouseView,
} from '../src/quest/dollhouse';

// The dollhouse on the headset page (#180): the room drawn smaller, in the headset's `local` space.
// "Room space" is that space with the room at life size; "dollhouse space" is where it is drawn.

/** A twentieth-size room, turned a quarter left and put on a table 1 m ahead at waist height. */
const TABLE: DollhouseView = { scale: 0.05, yaw: Math.PI / 2, offset: { x: 0, y: 0.8, z: -1 } };

const close = (actual: { x: number; y: number; z: number }, expected: { x: number; y: number; z: number }) => {
  expect(actual.x).toBeCloseTo(expected.x, 9);
  expect(actual.y).toBeCloseTo(expected.y, 9);
  expect(actual.z).toBeCloseTo(expected.z, 9);
};

test('a point 2 m ahead in the room is 10 cm to the left of the table point at a twentieth size', () => {
  // A quarter turn left takes ahead (-z) to the left (-x).
  close(toDollhouse(TABLE, { x: 0, y: 0, z: -2 }), { x: -0.1, y: 0.8, z: -1 });
  close(fromDollhouse(TABLE, { x: -0.1, y: 0.8, z: -1 }), { x: 0, y: 0, z: -2 });
});

test('points, velocities and turns go into the dollhouse and back unchanged', () => {
  const point = { x: 1.2, y: 0.4, z: -3.1 };
  close(fromDollhouse(TABLE, toDollhouse(TABLE, point)), point);
  const velocity = { x: 0.3, y: -1, z: 2 };
  close(velocityFromDollhouse(TABLE, velocityToDollhouse(TABLE, velocity)), velocity);
  const turn = { x: 0.1, y: 0.7, z: -0.2, w: 0.68 };
  const back = orientationFromDollhouse(TABLE, orientationToDollhouse(TABLE, turn));
  const sign = Math.sign(back.w) === Math.sign(turn.w) ? 1 : -1;
  for (const key of ['x', 'y', 'z', 'w'] as const) expect(sign * back[key]).toBeCloseTo(turn[key], 9);
});

test('a hand moving 5 cm a second in a twentieth-size room moves 1 m a second in the room', () => {
  close(velocityFromDollhouse({ ...TABLE, yaw: 0 }, { x: 0.05, y: 0, z: 0 }), { x: 1, y: 0, z: 0 });
});

test('at life size nothing moves', () => {
  const point = { x: 0.5, y: 1.1, z: -0.7 };
  close(toDollhouse(LIFE_SIZE, point), point);
  close(fromDollhouse(LIFE_SIZE, point), point);
});

test('a quarter turn of the room turns a turn the same way', () => {
  const turn = orientationToDollhouse(TABLE, { x: 0, y: 0, z: 0, w: 1 });
  expect(turn.y).toBeCloseTo(Math.SQRT1_2, 9);
  expect(turn.w).toBeCloseTo(Math.SQRT1_2, 9);
  expect(Math.hypot(turn.x, turn.z)).toBeCloseTo(0, 9);
});

/** Two pinches `apart` metres apart, side by side at chest height 40 cm ahead, around `centre`. */
const hands = (apart: number, centre = { x: 0, y: 1.2, z: -0.4 }) => [
  { x: centre.x - apart / 2, y: centre.y, z: centre.z },
  { x: centre.x + apart / 2, y: centre.y, z: centre.z },
];

test('pulling two pinched hands from 60 cm to 6 cm apart shrinks the room to a tenth around them', () => {
  const scaling = new DollhouseScaling();
  scaling.update(hands(0.6), true);
  expect(scaling.scaling).toBe(true);
  const view = scaling.update(hands(0.06), true);
  expect(view.scale).toBeCloseTo(0.1, 9);
  // The room point that was between the hands is still between them.
  close(toDollhouse(view, { x: 0, y: 1.2, z: -0.4 }), { x: 0, y: 1.2, z: -0.4 });
});

test('the room follows the hands when both move together while scaling', () => {
  const scaling = new DollhouseScaling();
  scaling.update(hands(0.6), true);
  const view = scaling.update(hands(0.06, { x: 0.2, y: 1.0, z: -0.5 }), true);
  close(toDollhouse(view, { x: 0, y: 1.2, z: -0.4 }), { x: 0.2, y: 1.0, z: -0.5 });
});

test('letting go of either hand stops scaling and keeps the size', () => {
  const scaling = new DollhouseScaling();
  scaling.update(hands(0.6), true);
  scaling.update(hands(0.06), true);
  const view = scaling.update([hands(0.06)[0]], true);
  expect(scaling.scaling).toBe(false);
  expect(view.scale).toBeCloseTo(0.1, 9);
  // One hand alone moving afterwards changes nothing.
  expect(scaling.update([{ x: 1, y: 1, z: 1 }], true).scale).toBeCloseTo(0.1, 9);
});

test('two pinches never start scaling while an object is held, or with only one hand', () => {
  const holding = new DollhouseScaling();
  holding.update(hands(0.6), false);
  expect(holding.scaling).toBe(false);
  expect(holding.update(hands(0.06), false)).toEqual(LIFE_SIZE);
  const one = new DollhouseScaling();
  one.update([hands(0.6)[0]], true);
  expect(one.scaling).toBe(false);
});

test('the room shrinks no further than a fortieth and grows no further than life size', () => {
  const scaling = new DollhouseScaling();
  scaling.update(hands(0.8), true);
  expect(scaling.update(hands(0.001), true).scale).toBeCloseTo(1 / 40, 9);
  scaling.update([], true);
  // 1 cm to 2 m apart would grow a fortieth to five times life size.
  scaling.update(hands(0.01), true);
  expect(scaling.update(hands(2), true).scale).toBe(1);
  expect(scaling.update([], true)).toEqual(LIFE_SIZE);
});

test('let go near life size, the room snaps back to exactly where the alignment puts it', () => {
  const scaling = new DollhouseScaling();
  scaling.update(hands(0.6), true);
  scaling.update(hands(0.06, { x: 0.3, y: 1, z: -0.2 }), true);
  scaling.update([], true);
  scaling.update(hands(0.1, { x: 0.3, y: 1, z: -0.2 }), true);
  // While the hands still hold it, 95% stays around them, so jitter near the snap never flickers.
  const held = scaling.update(hands(0.95, { x: -0.4, y: 1.3, z: -0.6 }), true);
  expect(held.scale).toBeCloseTo(0.95, 9);
  close(toDollhouse(held, { x: 0, y: 1.2, z: -0.4 }), { x: -0.4, y: 1.3, z: -0.6 });
  // Let go there: life size, unmoved and unturned.
  expect(scaling.update([hands(0.95)[0]], true)).toEqual(LIFE_SIZE);
});

test('let go well below life size, the room keeps its size and place', () => {
  const scaling = new DollhouseScaling();
  scaling.update(hands(0.6), true);
  const held = scaling.update(hands(0.48), true);
  expect(held.scale).toBeCloseTo(0.8, 9);
  expect(scaling.update([], true)).toEqual(held);
});

test('hands starting almost together do not scale by a wild amount', () => {
  const scaling = new DollhouseScaling();
  scaling.update(hands(0.001), true);
  expect(scaling.update(hands(0.5), true)).toEqual(LIFE_SIZE);
});

test('a reset puts the room back to life size and ends any scaling', () => {
  const scaling = new DollhouseScaling();
  scaling.update(hands(0.6), true);
  scaling.update(hands(0.06), true);
  scaling.reset();
  expect(scaling.scaling).toBe(false);
  expect(scaling.view).toEqual(LIFE_SIZE);
});

test('the scale reads as one to how many times smaller the room is', () => {
  expect(scaleLabel(1)).toBe('1:1');
  expect(scaleLabel(0.05)).toBe('1:20');
  expect(scaleLabel(1 / 40)).toBe('1:40');
  expect(scaleLabel(0.3)).toBe('1:3');
});

test('a hand pinches at the point between its thumb tip and index tip', () => {
  const joints = { wrist: { x: 0, y: 1, z: 0 }, 'thumb-tip': { x: 0.1, y: 1.2, z: -0.3 }, 'index-finger-tip': { x: 0.11, y: 1.2, z: -0.31 } };
  const point = pinchPoint(joints)!;
  expect(point.x).toBeCloseTo(0.105, 9);
  expect(point.y).toBeCloseTo(1.2, 9);
  expect(point.z).toBeCloseTo(-0.305, 9);
  expect(pinchPoint({ wrist: { x: 0, y: 1, z: 0 }, 'thumb-tip': { x: 0, y: 1, z: 0 } })).toBeNull();
});
