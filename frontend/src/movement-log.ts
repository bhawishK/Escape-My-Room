/**
 * What the phone's tracking did, for device checks: its pose about ten times a second and each
 * tracking event, kept for the last five minutes and sent to Python to be read afterwards.
 */
import { headingOf, pitchOf, type RoomPose } from './phone-view';
import type { TrackingStatus } from './protocol';

export type TrackingMode = 'measured' | 'steps';

type Entry =
  | { t: number; kind: 'event'; name: string; detail: string }
  | {
    t: number; kind: 'pose'; mode: TrackingMode; status: TrackingStatus;
    x: number; y: number; z: number; heading: number; pitch: number;
  };

const POSE_INTERVAL_MS = 100;
// Five minutes of poses ten times a second, with room for events.
const MAX_ENTRIES = 3500;

/** Millimetres and milliradians are plenty; `+ 0` turns -0 into 0. */
const round = (value: number) => Math.round(value * 1000) / 1000 + 0;

export class MovementLog {
  private readonly entries: Entry[] = [];
  private startedAt: number | null = null;
  private startedIso = '';
  private lastPoseAt = -Infinity;

  /** Starts counting time from now, the first time the room view opens. */
  begin(now = performance.now()): void {
    if (this.startedAt !== null) return;
    this.startedAt = now;
    this.startedIso = new Date().toISOString();
  }

  event(name: string, detail: string, now = performance.now()): void {
    this.add({ t: this.time(now), kind: 'event', name, detail });
  }

  /** Records where tracking says the phone is, at most ten times a second. */
  pose(mode: TrackingMode, status: TrackingStatus, pose: RoomPose, now = performance.now()): void {
    if (now - this.lastPoseAt < POSE_INTERVAL_MS) return;
    this.lastPoseAt = now;
    const { position: p, orientation } = pose;
    this.add({
      t: this.time(now), kind: 'pose', mode, status, x: round(p.x), y: round(p.y), z: round(p.z),
      heading: round(headingOf(orientation)), pitch: round(pitchOf(orientation)),
    });
  }

  report(): Record<string, unknown> {
    return {
      user_agent: navigator.userAgent, page: location.href, started_at: this.startedIso,
      sent_at: new Date().toISOString(), entries: this.entries,
    };
  }

  private time(now: number): number { return Math.round(now - (this.startedAt ?? now)); }

  private add(entry: Entry): void {
    this.entries.push(entry);
    if (this.entries.length > MAX_ENTRIES) this.entries.shift();
  }
}
