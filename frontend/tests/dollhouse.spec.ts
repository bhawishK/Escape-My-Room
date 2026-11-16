import { expect, test } from '@playwright/test';
import { pinchPoint } from '../src/quest/gestures';
import {
  DollhouseCarry, DollhouseScaling, LIFE_SIZE, fromDollhouse, residentFigure, scaleLabel, orientationFromDollhouse, orientationToDollhouse, toDollhouse,
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

/** A hand's grip turned `yaw` radians to the left about the vertical, at `position`. */
const grip = (position: { x: number; y: number; z: number }, yaw = 0) => ({
  position, orientation: { x: 0, y: Math.sin(yaw / 2), z: 0, w: Math.cos(yaw / 2) },
});

test('a hand carrying the dollhouse moves it with the hand, keeping its size and turn', () => {
  const carry = new DollhouseCarry();
  expect(carry.begin(grip({ x: 0.1, y: 1, z: -0.5 }), TABLE)).toBe(true);
  const view = carry.update(grip({ x: 0.4, y: 1.1, z: -0.5 }));

  expect(view.scale).toBe(TABLE.scale);
  expect(view.yaw).toBeCloseTo(TABLE.yaw, 9);
  close(view.offset, { x: 0.3, y: 0.9, z: -1 });
});

test('turning the carrying hand a quarter left turns the dollhouse a quarter left about the hand', () => {
  const carry = new DollhouseCarry();
  const hand = { x: 0.1, y: 1, z: -0.5 };
  // The room point in the hand: TABLE's quarter turn takes room -z to the left, 20 times smaller.
  const held = fromDollhouse(TABLE, hand);
  carry.begin(grip(hand), TABLE);
  const view = carry.update(grip(hand, Math.PI / 2));

  expect(view.yaw).toBeCloseTo(Math.PI, 9);
  close(toDollhouse(view, held), hand);
  // A point 2 m further along room -z than the held one now lies 10 cm toward +z of the hand.
  close(toDollhouse(view, { ...held, z: held.z - 2 }), { x: 0.1, y: 1, z: -0.4 });
});

test('the real room at life size cannot be carried', () => {
  const carry = new DollhouseCarry();
  expect(carry.begin(grip({ x: 0, y: 1, z: -0.5 }), LIFE_SIZE)).toBe(false);
  expect(carry.carrying).toBe(false);
});

test('carried and turned anywhere, grown back near life size it lines up with the real room again', () => {
  const carry = new DollhouseCarry();
  carry.begin(grip({ x: 0, y: 1, z: -0.5 }), TABLE);
  const moved = carry.update(grip({ x: 0.7, y: 0.6, z: -0.2 }, 1.2));
  carry.end();

  const scaling = new DollhouseScaling();
  scaling.view = moved;
  scaling.update(hands(0.05), true);
  expect(scaling.update(hands(0.95), true).scale).toBeCloseTo(0.95, 9);
  expect(scaling.update([], true)).toEqual(LIFE_SIZE);
});

/** The room's anchor in the `local` space before alignment: the floor 1.6 m below the eyes. */
const ANCHOR = { yaw: 0, offset: { x: 0, y: -1.6, z: 0 } };

test('the resident stands in the dollhouse where they stand in the room, facing the same way', () => {
  const figure = residentFigure(
    { tracking_status: 'tracked', position: { x: 2, y: 0, z: -1 }, heading: 0.3 }, TABLE, ANCHOR)!;

  // Their feet at (2, -1.6, -1) in the `local` space; the quarter turn takes room +x to -z and
  // room -z to -x, a twentieth of the size, around the table point (0, 0.8, -1).
  close(figure.position, { x: -0.05, y: 0.72, z: -1.1 });
  expect(figure.heading).toBeCloseTo(0.3 + Math.PI / 2, 9);
  expect(figure.opacity).toBe(1);
});

test('the resident is drawn at least 8 cm tall in a small dollhouse, and to scale in a large one', () => {
  const presence = { tracking_status: 'tracked' as const, position: { x: 0, y: 0, z: 0 }, heading: 0 };
  expect(residentFigure(presence, { ...TABLE, scale: 1 / 40 }, ANCHOR)!.height).toBeCloseTo(0.08, 9);
  // Life size, a figure is as tall as a standing person.
  expect(residentFigure(presence, LIFE_SIZE, ANCHOR)!.height).toBeCloseTo(1.55, 9);
});

test('a stale resident is faint, and one inactive, lost or without a place is not drawn', () => {
  const at = { position: { x: 0, y: 0, z: 0 }, heading: 0 };
  expect(residentFigure({ tracking_status: 'stale', ...at }, TABLE, ANCHOR)!.opacity).toBe(0.35);
  expect(residentFigure({ tracking_status: 'inactive', ...at }, TABLE, ANCHOR)).toBeNull();
  expect(residentFigure({ tracking_status: 'lost', ...at }, TABLE, ANCHOR)).toBeNull();
  expect(residentFigure({ tracking_status: 'tracked', position: null, heading: null }, TABLE, ANCHOR)).toBeNull();
  expect(residentFigure(undefined, TABLE, ANCHOR)).toBeNull();
});

test('a hand pointing straight up still turns the dollhouse only by its turn about the vertical', () => {
  // A quarter turn about x (the hand pointing up), then `yaw` about the vertical.
  const pitched = (yaw: number) => {
    const b = Math.PI / 4;
    const a = yaw / 2;
    return {
      position: { x: 0.1, y: 1, z: -0.5 },
      orientation: { x: Math.cos(a) * Math.sin(b), y: Math.sin(a) * Math.cos(b), z: -Math.sin(a) * Math.sin(b), w: Math.cos(a) * Math.cos(b) },
    };
  };
  const carry = new DollhouseCarry();
  carry.begin(pitched(0), TABLE);
  expect(carry.update(pitched(0.01)).yaw).toBeCloseTo(TABLE.yaw + 0.01, 6);
  expect(carry.update(pitched(0.5)).yaw).toBeCloseTo(TABLE.yaw + 0.5, 6);
});
