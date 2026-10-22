/**
 * The camera-switch experiment (#74): pause the 8th Wall engine, which releases the back camera,
 * use the front camera briefly, and resume the engine, timing every stage. It answers how long the
 * phone is without the back camera and whether the engine keeps tracking or starts over.
 */
import { yawOf, type RoomPose } from './phone-view';

/**
 * How long tracking must stay normal after a switch before it counts as back: a resumed engine can
 * send one normal frame and then start initialising.
 */
const SETTLE_MS = 1000;
/** How long to wait for the front camera's first picture before giving up on it. */
const FRONT_FIRST_FRAME_LIMIT_MS = 1500;

export interface CameraSwitchHooks {
  pauseEngine(): void;
  resumeEngine(): void;
  openFrontCamera(): Promise<MediaStream>;
  /** Starts anything the eye measurement needs, such as its model, as the switch begins. */
  prepareEyes(): void;
  /** Measures the eyes from `video`, which shows the front camera; `cancelled` says to stop early. */
  measureEyes(video: HTMLVideoElement, cancelled: () => boolean): Promise<Record<string, unknown>>;
  /** The engine's last pose as it gave it, before any lining up, or null before it has one. */
  rawPose(): RoomPose | null;
  status(message: string): void;
  log(name: string, detail: string, data?: Record<string, unknown>): void;
}

type Outcome = 'tracking kept' | 'tracking came back after initialising' | 'tracking did not come back' | 'cancelled';

export class CameraSwitch {
  private switching = false;
  private cancelled = false;
  private startedAt = 0;
  private front: MediaStream | null = null;
  private resumedAt: number | null = null;
  private backVideoAt: number | null = null;
  private firstPoseAt: number | null = null;
  private normalAt: number | null = null;
  private initializing = false;
  private before: RoomPose | null = null;
  private after: RoomPose | null = null;
  /** Ends the current wait early: tracking is back, or the switch was cancelled. */
  private wake: (() => void) | null = null;
  private cancelWait: (() => void) | null = null;

  /** `timeoutMs` is how long the engine has after resuming to track normally again. */
  constructor(private readonly hooks: CameraSwitchHooks, private readonly timeoutMs = 10000) {}

  get running(): boolean { return this.switching; }

  /** The engine's camera status, forwarded while a switch runs. */
  cameraStatus(status: string): void {
    if (this.switching && this.resumedAt !== null && status === 'hasVideo' && this.backVideoAt === null) {
      this.backVideoAt = this.since();
    }
  }

  /** Each engine frame as the engine gave it, forwarded while a switch runs. */
  engineFrame(status: string, reason: string, raw: RoomPose): void {
    if (!this.switching || this.resumedAt === null) return;
    this.firstPoseAt ??= this.since();
    if (reason === 'INITIALIZING') {
      this.initializing = true;
      // A normal frame before this was not tracking coming back.
      this.normalAt = null;
      this.after = null;
    }
    if (status === 'NORMAL' && this.normalAt === null) {
      this.normalAt = this.since();
      this.after = raw;
      this.wake?.();
    }
  }

  /** Ends a switch at once, for example when the room view closes; the front camera is closed. */
  cancel(): void {
    if (!this.switching) return;
    this.cancelled = true;
    this.closeFront();
    this.cancelWait?.();
  }

  async run(): Promise<void> {
    if (this.switching) return;
    this.reset();
    this.switching = true;
    this.startedAt = performance.now();
    this.before = this.hooks.rawPose();
    this.hooks.log('camera switch start', 'pausing the engine for the front camera');
    this.hooks.status('Switching cameras · front camera');
    this.hooks.prepareEyes();
    this.hooks.pauseEngine();
    const data: Record<string, unknown> = {};
    // On the page but out of sight: a phone may stop decoding a video that is not on the page.
    const video = document.createElement('video');
    video.muted = true;
    video.playsInline = true;
    video.setAttribute('aria-hidden', 'true');
    video.style.cssText = 'position: fixed; width: 1px; height: 1px; opacity: 0; pointer-events: none;';
    document.body.append(video);
    const why = (error: unknown) => (error instanceof Error ? error.message : String(error));
    try {
      this.front = await this.hooks.openFrontCamera();
      data.front_camera = 'opened';
    } catch (error) {
      data.front_camera = `not opened: ${why(error)}`;
    }
    // Cancelled while the camera was opening: it closes below at once.
    if (this.front && !this.cancelled) {
      video.srcObject = this.front;
      try {
        data.front_first_frame_ms = await this.firstFrame(video);
        this.hooks.status('Switching cameras · measuring your eyes, look at the screen');
        data.eyes = await this.hooks.measureEyes(video, () => this.cancelled);
        data.eyes_ms = this.since();
      } catch (error) {
        data.eyes = { found: false, reason: why(error), frames: 0 };
      }
    }
    data.eyes ??= { found: false, reason: this.cancelled ? 'cancelled' : 'front camera not opened', frames: 0 };
    video.srcObject = null;
    video.remove();
    this.closeFront();
    data.front_closed_ms = this.since();
    if (!this.cancelled) {
      this.hooks.status('Switching cameras · back to tracking');
      this.resumedAt = this.since();
      this.hooks.resumeEngine();
      await this.untilSettled();
    }
    this.finish(data);
  }

