/**
 * The wrist menu above the left hand (#204): a slider of five pages, Objects (the catalogue),
 * Make (a new piece from a spoken description), Drill (the headset page's Drill card: the room's
 * objects to choose from, then Prepare, Start or Stop, and Call off, #234), Edit (Move and Resize
 * for the chosen piece) and Exit. An open left palm shows it and a fist hides it. Positions are in the `local` space, laid
 * out across the person's view as the head faces.
 */
import type { Position } from '../protocol';
import type { HandPose } from './gestures';

export const WRIST_PAGES = ['objects', 'make', 'drill', 'edit', 'exit'] as const;
export type WristPage = typeof WRIST_PAGES[number];
export const PAGE_NAMES: Record<WristPage, string> = { objects: 'Objects', make: 'Make', drill: 'Drill', edit: 'Edit', exit: 'Exit' };

/** The slider's stops: this far above the hand, this far apart. */
const TRACK_ABOVE = 0.22;
const STOP_METRES = 0.065;
/** A page's line of text, and its row of buttons or pieces, this far above the hand. */
const LINE_ABOVE = 0.165;
const ROW_ABOVE = 0.12;
/** The catalogue's pieces this far apart; Make's and Edit's two buttons this far apart. */
const SLOT_METRES = 0.06;
const PAIR_METRES = 0.08;
/** The Drill page's objects this far apart, and its row of Prepare, Start and Call off this far below them. */
const OBJECT_METRES = 0.075;
const CONTROLS_BELOW = 0.045;
/** A pinch this near a button or piece chooses it; this near the slider's track takes hold of it. */
const REACH = 0.035;
const TRACK_REACH = 0.03;

const distance = (a: Position, b: Position) => Math.hypot(a.x - b.x, a.y - b.y, a.z - b.z);

/** Where everything on the wrist menu is now. */
export interface WristMenu {
  page: WristPage;
  /** The slider's stops, one per page, in WRIST_PAGES order. */
  stops: Position[];
  /** Where the page's line of text is. */
  line: Position;
  /** The catalogue's pieces, on the Objects page; else none. */
  pieces: Position[];
  /** The room's objects to choose from, on the Drill page; else none. */
  objects: Position[];
  /** The page's buttons by name: speak and make, prepare, run and cancel, move and resize, or exit. */
  buttons: Partial<Record<WristButton, Position>>;
}
export type WristButton = 'speak' | 'make' | 'guide' | 'prepare' | 'run' | 'cancel' | 'move' | 'resize' | 'floor' | 'mute' | 'exit';

/** What a pinch on the menu is on. */
export type WristChoice =
  | { kind: 'piece'; index: number }
  | { kind: 'object'; index: number }
  | { kind: 'button'; button: WristButton }
  | { kind: 'track' }
  | null;

/** The menu above `hand`, on `page`, with `pieces` in the catalogue and `objects` in the room. */
export function wristMenu(hand: Position, headYaw: number, page: WristPage, pieces: number, objects = 0): WristMenu {
  // The person's right, as three.js turns +x by the head's yaw.
  const right = { x: Math.cos(headYaw), z: -Math.sin(headYaw) };
  const at = (along: number, above: number): Position => ({
    x: hand.x + right.x * along, y: hand.y + above, z: hand.z + right.z * along,
  });
  const row = (count: number, apart: number) =>
    Array.from({ length: count }, (_, index) => at((index - (count - 1) / 2) * apart, ROW_ABOVE));
  const stops = row(WRIST_PAGES.length, STOP_METRES).map(stop => ({ ...stop, y: hand.y + TRACK_ABOVE }));
  const buttons: WristMenu['buttons'] = {};
  if (page === 'make' || page === 'edit') {
    const [left, rightButton] = row(2, PAIR_METRES);
    if (page === 'make') Object.assign(buttons, { speak: left, make: rightButton });
    else Object.assign(buttons, { move: left, resize: rightButton });
    // Touch the floor (#218), on its own row so Move and Resize stay where they are.
    if (page === 'edit') buttons.floor = { ...at(0, ROW_ABOVE), y: hand.y + ROW_ABOVE - CONTROLS_BELOW };
  }
  if (page === 'drill') {
    // Guide sets the "go here" spot with a pinch on the floor (#273).
    const [speak, guide, prepare, run, cancel] = row(5, PAIR_METRES).map(at => ({ ...at, y: at.y - CONTROLS_BELOW }));
    Object.assign(buttons, { speak, guide, prepare, run, cancel });
  }
  if (page === 'exit') {
    // Mute is a button, not a fist (#273).
    const [mute, exit] = row(2, PAIR_METRES);
    Object.assign(buttons, { mute, exit });
  }
  return {
    page, stops, line: at(0, LINE_ABOVE),
    pieces: page === 'objects' ? row(pieces, SLOT_METRES) : [],
    objects: page === 'drill' ? row(objects, OBJECT_METRES) : [],
    buttons,
  };
}

