/**
 * The dollhouse on the headset page (#180): the room drawn smaller in front of the person, in the
 * headset's `local` reference space. Only the headset's view changes; shared positions stay in
 * room metres.
 *
 * "Room space" is the `local` space with the room at life size, where the alignment puts it.
 * "Dollhouse space" is where it is drawn: shrunk by `scale`, turned by `yaw` about the vertical
 * and moved by `offset`, as a three.js group with that position, rotation.y and scale.
 */
import type { Position, PresenceState, Rotation } from '../protocol';

export interface DollhouseView {
  /** How big the room is drawn: 1 at life size, 0.05 at a twentieth. */
  scale: number;
  /** Radians about the vertical, as three.js turns rotation.y. */
  yaw: number;
  offset: Position;
}

export const LIFE_SIZE: DollhouseView = { scale: 1, yaw: 0, offset: { x: 0, y: 0, z: 0 } };

/** `p` turned `yaw` about the vertical, as three.js turns it. */
function turned(p: Position, yaw: number): Position {
  const cosine = Math.cos(yaw);
  const sine = Math.sin(yaw);
  return { x: cosine * p.x + sine * p.z, y: p.y, z: -sine * p.x + cosine * p.z };
}

/** Where a point of the life-size room is drawn in the dollhouse. */
export function toDollhouse(view: DollhouseView, point: Position): Position {
  const p = turned(point, view.yaw);
  return { x: view.offset.x + view.scale * p.x, y: view.offset.y + view.scale * p.y, z: view.offset.z + view.scale * p.z };
}

/** The point of the life-size room under a point of the dollhouse, such as a fingertip. */
export function fromDollhouse(view: DollhouseView, point: Position): Position {
  const { offset, scale } = view;
  return turned({ x: (point.x - offset.x) / scale, y: (point.y - offset.y) / scale, z: (point.z - offset.z) / scale }, -view.yaw);
}

export function velocityToDollhouse(view: DollhouseView, velocity: Position): Position {
  const v = turned(velocity, view.yaw);
  return { x: view.scale * v.x, y: view.scale * v.y, z: view.scale * v.z };
}

/** A hand's speed in the dollhouse as the room's: a 5 cm/s move at a twentieth is 1 m/s. */
export function velocityFromDollhouse(view: DollhouseView, velocity: Position): Position {
  const { scale } = view;
  return turned({ x: velocity.x / scale, y: velocity.y / scale, z: velocity.z / scale }, -view.yaw);
}

/** The smallest and largest the room is drawn. */
export const SMALLEST = 1 / 40;
const LARGEST = 1;
/** Let go grown back past this, the room snaps to life size where the alignment puts it. */
const SNAP = 0.9;
/** Hands closer than this when scaling would start give no reliable distance to scale by. */
const MIN_APART_METRES = 0.005;

const distance = (a: Position, b: Position) => Math.hypot(a.x - b.x, a.y - b.y, a.z - b.z);
const midpoint = (a: Position, b: Position): Position => ({ x: (a.x + b.x) / 2, y: (a.y + b.y) / 2, z: (a.z + b.z) / 2 });

/**
 * Two pinched hands scale the room: pulled together it shrinks, pulled apart it grows, around the
 * point between them, which then follows the hands. Scaling starts only when two hands pinch and
 * no object is held, and stops when either lets go. Let go near life size, it snaps back there.
 */
export class DollhouseScaling {
  view: DollhouseView = LIFE_SIZE;
  /** Since scaling started: the hands' distance, the view, and the room point between the hands. */
  private start: { apart: number; view: DollhouseView; held: Position } | null = null;

  get scaling(): boolean {
    return this.start !== null;
  }

  /**
   * This frame's pinches that hold nothing, in the `local` space, and whether the headset is free
   * to scale: no object held, not paused, lined up. Returns the view to draw the room with.
   */
  update(pinches: readonly Position[], free: boolean): DollhouseView {
    if (pinches.length < 2) {
      // Let go near life size, the room snaps there; while held it stays around the hands, so
      // jitter near the snap never flickers between the two places.
      if (this.start && this.view.scale >= SNAP) this.view = LIFE_SIZE;
      this.start = null;
      return this.view;
    }
    const [a, b] = pinches;
    if (!this.start) {
      if (!free || distance(a, b) < MIN_APART_METRES) return this.view;
      this.start = { apart: distance(a, b), view: this.view, held: fromDollhouse(this.view, midpoint(a, b)) };
      return this.view;
    }
    const { apart, view, held } = this.start;
    const scale = Math.min(LARGEST, Math.max(SMALLEST, view.scale * distance(a, b) / apart));
    // The room point that was between the hands is drawn between them now.
    const centre = midpoint(a, b);
    const drawn = toDollhouse({ ...view, scale, offset: { x: 0, y: 0, z: 0 } }, held);
    this.view = { scale, yaw: view.yaw, offset: { x: centre.x - drawn.x, y: centre.y - drawn.y, z: centre.z - drawn.z } };
    return this.view;
  }

