/**
 * The dollhouse on the headset page (#180): the room drawn smaller in front of the person, in the
 * headset's `local` reference space. Only the headset's view changes; shared positions stay in
 * room metres.
 *
 * "Room space" is the `local` space with the room at life size, where the alignment puts it.
 * "Dollhouse space" is where it is drawn: shrunk by `scale`, turned by `yaw` about the vertical
 * and moved by `offset`, as a three.js group with that position, rotation.y and scale.
 */
import { roomOrientation, roomPoint, type CalibrationInput } from '../alignment';
import type { Position, PresenceState, RoomEntity, Rotation } from '../protocol';

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

/** In a dollhouse, a hand slower than this as it lets go puts the piece down instead (#184). */
const THROW_HAND_SPEED = 0.3;

/**
 * Where a piece let go at `point` with the hand turned `orientation` (both in the `local` space)
 * lands in the room (#184): the room point under the fingertip, and its turn about the vertical.
 */
export function dollhousePlacement(
  view: DollhouseView,
  alignment: CalibrationInput,
  point: Position,
  orientation: Rotation,
): { position: Position; yaw: number } {
  return {
    position: roomPoint(alignment, fromDollhouse(view, point)),
    yaw: yawOf(roomOrientation(alignment, orientationFromDollhouse(view, orientation))),
  };
}

/**
 * What a held piece is thrown at as it is let go (#184): its own velocity in room metres, which
 * in a dollhouse is already as much faster than the hand as the room is smaller, so a toss flies
 * as far as it looks. A slow hand only drifts as it opens, and in a dollhouse that drift would be
 * a hard throw: a hand slower than 30 cm a second puts the piece down instead (null).
 */
export function throwInRoom(view: DollhouseView, velocity: Position): Position | null {
  const hand = Math.hypot(velocity.x, velocity.y, velocity.z) * view.scale;
  return view.scale < 1 && hand < THROW_HAND_SPEED ? null : velocity;
}

/** How long the hand is smoothed over in the smallest dollhouse, in milliseconds (#184). */
const SMOOTHING_MS = 50;

/**
 * Steadies a hand that holds something in a dollhouse (#184). A hand trembles a few millimetres,
 * and at 1:40 that is a dozen centimetres in the room, so the hand is followed smoothly: not at
 * all at life size, over 50 ms in the smallest dollhouse. A steady move still arrives.
 */
export class GripSmoother {
  private last: { position: Position; time: number } | null = null;

  /** Where the hand counts as being, at `time` milliseconds, in a room drawn at `scale`. */
  smooth(position: Position, time: number, scale: number): Position {
    const smallness = Math.min(1, Math.max(0, (1 / scale - 1) / (1 / SMALLEST - 1)));
    const last = this.last;
    if (!last || smallness === 0 || time <= last.time) {
      this.last = { position: { ...position }, time };
      return { ...position };
    }
    const follow = 1 - Math.exp(-(time - last.time) / (SMOOTHING_MS * smallness));
    const now = {
      x: last.position.x + (position.x - last.position.x) * follow,
      y: last.position.y + (position.y - last.position.y) * follow,
      z: last.position.z + (position.z - last.position.z) * follow,
    };
    this.last = { position: now, time };
    return { ...now };
  }

  /** Forget the hand, so the next hold starts where the hand is. */
  reset(): void {
    this.last = null;
  }
}

/** The wrist palette (#184): its pieces' spacing, height above the hand, and pinch reach. */
const SLOT_METRES = 0.06;
const PALETTE_ABOVE_HAND = 0.12;
const SLOT_REACH = 0.035;

/**
 * Where each of `count` catalogue pieces floats while the room is small (#184): a row above the
 * hand holding the palette, running to the right of the face, so it reads left to right.
 */
export function paletteSlots(hand: Position, headYaw: number, count: number): Position[] {
  // The person's right, as three.js turns +x by the head's yaw.
  const right = { x: Math.cos(headYaw), z: -Math.sin(headYaw) };
  return Array.from({ length: count }, (_, index) => {
    const along = (index - (count - 1) / 2) * SLOT_METRES;
    return { x: hand.x + right.x * along, y: hand.y + PALETTE_ABOVE_HAND, z: hand.z + right.z * along };
  });
}

/** The slot a pinch at `point` is on: the nearest within 3.5 cm, or null for none. */
export function slotAt(slots: readonly Position[], point: Position): number | null {
  let best: number | null = null;
  let bestDistance = SLOT_REACH;
  for (let index = 0; index < slots.length; index += 1) {
    const slot = slots[index];
    const distance = Math.hypot(slot.x - point.x, slot.y - point.y, slot.z - point.z);
    if (distance <= bestDistance) {
      best = index;
      bestDistance = distance;
    }
  }
  return best;
}

/** How high the room reaches above its floor, for whether a hand is in the dollhouse (#185). */
const CEILING_METRES = 3;
/** A designer's hand, wrist to fingertip, in metres: drawn this long times the dollhouse's size. */
export const HAND_METRES = 0.19;

/**
 * The room point of the first hand inside the small room (#185): over one of its floor pieces
 * and below a 3 m ceiling, in room metres, for the phone to draw a giant hand there. Null when
 * no hand is in it, or the room is at life size, where the person is simply standing in it.
 * `floor` is the room's floor pieces, as `floorPieces` gives them.
 */
export function handInDollhouse(
  view: DollhouseView,
  alignment: CalibrationInput,
  hands: readonly Position[],
  floor: readonly RoomEntity[],
): Position | null {
  if (view.scale >= 1 || floor.length === 0) return null;
  for (const hand of hands) {
    const room = roomPoint(alignment, fromDollhouse(view, hand));
    const over = floor.find(piece =>
      Math.abs(room.x - piece.position.x) <= piece.size.width / 2 &&
      Math.abs(room.z - piece.position.z) <= piece.size.depth / 2);
    if (!over) continue;
    const top = over.position.y + over.size.height;
    if (room.y >= top && room.y <= top + CEILING_METRES) return room;
  }
  return null;
}