/** What a pinch at `point` is on: a piece, a button, the slider's track, or nothing. */
export function wristChoice(menu: WristMenu, point: Position): WristChoice {
  if (onTrack(menu, point)) return { kind: 'track' };
  let best: WristChoice = null;
  let nearest = REACH;
  menu.pieces.forEach((piece, index) => {
    const away = distance(piece, point);
    if (away <= nearest) [best, nearest] = [{ kind: 'piece', index }, away];
  });
  menu.objects.forEach((object, index) => {
    const away = distance(object, point);
    if (away <= nearest) [best, nearest] = [{ kind: 'object', index }, away];
  });
  for (const [button, at] of Object.entries(menu.buttons) as [WristButton, Position][]) {
    const away = distance(at, point);
    if (away <= nearest) [best, nearest] = [{ kind: 'button', button }, away];
  }
  return best;
}

/** Whether `point` is on the slider's track: near the line through its stops, between its ends. */
function onTrack(menu: WristMenu, point: Position): boolean {
  const first = menu.stops[0];
  const last = menu.stops[menu.stops.length - 1];
  const length = distance(first, last);
  const along = alongTrack(menu, point) * length;
  const across = { x: first.x + (last.x - first.x) * along / length, y: first.y, z: first.z + (last.z - first.z) * along / length };
  return along >= -TRACK_REACH && along <= length + TRACK_REACH && distance(across, point) <= TRACK_REACH;
}

/** How far along the track `point` is, 0 at the first stop and 1 at the last. */
function alongTrack(menu: WristMenu, point: Position): number {
  const first = menu.stops[0];
  const last = menu.stops[menu.stops.length - 1];
  const dx = last.x - first.x;
  const dz = last.z - first.z;
  return ((point.x - first.x) * dx + (point.z - first.z) * dz) / (dx * dx + dz * dz);
}

/** The page whose stop is nearest `point` along the track. */
export function pageAt(menu: WristMenu, point: Position): WristPage {
  const along = Math.min(1, Math.max(0, alongTrack(menu, point)));
  return WRIST_PAGES[Math.round(along * (WRIST_PAGES.length - 1))];
}

/** An open palm or a fist held this long opens or closes the menu, so a hand passing through does nothing. */
export const PALM_HOLD_MS = 150;

/**
 * Whether the wrist menu is open: an open left palm held a moment opens it, a fist held a moment
 * closes it, and a hand out of sight closes it. Anything between keeps it as it is, so a hand
 * relaxing a little doesn't close it.
 */
export class PalmToggle {
  open = false;
  /** While the fist that closed the menu is still held: that fist doesn't also mute (#175). */
  closingFist = false;
  private pose: HandPose | null = null;
  private since = 0;

  /** The hand's pose this frame, null when it isn't seen; whether the menu is open. */
  update(pose: HandPose | null, now: number): boolean {
    if (pose === null) {
      this.open = false;
      this.closingFist = false;
      this.pose = null;
      return false;
    }
    if (pose !== this.pose) {
      this.pose = pose;
      this.since = now;
    }
    if (pose !== 'fist') this.closingFist = false;
    const held = now - this.since >= PALM_HOLD_MS;
    if (held && pose === 'open-palm') this.open = true;
    if (held && pose === 'fist' && this.open) {
      this.open = false;
      this.closingFist = true;
    }
    return this.open;
  }
}
