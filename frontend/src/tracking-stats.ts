/**
 * How the phone's tracking behaved, for the diagnostic report, so device runs can be compared: the
 * mode and why it fell back, each tracking-status change and why, how long each opening of the room
 * view took to its first measured pose, and how often measured poses arrive. Times are milliseconds
 * since the room view first opened, on this device's clock.
 */
import type { EngineScale } from './engine-tracking';
import type { TrackingMode } from './movement-log';
import type { TrackingStatus } from './protocol';

/** Pose rates are averaged over this long, as the motion section's other rates are. */
const RATE_WINDOW_MS = 5000;
/** Status and mode changes kept; a run with more is losing tracking far too often anyway. */
const KEPT_CHANGES = 200;

/** The splat a room view draws: its file and how many splats it holds. */
export interface SplatDrawn {
  file: string;
  splats: number;
}

export interface StatusChange {
  at_ms: number;
  mode: TrackingMode;
  status: TrackingStatus;
  reason: string;
}

export interface ModeChange {
  at_ms: number;
  mode: TrackingMode;
  /** Why the phone counts steps instead of measuring, when it does. */
  fallback_reason: string | null;
}

export interface Opening {
  opened_at_ms: number;
  /** From opening to the first pose the engine measured; null until there is one. */
  first_tracked_pose_ms: number | null;
}

export class TrackingStats {
  private clockFrom: number | null = null;
  private open = false;
  private current: ModeChange | null = null;
  private trackingStatus: TrackingStatus | null = null;
  /** The engine's own last status and reason, given as the reason for its status changes. */
  private engineReason = '';
  private readonly modeChanges: ModeChange[] = [];
  private readonly statusChanges: StatusChange[] = [];
  private readonly openings: Opening[] = [];
  /** When recent measured poses arrived, within the rate window. */
  private readonly poses: number[] = [];
  /** How 8th Wall's distances were last corrected, or null before they were (#112). */
  private scaled: EngineScale | null = null;
  /** When recent frames were drawn, within the rate window. */
  private readonly frames: number[] = [];

  /** The room view opens and tracking starts: a new opening, timed to its own first pose. */
  opened(now = performance.now()): void {
    this.clockFrom ??= now;
    this.engineReason = '';
    if (this.open) return;
    this.open = true;
    this.openings.push({ opened_at_ms: this.time(now), first_tracked_pose_ms: null });
  }

  closed(now = performance.now()): void {
    if (!this.open) return;
    this.open = false;
    this.status('inactive', 'room view closed', now);
  }

  /** Which source tracks the phone, and why it is not the engine when it is not. */
  mode(mode: TrackingMode, fallbackReason: string | null, now = performance.now()): void {
    const reason = mode === 'steps' ? fallbackReason : null;
    if (this.current?.mode === mode && this.current.fallback_reason === reason) return;
    this.current = { at_ms: this.time(now), mode, fallback_reason: reason };
    this.keep(this.modeChanges, this.current);
  }

  /** The engine's own status and reason, such as `LIMITED EXCESSIVE_MOTION`. */
  engine(status: string, reason: string): void { this.engineReason = `${status} ${reason}`; }

  /** The reason for the engine's next status change, given before it happens, such as a pause. */
  nextReason(reason: string): void { this.engineReason = reason; }

  /** The engine starts again, so its earlier reasons no longer apply. */
  restarted(): void { this.engineReason = ''; }

  /**
   * Tracking is now `status`; without a reason, the engine's own is given. A change of status or
   * of reason is kept, so a pause while already lost is still recorded.
   */
  status(status: TrackingStatus, reason = this.engineReason || 'starting', now = performance.now()): void {
    if (!this.current) return;
    const last = this.statusChanges.at(-1);
    if (status === this.trackingStatus && reason === last?.reason) return;
    this.trackingStatus = status;
    this.keep(this.statusChanges, { at_ms: this.time(now), mode: this.current.mode, status, reason });
  }

  /** The engine measured a pose. */
  pose(now = performance.now()): void {
    const opening = this.openings.at(-1);
    if (opening && opening.first_tracked_pose_ms === null) {
      opening.first_tracked_pose_ms = this.time(now) - opening.opened_at_ms;
    }
    this.poses.push(now);
    while (this.poses.length && now - this.poses[0] > RATE_WINDOW_MS) this.poses.shift();
  }

  /** 8th Wall's scale was measured. */
  scale(scale: EngineScale): void { this.scaled = scale; }

  /** A frame was drawn. */
  frame(now = performance.now()): void {
    this.frames.push(now);
    while (this.frames.length && now - this.frames[0] > RATE_WINDOW_MS) this.frames.shift();
  }

  /** One line for the page's diagnostics. */
  summary(now = performance.now()): string {
    if (!this.current) return 'No tracking yet';
    const status = this.trackingStatus ?? 'starting';
    if (this.current.mode === 'steps') return ['Steps', this.current.fallback_reason, status].filter(Boolean).join(' · ');
    return `Measured · ${status} · ${this.rate(this.poses, now).toFixed(1)} poses/s · ${this.rate(this.frames, now).toFixed(0)} fps`;
  }

  /** `splat` is the file the room view draws and how many splats it holds. */
  report(splat: SplatDrawn | null = null, now = performance.now()): Record<string, unknown> {
    return {
      mode: this.current?.mode ?? null,
      fallback_reason: this.current?.fallback_reason ?? null,
      mode_changes: [...this.modeChanges],
      status_changes: [...this.statusChanges],
      openings: this.openings.map(opening => ({ ...opening })),
      first_tracked_pose_ms: this.openings.at(-1)?.first_tracked_pose_ms ?? null,
      pose_rate_hz: Number(this.rate(this.poses, now).toFixed(2)),
      frame_rate_hz: Number(this.rate(this.frames, now).toFixed(2)),
      scale: this.scaled,
      splat,
      time_note: 'Times are milliseconds since the room view first opened, on this device.',
    };
  }

  private time(now: number): number { return Math.round(now - (this.clockFrom ?? now)); }

  private rate(times: readonly number[], now: number): number {
    return times.filter(time => now - time <= RATE_WINDOW_MS).length / (RATE_WINDOW_MS / 1000);
  }

  private keep<T>(changes: T[], change: T): void {
    changes.push(change);
    if (changes.length > KEPT_CHANGES) changes.shift();
  }
}
