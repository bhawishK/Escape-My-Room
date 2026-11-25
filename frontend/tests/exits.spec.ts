import { expect, test } from '@playwright/test';
import type { RoomExit } from '../src/protocol';
import { EXIT_FLOOR_METRES, EXIT_MARGIN_METRES, exitAlongRay, exitName, guidingLine } from '../src/quest/exits';

// Pointing at an exit (#282): which door or window a ray is on, in room metres.

// Room 10's door, on its +x wall, and a window on its -x wall, as Python sends them (#280).
const DOOR: RoomExit = {
  id: 'door_0', kind: 'door', centre: [2.5575, 1.09, 0.3096], width: 1.64, height: 2.26,
  outward: [1, 0], anchor: [2.1575, 0.3096],
};
const WINDOW: RoomExit = {
  id: 'window_0', kind: 'window', centre: [-1.3925, 1.34, 0.2346], width: 2.72, height: 1.98,
  outward: [-1, 0], anchor: [-0.9925, 0.2346],
};
const EXITS = [DOOR, WINDOW];
const EYE = { x: 0, y: 1.6, z: 0.3 };

test('a ray through the door\'s opening is on the door, at the wall', () => {
  const hit = exitAlongRay(EXITS, EYE, { x: 1, y: -0.1, z: 0 }, 30);
  expect(hit?.id).toBe('door_0');
  expect(hit!.distance).toBeCloseTo(Math.hypot(2.5575, 0.25575), 3);
});

test('the other way, the same ray is on the window', () => {
  expect(exitAlongRay(EXITS, EYE, { x: -1, y: 0, z: 0 }, 30)?.id).toBe('window_0');
});

test('just past the opening\'s edge still counts, further does not', () => {
  // Aimed level at the wall, beside the door: its edge is 0.82 m from its middle.
  const at = (z: number) => exitAlongRay([DOOR], { x: 0, y: 1.09, z: 0.3096 }, { x: 2.5575, y: 0, z: z }, 30);
  expect(at(0.82 + EXIT_MARGIN_METRES - 0.05)?.id).toBe('door_0');
  expect(at(0.82 + EXIT_MARGIN_METRES + 0.05)).toBeNull();
});

test('a ray down onto the floor just inside the door is on it', () => {
  const near = exitAlongRay([DOOR], { x: 1, y: 1.5, z: 0.3 }, { x: 1.1, y: -1.5, z: 0 }, 30);
  expect(near?.id).toBe('door_0');
  const far = exitAlongRay([DOOR], { x: 1, y: 1.5, z: 0.3 }, { x: 1.1 - EXIT_FLOOR_METRES - 0.5, y: -1.5, z: 0 }, 30);
  expect(far).toBeNull();
});

test('a ray away from both, behind it, or beyond its reach is on no exit', () => {
  expect(exitAlongRay(EXITS, EYE, { x: 0, y: 0, z: 1 }, 30)).toBeNull();
  expect(exitAlongRay(EXITS, EYE, { x: 0, y: 1, z: 0 }, 30)).toBeNull();
  expect(exitAlongRay([DOOR], EYE, { x: 1, y: 0, z: 0 }, 2)).toBeNull();
  expect(exitAlongRay([], EYE, { x: 1, y: 0, z: 0 }, 30)).toBeNull();
  expect(exitAlongRay(EXITS, EYE, { x: 0, y: 0, z: 0 }, 30)).toBeNull();
});

test('the direction need not be a unit vector, as a ray through the dollhouse isn\'t', () => {
  expect(exitAlongRay(EXITS, EYE, { x: 40, y: -4, z: 0 }, 30)?.distance).toBeCloseTo(Math.hypot(2.5575, 0.25575), 3);
});

test('an exit is named by its kind, numbered when there are more than one', () => {
  expect(exitName(EXITS, 'door_0')).toBe('the door');
  expect(exitName([...EXITS, { ...WINDOW, id: 'window_1' }], 'window_1')).toBe('window 2');
  expect(exitName(EXITS, 'nowhere')).toBe('the exit');
});

test('while guiding, the headset says how far the phone user has to go, until they are out', () => {
  const routing = { exit: 'door_0', status: 'routing' as const, route: [[0, 0], [2, 0]] as [number, number][], length: 2.04 };
  expect(guidingLine(null, EXITS)).toBeNull();
  expect(guidingLine(routing, EXITS)).toBe('Guiding to the door · the phone user is 2.0 m away');
  expect(guidingLine({ ...routing, status: 'waiting', route: null, length: null }, EXITS)).toBe('Guiding to the door · waiting to see the phone user');
  expect(guidingLine({ ...routing, status: 'no_route', route: null, length: null }, EXITS)).toMatch(/^No clear way to the door/);
  expect(guidingLine({ ...routing, status: 'arrived', route: null, length: null }, EXITS)).toBe('The phone user is out, by the door');
});
