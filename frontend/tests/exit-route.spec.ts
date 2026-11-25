import { expect, test } from '@playwright/test';
import {
  CHEVRON_SPACING_METRES, CHEVRON_START_METRES, chevronsAlong, edgeArrow, guidanceLine, pointAlong, routeFrom, routeLength,
  type Point,
} from '../src/exit-route';

// The phone's way out (#283): chevrons along the route, the edge arrow, and what it says.

// Two legs: 2 m along +x, then 1 m along -z.
const ROUTE: Point[] = [[0, 0], [2, 0], [2, -1]];

test('the route starts from where the phone user stands now', () => {
  expect(routeFrom(ROUTE, [0.1, 0.05])).toEqual([[0.1, 0.05], [2, 0], [2, -1]]);
  expect(routeFrom(ROUTE, null)).toEqual(ROUTE);
  expect(routeFrom([[2, -1]], [0, 0])).toEqual([[0, 0], [2, -1]]);
  expect(routeFrom([], [0, 0])).toEqual([]);
});

test('its length and a point along it', () => {
  expect(routeLength(ROUTE)).toBeCloseTo(3, 9);
  expect(pointAlong(ROUTE, 0.5)).toEqual([0.5, 0]);
  expect(pointAlong(ROUTE, 2.5)).toEqual([2, -0.5]);
  expect(pointAlong(ROUTE, 10)).toEqual([2, -1]);
  expect(pointAlong([], 1)).toBeNull();
});

test('chevrons are spaced along the route, each pointing along its leg', () => {
  const chevrons = chevronsAlong(ROUTE);
  expect(chevrons.length).toBe(Math.floor((3 - CHEVRON_START_METRES) / CHEVRON_SPACING_METRES) + 1);
  expect(chevrons[0].x).toBeCloseTo(CHEVRON_START_METRES, 9);
  // Along +x: turned a quarter clockwise from -z; along -z: not turned.
  expect(chevrons[0].yaw).toBeCloseTo(-Math.PI / 2, 9);
  expect(chevrons[chevrons.length - 1].yaw).toBeCloseTo(0, 9);
  expect(chevronsAlong([[0, 0]])).toEqual([]);
});

test('no edge arrow while the way on is on screen; one at the edge it is beyond when not', () => {
  expect(edgeArrow({ x: 0.2, y: -0.3 }, false)).toBeNull();
  const right = edgeArrow({ x: 3, y: 0 }, false)!;
  expect(right.left).toBeCloseTo(0.95, 9);
  expect(right.top).toBeCloseTo(0.5, 9);
  expect(right.angle).toBeCloseTo(Math.PI / 2, 9);
  const above = edgeArrow({ x: 0, y: 2 }, false)!;
  expect(above.top).toBeCloseTo(0.05, 9);
  expect(above.angle).toBeCloseTo(0, 9);
});

test('a point behind the phone sends the arrow to the bottom, on the side it is on', () => {
  // Behind and to the left: projected mirrored, to the right.
  const arrow = edgeArrow({ x: 0.5, y: 0.2 }, true)!;
  expect(arrow.top).toBeCloseTo(0.95, 9);
  expect(arrow.left).toBeLessThan(0.5);
  expect(Math.abs(arrow.angle)).toBeGreaterThan(Math.PI / 2);
});

test('what the phone says, from before the confirm to out', () => {
  const guidance = { exit: 'door_0', status: 'routing' as const, route: ROUTE, length: 3 };
  expect(guidanceLine(null, null)).toBeNull();
  expect(guidanceLine({ ...guidance, status: 'waiting', route: null }, null)).toBe('Finding your way out…');
  expect(guidanceLine(guidance, 3.04)).toBe('Exit 3.0 m · follow the arrows');
  expect(guidanceLine(guidance, 12.6)).toBe('Exit 13 m · follow the arrows');
  expect(guidanceLine({ ...guidance, status: 'no_route', route: null }, null)).toMatch(/^No clear way/);
  expect(guidanceLine({ ...guidance, status: 'arrived', route: null }, null)).toBe("You're out");
});
