/**
 * Pointing at an exit (#275, #282): which of the room's doors and windows a ray is on, in the
 * dollhouse or at life size. The commander points at a door, "Exit · guide here" appears there,
 * and a pinch confirms it. All in room metres: the caller turns the ray into the room first.
 */
import type { Position, RoomExit, RoomGuidance } from '../protocol';

/** A ray this close to an opening's edges, in room metres, is still on it: doors are big targets. */
export const EXIT_MARGIN_METRES = 0.25;
/** A ray meeting the floor this close to an exit's anchor is on that exit too. */
export const EXIT_FLOOR_METRES = 0.6;
/** The offer stays this long after the ray leaves the exit, so the pinch that ends pointing confirms it. */
export const OFFER_GRACE_MS = 800;

export interface ExitHit {
  id: string;
  /** How far along the ray, in room metres. */
  distance: number;
}

/**
 * The exit the ray from `origin` along `direction` is on: through its opening (with a margin),
 * or on the floor at its anchor. The nearest along the ray, within `reach`; null if none.
 */
export function exitAlongRay(
  exits: readonly RoomExit[], origin: Position, direction: Position, reach: number,
): ExitHit | null {
  const size = Math.hypot(direction.x, direction.y, direction.z);
  if (size < 1e-9) return null;
  const d = { x: direction.x / size, y: direction.y / size, z: direction.z / size };
  let best: ExitHit | null = null;
  const consider = (id: string, distance: number) => {
    if (distance > 0 && distance <= reach && (!best || distance < best.distance)) best = { id, distance };
  };
  // Where the ray meets the floor, if it does.
  const toFloor = d.y < -1e-9 ? -origin.y / d.y : Infinity;
  for (const exit of exits) {
    const [cx, cy, cz] = exit.centre;
    const [nx, nz] = exit.outward;
    // Through the opening: the wall's plane, square to `outward`.
    const facing = d.x * nx + d.z * nz;
    if (Math.abs(facing) > 1e-9) {
      const t = ((cx - origin.x) * nx + (cz - origin.z) * nz) / facing;
      const x = origin.x + d.x * t;
      const y = origin.y + d.y * t;
      const z = origin.z + d.z * t;
      // Along the wall, and up it, from the opening's middle.
      const along = Math.abs((x - cx) * -nz + (z - cz) * nx);
      if (along <= exit.width / 2 + EXIT_MARGIN_METRES && Math.abs(y - cy) <= exit.height / 2 + EXIT_MARGIN_METRES) {
        consider(exit.id, t);
      }
    }
    // On the floor just inside it.
    if (Number.isFinite(toFloor)) {
      const x = origin.x + d.x * toFloor;
      const z = origin.z + d.z * toFloor;
      if (Math.hypot(x - exit.anchor[0], z - exit.anchor[1]) <= EXIT_FLOOR_METRES) consider(exit.id, toFloor);
    }
  }
  return best;
}

/** How the headset names an exit: "the door", or "door 2" when the room has more than one. */
export function exitName(exits: readonly RoomExit[], id: string): string {
  const exit = exits.find(candidate => candidate.id === id);
  if (!exit) return 'the exit';
  const same = exits.filter(candidate => candidate.kind === exit.kind);
  return same.length > 1 ? `${exit.kind} ${same.indexOf(exit) + 1}` : `the ${exit.kind}`;
}

/** What the headset says while guiding (#284): where the phone user is on their way out. */
export function guidingLine(guidance: RoomGuidance | null, exits: readonly RoomExit[]): string | null {
  if (!guidance) return null;
  const to = exitName(exits, guidance.exit);
  if (guidance.status === 'arrived') return `The phone user is out, by ${to}`;
  if (guidance.status === 'no_route') return `No clear way to ${to} · guide the phone user by voice`;
  if (guidance.status === 'waiting' || guidance.length === null) return `Guiding to ${to} · waiting to see the phone user`;
  return `Guiding to ${to} · the phone user is ${guidance.length.toFixed(1)} m away`;
}
