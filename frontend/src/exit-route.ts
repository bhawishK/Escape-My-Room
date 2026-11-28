/**
 * The phone's way out (#275, #283): chevrons on the floor along the route Python works out to the
 * exit the commander chose, an arrow at the screen's edge when the way on is out of sight, the
 * distance left, and "You're out" on arrival. Nothing shows before the commander confirms an exit.
 */
import type { RoomGuidance } from './protocol';

export type Point = [number, number];

/** Chevrons are this far apart along the route, starting this far ahead of the phone user's feet. */
export const CHEVRON_SPACING_METRES = 0.5;
export const CHEVRON_START_METRES = 0.4;
/** The edge arrow points at the route this far ahead of the phone user, or at the exit if nearer. */
export const LOOK_AHEAD_METRES = 1.5;
/** A point this near the screen's edge counts as off it: the arrow shows before it is gone. */
export const EDGE_MARGIN = 0.1;

/** The route from where the phone user stands now: Python's first point is up to half a second old. */
export function routeFrom(route: readonly Point[], at: Point | null): Point[] {
  if (route.length === 0) return [];
  if (!at) return [...route];
  return route.length === 1 ? [at, route[0]] : [at, ...route.slice(1)];
}

export function routeLength(route: readonly Point[]): number {
  let total = 0;
  for (let i = 1; i < route.length; i++) total += Math.hypot(route[i][0] - route[i - 1][0], route[i][1] - route[i - 1][1]);
  return total;
}

/** The point `distance` metres along the route, or its end if it is shorter. */
export function pointAlong(route: readonly Point[], distance: number): Point | null {
  if (route.length === 0) return null;
  let left = distance;
  for (let i = 1; i < route.length; i++) {
    const [ax, az] = route[i - 1];
    const [bx, bz] = route[i];
    const leg = Math.hypot(bx - ax, bz - az);
    if (leg > 0 && left <= leg) return [ax + (bx - ax) * left / leg, az + (bz - az) * left / leg];
    left -= leg;
  }
  return route[route.length - 1];
}

export interface Chevron {
  x: number;
  z: number;
  /** Radians about the vertical, as three.js turns rotation.y: 0 points along -z. */
  yaw: number;
}

/** Chevrons along the route, each pointing the way along its leg. */
export function chevronsAlong(
  route: readonly Point[], spacing = CHEVRON_SPACING_METRES, start = CHEVRON_START_METRES,
): Chevron[] {
  const chevrons: Chevron[] = [];
  let next = start;
  let walked = 0;
  for (let i = 1; i < route.length; i++) {
    const [ax, az] = route[i - 1];
    const [bx, bz] = route[i];
    const leg = Math.hypot(bx - ax, bz - az);
    if (leg === 0) continue;
    const yaw = Math.atan2(-(bx - ax), -(bz - az));
    while (next <= walked + leg) {
      const share = (next - walked) / leg;
      chevrons.push({ x: ax + (bx - ax) * share, z: az + (bz - az) * share, yaw });
      next += spacing;
    }
    walked += leg;
  }
  return chevrons;
}

/**
 * Where on the screen's edge the arrow goes, for a point at `ndc` (normalised device coordinates,
 * from the camera; `behind` when it is behind the camera): its place as fractions of the screen
 * from the top left, and its turn in radians clockwise from pointing up. Null when the point is on
 * screen, so no arrow is needed.
 */
export function edgeArrow(ndc: { x: number; y: number }, behind: boolean): { left: number; top: number; angle: number } | null {
  let { x, y } = ndc;
  const limit = 1 - EDGE_MARGIN;
  if (!behind && Math.abs(x) <= limit && Math.abs(y) <= limit) return null;
  // Behind the camera the projection is mirrored: turn it back, and send it to the bottom.
  if (behind) {
    x = -x;
    y = -Math.abs(y) - 1;
  }
  const scale = limit / Math.max(Math.abs(x), Math.abs(y), 1e-9);
  const ex = x * scale;
  const ey = y * scale;
  return { left: (ex + 1) / 2, top: (1 - ey) / 2, angle: Math.atan2(x, y) };
}

/** What the phone says about the way out; null before the commander has chosen an exit. */
export function guidanceLine(guidance: RoomGuidance | null | undefined, metresLeft: number | null): string | null {
  if (!guidance) return null;
  if (guidance.status === 'arrived') return "You're out";
  if (guidance.status === 'no_route') return 'No clear way to the exit · listen to the commander';
  if (guidance.status === 'waiting' || metresLeft === null) return 'Finding your way out…';
  return `Exit ${metresLeft < 10 ? metresLeft.toFixed(1) : Math.round(metresLeft)} m · follow the arrows`;
}
