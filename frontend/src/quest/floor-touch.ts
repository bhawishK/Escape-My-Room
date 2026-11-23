/**
 * Touch the floor (#218): the room's floor is set where a palm rests on the real floor.
 *
 * The Quest puts the room's floor at its `local-floor` origin (#207), which is the headset's own
 * idea of the floor; when that is off, the room's floor floats above the real one or sinks below
 * it. A hand lying flat on the real floor says where it really is: its joints all at about one
 * height, still for a second, and low. The floor is then that height less a joint's height above
 * the skin it rests on.
 */

import type { CalibrationInput } from '../alignment';
import type { Position } from '../protocol';

/** How long the hand must rest. */
export const FLOOR_TOUCH_MS = 1000;
/** A hand's joint centres sit about this far above the surface the hand rests on. */
export const JOINT_ABOVE_FLOOR = 0.012;
/** Flat: the joints' heights within this of each other. */
const FLAT_M = 0.04;
/** Low: under this above the headset's floor (it may be wrong by this much, upward). */
const NEAR_FLOOR_M = 0.45;
/** Still: the hand moves less than this across, and its height less than this, while resting. */
const STILL_ACROSS_M = 0.03;
const STILL_HEIGHT_M = 0.015;
/** At least this many of the hand's joints seen. */
const JOINTS_SEEN = 6;

interface Resting {
  at: number;
  x: number;
  z: number;
  low: number;
}

/** Watches a hand for resting flat on the floor; says the floor's height once it has. */
export class FloorTouch {
  private samples: Resting[] = [];

  /** The hand's joints at `at` ms; the floor's height when it has rested long enough, else null. */
  add(joints: readonly Position[], at: number): number | null {
    if (joints.length < JOINTS_SEEN) {
      this.samples = [];
      return null;
    }
    const heights = joints.map(joint => joint.y);
    const low = Math.min(...heights);
    if (Math.max(...heights) - low > FLAT_M || low > NEAR_FLOOR_M) {
      this.samples = [];
      return null;
    }
    const x = joints.reduce((sum, joint) => sum + joint.x, 0) / joints.length;
    const z = joints.reduce((sum, joint) => sum + joint.z, 0) / joints.length;
    const first = this.samples[0];
    if (first && (Math.hypot(x - first.x, z - first.z) > STILL_ACROSS_M || Math.abs(low - first.low) > STILL_HEIGHT_M)) {
      // Moved: rest starts again from here.
      this.samples = [];
    }
    this.samples.push({ at, x, z, low });
    if (at - this.samples[0].at < FLOOR_TOUCH_MS) return null;
    const lows = this.samples.map(sample => sample.low).sort((a, b) => a - b);
    this.samples = [];
    return lows[Math.floor(lows.length / 2)] - JOINT_ABOVE_FLOOR;
  }

  reset(): void {
    this.samples = [];
  }
}

/**
 * The alignment with the room's floor at `floor`, the real floor's height in the headset's space;
 * null keeps it. Room = space + origin, so the room's y = 0 lands at `floor`.
 */
export function withFloor(alignment: CalibrationInput, floor: number | null): CalibrationInput {
  if (floor === null) return alignment;
  return { ...alignment, origin: { ...alignment.origin, y: alignment.origin.y - floor } };
}

/**
 * An alignment made with the floor at `from` (null: none measured), moved to the floor at `to`:
 * re-measuring the floor after lining the room up moves the room up or down, and nothing else.
 */
export function refloored(alignment: CalibrationInput, from: number | null, to: number | null): CalibrationInput {
  const change = (to ?? 0) - (from ?? 0);
  return { ...alignment, origin: { ...alignment.origin, y: alignment.origin.y - change } };
}

/** Where the measured floor is kept on the headset, so it is done once, not every session. */
const FLOOR_KEY = 'escape-room:floor-height';

/** The floor height measured before, if any. Storage can be missing or refused: then none. */
export function savedFloor(): number | null {
  try {
    const kept = window.localStorage.getItem(FLOOR_KEY);
    const value = kept === null ? NaN : Number(kept);
    return Number.isFinite(value) ? value : null;
  } catch {
    return null;
  }
}

export function saveFloor(height: number): void {
  try {
    window.localStorage.setItem(FLOOR_KEY, String(height));
  } catch {
    // Not kept: it holds for this session only.
  }
}