  private finish(data: Record<string, unknown>): void {
    const outcome: Outcome = this.cancelled ? 'cancelled' : this.normalAt === null ? 'tracking did not come back' :
      this.initializing ? 'tracking came back after initialising' : 'tracking kept';
    // The engine is paused as the switch starts, so the back camera is gone until its video returns.
    const withoutBack = this.backVideoAt ?? this.firstPoseAt;
    Object.assign(data, {
      outcome, initializing: this.initializing, resumed_ms: this.resumedAt, back_video_ms: this.backVideoAt,
      first_pose_ms: this.firstPoseAt, normal_ms: this.normalAt, no_back_camera_ms: withoutBack,
      total_ms: this.since(), offset: this.offset(),
    });
    this.hooks.log('camera switch', outcome, data);
    const gap = withoutBack === null ? '' : ` · ${(withoutBack / 1000).toFixed(1)} s without the back camera`;
    this.hooks.status(`Switched cameras${gap} · ${outcome}`);
    this.switching = false;
  }

  /** Waits until tracking has stayed normal for SETTLE_MS, or the time limit passes, or a cancel. */
  private async untilSettled(): Promise<void> {
    const deadline = performance.now() + this.timeoutMs;
    while (!this.cancelled && performance.now() < deadline) {
      if (this.normalAt === null) await this.wait(deadline - performance.now());
      else {
        const normalSince = this.normalAt;
        await this.wait(Math.min(SETTLE_MS, deadline - performance.now()), false);
        if (this.normalAt === normalSince) return;
      }
    }
  }

  /** Waits `ms`; tracking returning ends it early when `wakes`, and cancelling always does. */
  private wait(ms: number, wakes = true): Promise<void> {
    return new Promise(resolve => {
      const done = () => {
        clearTimeout(timer);
        this.wake = null;
        this.cancelWait = null;
        resolve();
      };
      const timer = setTimeout(done, Math.max(0, ms));
      if (wakes) this.wake = done;
      this.cancelWait = done;
    });
  }

  /** How far the engine's own pose moved across the switch, while the phone was meant to stand still. */
  private offset(): { metres: number; degrees: number } | null {
    if (!this.before || !this.after) return null;
    const a = this.before.position;
    const b = this.after.position;
    const turn = yawOf(this.after.orientation) - yawOf(this.before.orientation);
    return {
      metres: Math.round(Math.hypot(b.x - a.x, b.y - a.y, b.z - a.z) * 100) / 100,
      degrees: Math.round(Math.atan2(Math.sin(turn), Math.cos(turn)) * 180 / Math.PI) + 0,
    };
  }

  /** Waits for the camera's first picture in `video`, and says when it came since the switch began. */
  private async firstFrame(video: HTMLVideoElement): Promise<number> {
    let timer = 0;
    try {
      await Promise.race([
        new Promise<void>(resolve => {
          if (video.readyState >= 2) resolve();
          else video.addEventListener('loadeddata', () => resolve(), { once: true });
          void video.play().catch(() => undefined);
        }),
        new Promise<void>((_, reject) => {
          const started = performance.now();
          // Checked often, so a cancel ends the wait at once.
          timer = window.setInterval(() => {
            if (this.cancelled) reject(new Error('cancelled'));
            else if (performance.now() - started > FRONT_FIRST_FRAME_LIMIT_MS) reject(new Error('no picture from the front camera'));
          }, 30);
        }),
      ]);
      return this.since();
    } finally {
      clearInterval(timer);
    }
  }

  private closeFront(): void {
    this.front?.getTracks().forEach(track => track.stop());
    this.front = null;
  }

  private reset(): void {
    this.cancelled = false;
    this.resumedAt = null;
    this.backVideoAt = null;
    this.firstPoseAt = null;
    this.normalAt = null;
    this.initializing = false;
    this.before = null;
    this.after = null;
  }

  private since(): number { return Math.round(performance.now() - this.startedAt); }
}
