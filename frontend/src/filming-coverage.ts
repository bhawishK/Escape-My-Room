/**
 * Which ways the camera has filmed (#100), from the phone's orientation sensor: twelve headings at
 * three heights (floor, eye level, ceiling), each counted once the camera has spent a second on it.
 *
 * Headings run clockwise from wherever the sensor's alpha is 0, so no compass is needed: only how
 * far round the room the camera has turned matters. The prompts are about the walk round the room
 * the room video needs: every side at eye level, and the floor.
 */

import type { Prompt } from './filming-coach';

export interface Direction {
  /** Degrees clockwise, 0 to 360. */
  heading: number;
  /** Degrees up from level, -90 to 90. */
  pitch: number;
}

export type Band = 'floor' | 'eye' | 'ceiling';

export interface Cell {
  heading: number;
  band: Band;
  filmed: boolean;
}

const SECTORS = 12;
const SECTOR_DEGREES = 360 / SECTORS;
/** Looking more than this far down is filming the floor; this far up, the ceiling. */
const FLOOR_PITCH = -25;
const CEILING_PITCH = 25;
/** A cell counts as filmed once the camera has spent this long on it. */
const FILMED_MS = 1000;
/** Coverage prompts wait until filming has gone on this long. */
const SETTLE_MS = 15_000;
/** The floor is asked for when it has been filmed at under this share of the eye-level headings. */
const FLOOR_SHARE = 1 / 3;
/** An unfilmed side is named once it spans this many sectors (90 degrees). */
const GAP_SECTORS = 3;

/**
 * Where the back camera points for the sensor's alpha, beta and gamma (degrees, W3C order
 * Z-X'-Y''): its heading clockwise from alpha 0 and its pitch up from level.
 */
export function cameraDirection(alpha: number, beta: number, gamma: number): Direction {
  const radians = Math.PI / 180;
  const [a, b, g] = [alpha * radians, beta * radians, gamma * radians];
  // The device's -z axis (out of the back camera), turned by Rz(alpha) Rx(beta) Ry(gamma), in
  // the sensor's world: x east, y north, z up.
  const x = -(Math.cos(a) * Math.sin(g) + Math.sin(a) * Math.sin(b) * Math.cos(g));
  const y = -(Math.sin(a) * Math.sin(g) - Math.cos(a) * Math.sin(b) * Math.cos(g));
  const z = -(Math.cos(b) * Math.cos(g));
  const heading = (Math.atan2(x, y) / radians + 360) % 360;
  return { heading, pitch: Math.asin(Math.max(-1, Math.min(1, z))) / radians };
}

function band(pitch: number): Band {
  return pitch < FLOOR_PITCH ? 'floor' : pitch > CEILING_PITCH ? 'ceiling' : 'eye';
}

function sector(heading: number): number {
  return Math.floor((((heading % 360) + 360) % 360) / SECTOR_DEGREES) % SECTORS;
}

export class FilmingCoverage {
  private readonly time = new Map<string, number>();
  private last: { at: number; key: string } | null = null;
  private started: number | null = null;

  /** Where the camera points at `at` ms; time is counted for the cell it pointed at before. */
  add(direction: Direction, at: number): void {
    this.started ??= at;
    if (this.last && at > this.last.at) {
      const spent = Math.min(at - this.last.at, 500);
      this.time.set(this.last.key, (this.time.get(this.last.key) ?? 0) + spent);
    }
    this.last = { at, key: `${band(direction.pitch)}:${sector(direction.heading)}` };
  }

  private filmed(cellBand: Band, index: number): boolean {
    return (this.time.get(`${cellBand}:${index}`) ?? 0) >= FILMED_MS;
  }

  /** Every cell, for drawing the ring. */
  cells(): Cell[] {
    const bands: Band[] = ['floor', 'eye', 'ceiling'];
    return bands.flatMap(cellBand => Array.from({ length: SECTORS }, (_, index) => ({
      heading: (index + 0.5) * SECTOR_DEGREES,
      band: cellBand,
      filmed: this.filmed(cellBand, index),
    })));
  }

  /** What to film next, said from `facing` (the camera's heading now), or null. */
  prompt(facing: number, at: number): Prompt | null {
    if (this.started === null || at - this.started < SETTLE_MS) return null;
    const eye = Array.from({ length: SECTORS }, (_, index) => this.filmed('eye', index));
    // The longest run of unfilmed eye-level sectors, going round.
    let best = { length: 0, start: 0 };
    for (let start = 0; start < SECTORS; start += 1) {
      if (eye[start]) continue;
      let length = 0;
      while (length < SECTORS && !eye[(start + length) % SECTORS]) length += 1;
      if (length > best.length) best = { length, start };
    }
    if (best.length >= GAP_SECTORS && best.length < SECTORS) {
      const centre = (best.start + best.length / 2) * SECTOR_DEGREES;
      const turn = ((centre - facing + 540) % 360) - 180;
      if (Math.abs(turn) >= 135) return { id: 'behind', text: 'Turn round: behind you is not filmed yet' };
      if (turn >= 45) return { id: 'right', text: 'Right side not filmed yet' };
      if (turn <= -45) return { id: 'left', text: 'Left side not filmed yet' };
    }
    const floor = Array.from({ length: SECTORS }, (_, index) => this.filmed('floor', index)).filter(Boolean).length;
    const level = eye.filter(Boolean).length;
    if (level > 0 && floor < FLOOR_SHARE * level) {
      return { id: 'floor', text: 'Show the floor: tilt the phone down as you go' };
    }
    return null;
  }
}
