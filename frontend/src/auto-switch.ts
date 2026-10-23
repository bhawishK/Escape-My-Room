/**
 * When the phone switches cameras by itself to measure the eyes (#86). On the iPhone a switch kept
 * 8th Wall's map only when tracking had been normal beforehand, so a switch waits for steady
 * tracking and a still phone, and keeps its distance from the last one.
 */
import type { RoomPose } from './phone-view';

/** The rules, in milliseconds and metres; a scale shortens the times for tests. */
const RULES = {
  /** Tracking normal for this long first. */
  steadyMs: 3000,
  /** Held this still for this long first. */
  stillMs: 1000,
  stillMetres: 0.05,
  stillDegreesPerSecond: 20,
  /** A longer gap between observed frames means tracking was not being watched: start counting again. */
  gapMs: 500,
  /** Between switches: often until the eyes are measured a few times, then rarely. */
  firstEveryMs: 15000,
  laterEveryMs: 60000,
  eyesWanted: 3,
  /** After a switch where tracking did not come back. */
  afterFailureMs: 60000,
};

export interface SwitchResult {
  /**
   * Whether the switch did its job: tracking came back normal, and the front camera opened. A
   * failed or cancelled switch is followed by the long wait.
   */
  worked: boolean;
  eyesFound: boolean;
}

export class AutoSwitchScheduler {
  private readonly rules: typeof RULES;
  private trackedSince: number | null = null;
  private samples: { t: number; pose: RoomPose }[] = [];
  private eyesMeasured = 0;
  private nextAllowed = -Infinity;

  constructor(scale = 1) {
    const times = Object.fromEntries(Object.entries(RULES).map(([key, value]) => [key, key.endsWith('Ms') ? value * scale : value]));
    this.rules = times as typeof RULES;
  }

  /** Each frame: whether tracking is normal, and where the phone is. */
  observe(now: number, tracked: boolean, pose: RoomPose): void {
    const last = this.samples[this.samples.length - 1];
    if (!tracked || (last && now - last.t > this.rules.gapMs)) {
      this.trackedSince = null;
      this.samples = [];
      if (!tracked) return;
    }
    this.trackedSince ??= now;
    this.samples.push({ t: now, pose });
    const keepFrom = now - 2 * this.rules.stillMs;
    while (this.samples.length > 0 && this.samples[0].t < keepFrom) this.samples.shift();
  }

  /**
   * Whether to start a switch now; `free` says nothing else needs the cameras, the box or the view,
   * and no switch is running.
   */
  due(now: number, free: boolean): boolean {
    if (!free || now < this.nextAllowed) return false;
    if (this.trackedSince === null || now - this.trackedSince < this.rules.steadyMs) return false;
    return this.still(now);
  }

  /** A switch ended, automatic or by the button; the next waits according to how it went. */
  finished(now: number, result: SwitchResult): void {
    if (result.eyesFound) this.eyesMeasured++;
    const wait = !result.worked ? this.rules.afterFailureMs :
      this.eyesMeasured >= this.rules.eyesWanted ? this.rules.laterEveryMs : this.rules.firstEveryMs;
    this.nextAllowed = now + wait;
  }

  /** Whether the phone has stayed within a few centimetres, turning, tilting or rolling slowly, over the last `stillMs`. */
  private still(now: number): boolean {
    const from = now - this.rules.stillMs;
    if (this.samples.length === 0 || this.samples[0].t > from) return false;
    const latest = this.samples[this.samples.length - 1].pose;
    const turnLimit = this.rules.stillDegreesPerSecond * Math.PI / 180 * this.rules.stillMs / 1000;
    return this.samples.filter(sample => sample.t >= from).every(({ pose }) => {
      const p = pose.position;
      const q = latest.position;
      // The whole rotation between the two, in any direction.
      const a = pose.orientation;
      const b = latest.orientation;
      const dot = Math.min(1, Math.abs(a.x * b.x + a.y * b.y + a.z * b.z + a.w * b.w));
      const turn = 2 * Math.acos(dot);
      return Math.hypot(p.x - q.x, p.y - q.y, p.z - q.z) <= this.rules.stillMetres && turn <= turnLimit;
    });
  }
}
