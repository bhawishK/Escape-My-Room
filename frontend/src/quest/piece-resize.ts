/**
 * Resizing a placed piece of furniture in the headset (#202). A quick pinch on a piece chooses it,
 * for Move and Resize on the wrist menu (#204); in resize mode, two pinched hands pulled apart grow the piece and
 * pulled together shrink it, as two hands scale the room. Positions are in the `local` space.
 */
import type { Position, RoomEntity } from '../protocol';

type EntitySize = RoomEntity['size'];

/** A tap: a pinch let go within this long, its hand moved no farther than this. */
export const TAP_MS = 350;
const TAP_METRES = 0.03;
/** A piece is resized to between these times its catalogue size, as Python keeps it. */
const SMALLEST = 0.25;
const LARGEST = 3;
/** Two hands closer than this don't start a resize: their distance would jump about. */
const MIN_APART_METRES = 0.05;

const distance = (a: Position, b: Position) => Math.hypot(a.x - b.x, a.y - b.y, a.z - b.z);

/** Whether a pinch from `since` at `from`, let go `now` at `here`, was a tap. */
export function isTap(since: number, from: Position, now: number, here: Position): boolean {
  return now - since < TAP_MS && distance(from, here) <= TAP_METRES;
}

/** This frame of a resize: waiting for two hands, resizing, or done with its last scale. */
export interface ResizeStep {
  phase: 'waiting' | 'resizing' | 'done';
  scale: number;
}

/**
 * One piece in resize mode: two pinches scale it by how far apart they are now against when
 * they started, from the piece's scale then. Letting go of either hand ends the resize and the
 * mode with it.
 */
export class PieceResize {
  /** The piece in resize mode, or null. */
  piece: string | null = null;
  private scale = 1;
  private start: { apart: number; scale: number } | null = null;

  /** Puts `piece`, now at `scale` times its catalogue size, in resize mode. */
  begin(piece: string, scale: number): void {
    this.piece = piece;
    this.scale = scale;
    this.start = null;
  }

  /** Leaves resize mode without a resize. */
  cancel(): void {
    this.piece = null;
    this.start = null;
  }

  /** This frame's pinches, in the `local` space. */
  update(pinches: readonly Position[]): ResizeStep {
    if (pinches.length < 2) {
      if (!this.start) return { phase: 'waiting', scale: this.scale };
      this.cancel();
      return { phase: 'done', scale: this.scale };
    }
    const apart = distance(pinches[0], pinches[1]);
    if (!this.start) {
      if (apart < MIN_APART_METRES) return { phase: 'waiting', scale: this.scale };
      this.start = { apart, scale: this.scale };
    }
    this.scale = Math.min(LARGEST, Math.max(SMALLEST, this.start.scale * apart / this.start.apart));
    return { phase: 'resizing', scale: this.scale };
  }
}

/** A piece's true size at `scale` times its catalogue `size`: width × depth × height. */
export function sizeLabel(size: EntitySize, scale: number): string {
  const metres = (value: number) => (value * scale).toFixed(2);
  return `${metres(size.width)} × ${metres(size.depth)} × ${metres(size.height)} m`;
}
