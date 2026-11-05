/**
 * Hand and head gestures on the headset page (#156). Immersive Web SDK gives the hand joints and
 * pinches; the poses and head motions the visiting interactions need are read here, from joint
 * positions in metres.
 */
import { rayForward } from '../grab';
import type { Position, Rotation } from '../protocol';

/** WebXR hand joints by name, where the frame gave a pose for them. */
export type HandJoints = Partial<Record<XRHandJoint, Position>>;

export type HandPose = 'pinch' | 'point' | 'open-palm' | 'none';

const FINGERS = ['index-finger', 'middle-finger', 'ring-finger', 'pinky-finger'] as const;
/**
 * A finger is extended when its tip is this many times farther from the wrist than its knuckle:
 * about 1.9 straight, about 1 curled under the palm.
 */
const EXTENDED_RATIO = 1.4;

const distance = (a: Position, b: Position) => Math.hypot(a.x - b.x, a.y - b.y, a.z - b.z);

/** Whether the finger is straight, curled, or not seen this frame (null). */
function extended(joints: HandJoints, finger: typeof FINGERS[number]): boolean | null {
  const wrist = joints.wrist;
  const knuckle = joints[`${finger}-phalanx-proximal`];
  const tip = joints[`${finger}-tip`];
  if (!wrist || !knuckle || !tip) return null;
  return distance(wrist, tip) > EXTENDED_RATIO * distance(wrist, knuckle);
}

/** The thumb and index tips touch when closer than this, in metres. */
const PINCH_METRES = 0.02;

/** The pose the hand makes now. A pinch wins over what the other fingers do. */
export function handPose(joints: HandJoints): HandPose {
  const thumb = joints['thumb-tip'];
  const indexTip = joints['index-finger-tip'];
  if (thumb && indexTip && distance(thumb, indexTip) < PINCH_METRES) return 'pinch';
  const straight = FINGERS.map(finger => extended(joints, finger));
  if (straight.every(finger => finger === true)) return 'open-palm';
  const [index, ...others] = straight;
  if (index === true && others.every(finger => finger === false)) return 'point';
  return 'none';
}

/**
 * Lets a pose through once it has been held `holdMs`, so a hand passing through it does nothing.
 * It then fires again only after it is let go and `cooldownMs` has passed since it fired.
 */
export class GestureGate<T extends string> {
  private pose: T | null = null;
  private since = 0;
  private fired = false;
  private firedAt = -Infinity;

  constructor(private readonly options: { holdMs: number; cooldownMs: number }) {}

  /** This frame's pose, `'none'` for none, at `now` milliseconds: the pose when it fires, else null. */
  update(pose: T | 'none', now: number): T | null {
    if (pose === 'none') {
      this.pose = null;
      return null;
    }
    if (pose !== this.pose) {
      this.pose = pose;
      this.since = now;
      this.fired = false;
    }
    if (this.fired || now - this.since < this.options.holdMs || now - this.firedAt < this.options.cooldownMs) return null;
    this.fired = true;
    this.firedAt = now;
    return pose;
  }
}

/** A head turn back the other way counts once the head has come back this far, in degrees. */
const SWING_DEGREES = 8;
/** Two turns back within this long are a nod or a shake. */
const NOD_WINDOW_MS = 1200;

/** Turns of one angle back the other way: a nod is two of them in the head's tilt. */
class Swings {
  /** The angle last seen, and the same angle counted on past ±180° so a turn never wraps. */
  private last: number | null = null;
  private angle = 0;
  /** The farthest point of the current move, and its way: 1 up or left, -1 down or right, 0 none yet. */
  private extreme = 0;
  private direction = 0;
  private turns: number[] = [];

  /** The angle now, in degrees: how many times it turned back within the window. */
  update(degrees: number, now: number): number {
    this.turns = this.turns.filter(at => now - at <= NOD_WINDOW_MS);
    if (this.last === null) {
      this.last = degrees;
      this.angle = this.extreme = degrees;
      return this.turns.length;
    }
    // The shortest way from the last angle, so 179° to -179° is 2°, not -358°.
    this.angle += ((degrees - this.last + 540) % 360) - 180;
    this.last = degrees;
    const moved = this.angle - this.extreme;
    if (Math.sign(moved) === this.direction) {
      // Still going the same way: the far point follows the head.
      this.extreme = this.angle;
    } else if (Math.abs(moved) >= SWING_DEGREES) {
      // Back the other way far enough; the first move only sets the way.
      if (this.direction !== 0) this.turns.push(now);
      this.direction = Math.sign(moved);
      this.extreme = this.angle;
    }
    return this.turns.length;
  }

  clear(): void {
    this.last = null;
    this.direction = 0;
    this.turns = [];
  }
}

/** Yes and no from the head: nodding down and up twice, or shaking side to side twice. */
export class HeadNods {
  private readonly tilt = new Swings();
  private readonly turn = new Swings();

  /** The head's orientation at `now` milliseconds: yes or no when one is made, else null. */
  update(orientation: Rotation, now: number): 'yes' | 'no' | null {
    const forward = rayForward(orientation);
    const pitch = Math.asin(Math.max(-1, Math.min(1, forward.y))) * 180 / Math.PI;
    const yaw = Math.atan2(-forward.x, -forward.z) * 180 / Math.PI;
    const nodded = this.tilt.update(pitch, now) >= 2;
    const shook = this.turn.update(yaw, now) >= 2;
    if (!nodded && !shook) return null;
    this.tilt.clear();
    this.turn.clear();
    return nodded ? 'yes' : 'no';
  }
}

/** How long the gaze has rested on one object, and whether it has just rested long enough. */
export class Dwell {
  private target: string | null = null;
  private since = 0;
  private started = false;

  constructor(private readonly ms: number) {}

  /** What the gaze is on at `now` milliseconds, or null for nothing. */
  update(target: string | null, now: number): { target: string | null; progress: number; started: boolean } {
    if (target !== this.target) {
      this.target = target;
      this.since = now;
      this.started = false;
    }
    if (target === null) return { target, progress: 0, started: false };
    const progress = Math.min(1, (now - this.since) / this.ms);
    const starts = progress >= 1 && !this.started;
    if (starts) this.started = true;
    return { target, progress, started: starts };
  }
}
