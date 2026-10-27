/**
 * How the phone's tracking behaved, for the diagnostic report, so device runs can be compared: the
 * mode and why it fell back, each tracking-status change and why, how long the first measured pose
 * took, and how often measured poses arrive. Times count from when the room view first opened.
 */
import type { TrackingMode } from './movement-log';
import type { TrackingStatus } from './protocol';

/** Pose rates are averaged over this long, as the motion section's other rates are. */
const RATE_WINDOW_MS = 5000;
const KEPT_CHANGES = 200;
const KEPT_POSES = 400;

export interface StatusChange {
  /** Milliseconds since the room view first opened. */
  at_ms: number;
  status: TrackingStatus;
  reason: string;
}

export class TrackingStats {
  private openedAt: number | null = null;
  private trackingMode: TrackingMode = 'steps';
  private fallbackReason: string | null = null;
  private current: TrackingStatus | null = null;
  private readonly changes: StatusChange[] = [];
  private firstPose: number | null = null;
  private readonly poses: number[] = [];

  /** Starts counting time from now, the first time the room view opens. */
  opened(now = performance.now()): void { this.openedAt ??= now; }

  /** Which source tracks the phone, and why it is not the engine when it is not. */
  mode(mode: TrackingMode, fallbackReason: string | null): void {
    this.trackingMode = mode;
    this.fallbackReason = mode === 'steps' ? fallbackReason : null;
  }

  /** Tracking is now `status`, for `reason`; only changes are kept. */
  status(status: TrackingStatus, reason: string, now = performance.now()): void {
    if (status === this.current) return;
    this.current = status;
    this.changes.push({ at_ms: this.time(now), status, reason });
    if (this.changes.length > KEPT_CHANGES) this.changes.shift();
  }

  /** The engine measured a pose. */
  pose(now = performance.now()): void {
    this.firstPose ??= this.time(now);
    this.poses.push(now);
    if (this.poses.length > KEPT_POSES) this.poses.shift();
  }

  /** One line for the page's diagnostics. */
  summary(now = performance.now()): string {
    const status = this.current ?? 'not started';
    if (this.trackingMode === 'steps') return ['Steps', this.fallbackReason, status].filter(Boolean).join(' · ');
    return `Measured · ${status} · ${this.rate(now).toFixed(1)} poses/s`;
  }

  report(now = performance.now()): Record<string, unknown> {
    return {
      mode: this.trackingMode,
      fallback_reason: this.fallbackReason,
      status_changes: [...this.changes],
      first_tracked_pose_ms: this.firstPose,
      pose_rate_hz: Number(this.rate(now).toFixed(2)),
      time_note: 'Times are milliseconds since the room view first opened, on this device.',
    };
  }

  private time(now: number): number { return Math.round(now - (this.openedAt ?? now)); }

  private rate(now: number): number {
    return this.poses.filter(time => now - time <= RATE_WINDOW_MS).length / (RATE_WINDOW_MS / 1000);
  }
}