  /** Back to life size, ending any scaling: after a reset, a new session or a lost alignment. */
  reset(): void {
    this.start = null;
    this.view = LIFE_SIZE;
  }
}

/**
 * How far a grip or head is turned about the vertical, in radians, as three.js turns rotation.y:
 * the twist of its quaternion about y. Unlike reading where its forward axis points, this stays
 * steady however the hand or head is tilted, straight up included.
 */
export function yawOf(orientation: Rotation): number {
  return 2 * Math.atan2(orientation.y, orientation.w);
}

/**
 * One hand carries the dollhouse (#182): it moves with the hand and turns as the hand turns about
 * the vertical, so the point of the room the hand took hold of stays in the hand. Only a room
 * smaller than life size can be carried; at life size it is the real room around the person.
 */
export class DollhouseCarry {
  /** Since the hand took hold: the view, the hand's turn, and the room point it holds. */
  private start: { view: DollhouseView; yaw: number; held: Position } | null = null;

  get carrying(): boolean {
    return this.start !== null;
  }

  /** Takes hold with `hand` in the `local` space; false, and nothing held, at life size. */
  begin(hand: { position: Position; orientation: Rotation }, view: DollhouseView): boolean {
    if (view.scale >= 1) return false;
    this.start = { view, yaw: yawOf(hand.orientation), held: fromDollhouse(view, hand.position) };
    return true;
  }

  /** Where the dollhouse is with the hand here now. */
  update(hand: { position: Position; orientation: Rotation }): DollhouseView {
    if (!this.start) throw new Error('Nothing is being carried.');
    const { view, yaw, held } = this.start;
    const turned = view.yaw + yawOf(hand.orientation) - yaw;
    const drawn = toDollhouse({ ...view, yaw: turned, offset: { x: 0, y: 0, z: 0 } }, held);
    const { position } = hand;
    return {
      scale: view.scale,
      yaw: turned,
      offset: { x: position.x - drawn.x, y: position.y - drawn.y, z: position.z - drawn.z },
    };
  }

  /** Let go: the dollhouse stays where it was last carried. */
  end(): void {
    this.start = null;
  }
}

/** How tall the resident's figure is at life size, and the least it is drawn in a dollhouse. */
export const FIGURE_METRES = 1.55;
const SMALLEST_FIGURE_METRES = 0.08;

/** Where the room's anchor puts room metres in the `local` space before any dollhouse. */
export interface RoomAnchor { yaw: number; offset: Position }

/**
 * The resident's figure in the dollhouse (#182): where their feet are and which way they face in
 * the `local` space, how tall it is drawn and how solid. A figure to scale would be lost at 1:40,
 * so it is never drawn smaller than 8 cm. Null when they have no place to show: inactive, lost,
 * or not yet placed.
 */
export function residentFigure(
  presence: PresenceState | undefined,
  view: DollhouseView,
  anchor: RoomAnchor,
): { position: Position; heading: number; height: number; opacity: number } | null {
  const shown = presence?.tracking_status === 'tracked' || presence?.tracking_status === 'stale';
  if (!shown || !presence.position || presence.heading === null) return null;
  const turnedFeet = turned(presence.position, anchor.yaw);
  const inRoomSpace = {
    x: anchor.offset.x + turnedFeet.x, y: anchor.offset.y + turnedFeet.y, z: anchor.offset.z + turnedFeet.z,
  };
  return {
    position: toDollhouse(view, inRoomSpace),
    heading: presence.heading + anchor.yaw + view.yaw,
    height: Math.max(FIGURE_METRES * view.scale, SMALLEST_FIGURE_METRES),
    opacity: presence.tracking_status === 'stale' ? 0.35 : 1,
  };
}


/** The scale as a model maker writes it: "1:20" for a room drawn at a twentieth. */
export function scaleLabel(scale: number): string {
  return `1:${Math.round(1 / scale)}`;
}

/** `q` turned `yaw` about the vertical first: the quaternion product (yaw) × q. */
function yawed(yaw: number, q: Rotation): Rotation {
  const s = Math.sin(yaw / 2);
  const c = Math.cos(yaw / 2);
  return {
    x: c * q.x + s * q.z,
    y: c * q.y + s * q.w,
    z: c * q.z - s * q.x,
    w: c * q.w - s * q.y,
  };
}

export function orientationToDollhouse(view: DollhouseView, orientation: Rotation): Rotation {
  return yawed(view.yaw, orientation);
}

export function orientationFromDollhouse(view: DollhouseView, orientation: Rotation): Rotation {
  return yawed(-view.yaw, orientation);
}
