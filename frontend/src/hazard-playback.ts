/**
 * Playing a hazard's 4D frames (#230, #231; part of #221), the same on the headset and the phone.
 *
 * A hazard in the session (#229) has its frames, where they go in the room, the room object they
 * hide, and, once started, a start time on the server's clock. Each device sets its own clock
 * against the server's from the `server_time_ms` every state carries, so both show the same frame
 * at the same moment.
 */
import type { Position, RoomEntity } from './protocol';

export interface HazardPlacement {
  /** Where the frames' origin goes, in room metres, after scaling and turning. */
  position: [number, number, number];
  /** Radians about the vertical, as three.js turns rotation.y. */
  turn: number;
  scale: number;
  hide: string | null;
}

export interface SessionHazard {
  id: string;
  asset: string;
  hazard: string;
  frames: number;
  frames_per_second: number;
  /** A frame's address with `{n}` for its number. */
  frame_url: string;
  seconds: number;
  loops: boolean;
  placement: HazardPlacement | null;
  hide: string | null;
  playing: boolean;
  /** Milliseconds on the server's clock; null when stopped. */
  started_at: number | null;
}

/** A frame's address. */
export const frameUrl = (hazard: SessionHazard, n: number): string => hazard.frame_url.replace('{n}', String(n));

/** How many samples the clock keeps; a state is sent several times a second while things move. */
const CLOCK_SAMPLES = 30;

/**
 * The server's clock, as seen from here. Each state says the server's time when it was made, and
 * arrives some time later, so `server - local` is the clocks' difference less that delay. The
 * largest of the recent samples had the least delay, so it is the best estimate.
 */
export class ServerClock {
  private samples: number[] = [];

  /** A state made at `serverMs` on the server's clock arrived at `localMs` on this one. */
  sample(serverMs: number, localMs: number): void {
    this.samples.push(serverMs - localMs);
    if (this.samples.length > CLOCK_SAMPLES) this.samples.shift();
  }

  get known(): boolean {
    return this.samples.length > 0;
  }

  /** The server's time at `localMs` on this clock. */
  now(localMs: number): number {
    return localMs + (this.samples.length ? Math.max(...this.samples) : 0);
  }
}

/**
 * The frame to show at `serverMs`. Stopped, or before its start, it shows its first frame, the
 * object not yet burning. Started, it plays once at its frame rate; then it starts again if it
 * loops, else it keeps burning by playing its last second over and over.
 */
export function frameAt(hazard: SessionHazard, serverMs: number): number {
  const { frames, frames_per_second: rate, started_at: start } = hazard;
  if (!hazard.playing || start === null || serverMs < start || frames < 1) return 0;
  const n = Math.floor(((serverMs - start) / 1000) * rate);
  if (n < frames) return n;
  if (hazard.loops) return n % frames;
  const tail = Math.max(1, Math.min(frames, Math.round(rate)));
  return frames - tail + ((n - frames) % tail);
}

/** A box in room metres: its centre, its turn about the vertical, and half its size on each side. */
export interface HideBox {
  centre: Position;
  yaw: number;
  half: Position;
}

/** How much bigger than the object the hidden box is, so its edges don't show around the frames. */
export const HIDE_MARGIN = 1.1;

/** The box of a room object to hide while its hazard is in the room; null if there's no such object. */
export function hideBox(entities: readonly RoomEntity[], id: string | null): HideBox | null {
  const entity = id ? entities.find(candidate => candidate.id === id) : undefined;
  if (!entity) return null;
  const { position, rotation, size } = entity;
  return {
    centre: { x: position.x, y: position.y + size.height / 2, z: position.z },
    yaw: 2 * Math.atan2(rotation.y, rotation.w),
    half: {
      x: (size.width / 2) * HIDE_MARGIN,
      y: (size.height / 2) * HIDE_MARGIN,
      z: (size.depth / 2) * HIDE_MARGIN,
    },
  };
}

/**
 * Whether this is a low-end device, which loads every other hazard frame (#231): 4 GB of memory
 * or less, as Chrome on Android reports it (Safari doesn't say), or `?low-end` in the address.
 */
export function lowEndDevice(): boolean {
  if (new URLSearchParams(window.location.search).has('low-end')) return true;
  const memory = (navigator as Navigator & { deviceMemory?: number }).deviceMemory;
  return memory !== undefined && memory <= 4;
}

/** What a page shows of its hazards for tests and diagnostics: `id:loading|ready:frame`, comma-separated. */
export function hazardsLabel(entries: readonly { id: string; ready: boolean; frame: number }[]): string {
  return entries.map(entry => `${entry.id}:${entry.ready ? 'ready' : 'loading'}:${entry.frame}`).join(',');
}
