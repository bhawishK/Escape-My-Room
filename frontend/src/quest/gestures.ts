/**
 * Hand and head gestures on the headset page (#156). Immersive Web SDK gives the hand joints and
 * pinches; the poses and head motions the visiting interactions need are read here, from joint
 * positions in metres.
 */
import type { Position } from '../protocol';

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
  private extreme: number | null = null;
  private direction = 0;
  private turns: number[] = [];

  /** The angle now, in degrees: how many times it turned back within the window. */
  update(angle: number, now: number): number {
    this.turns = this.turns.filter(at => now - at <= NOD_WINDOW_MS);
    if (this.extreme === null) {
      this.extreme = angle;
      return this.turns.length;
    }
    const moved = angle - this.extreme;
    if (this.direction === 0 || Math.sign(moved) === this.direction) {
      // Still going the same way, or the first move: the far point follows the head.
      if (Math.abs(moved) > 0 && (this.direction === 0 ? Math.abs(moved) >= SWING_DEGREES : true)) {
        this.direction = this.direction || Math.sign(moved);
        this.extreme = angle;
      }
    } else if (Math.abs(moved) >= SWING_DEGREES) {
      this.turns.push(now);
      this.direction = Math.sign(moved);
      this.extreme = angle;
    }
    return this.turns.length;
  }

  clear(): void {
    this.extreme = null;
    this.direction = 0;
    this.turns = [];
  }
}

/** Yes and no from the head: nodding down and up twice, or shaking side to side twice. */
export class HeadNods {
  private readonly tilt = new Swings();
  private readonly turn = new Swings();

  /** The head's orientation at `now` milliseconds: yes or no when one is made, else null. */
  update(orientation: { x: number; y: number; z: number; w: number }, now: number): 'yes' | 'no' | null {
    const { x, y, z, w } = orientation;
    // Where the head looks: its -Z axis.
    const forwardX = -2 * (w * y + x * z);
    const forwardY = 2 * (w * x - y * z);
    const forwardZ = -1 + 2 * (x * x + y * y);
    const pitch = Math.asin(Math.max(-1, Math.min(1, forwardY))) * 180 / Math.PI;
    const yaw = Math.atan2(-forwardX, -forwardZ) * 180 / Math.PI;
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
