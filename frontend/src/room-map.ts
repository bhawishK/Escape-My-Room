/**
 * The room's 2D map (#124): the room seen from above, its objects as icons and the players as
 * dots with an arrow the way each faces. A room with a map image (`map.png`, made with the room)
 * shows it; another shows its floor and furniture as outlines. Pressing on the map, and dragging,
 * picks a spot on the floor and a way to face: the phone places itself there, the headset stands
 * there. Its top is the room's -z and its right +x.
 */
import type { PresenceState, Role, SessionState } from './protocol';

type Room = SessionState['room'];

/** A spot on the floor, in room metres. */
export interface Spot { x: number; z: number }

export interface MapEvents {
  /** A spot was picked; `heading` is the way dragged (0 faces -z, positive to the left), or null for a tap. */
  pick?: (spot: Spot, heading: number | null) => void;
}

/** An icon for each kind of object Qwen names; anything else gets a pin. */
const ICONS: Record<string, string> = {
  door: '🚪', sink: '🚰', 'waste bin': '🗑️', bin: '🗑️', cupboard: '🗄️', cabinet: '🗄️', wardrobe: '🗄️',
  desk: '🪑', table: '🪑', chair: '🪑', bed: '🛏️', sofa: '🛋️', couch: '🛋️', tv: '📺', television: '📺',
  window: '🪟', mirror: '🪞', plant: '🪴', box: '📦', toilet: '🚽', bath: '🛁', shower: '🚿',
};
const PIN = '📍';
// A drag shorter than this, in pixels, is a tap: the way to face is not changed.
const DRAG_PIXELS = 12;
// Static entities this thin are floor, as the phone's step counting takes them.
const FLOOR_THICKNESS = 0.05;

interface Bounds { minX: number; maxX: number; minZ: number; maxZ: number }

const percent = (fraction: number) => `${(fraction * 100).toFixed(1)}%`;
const capitalised = (text: string) => `${text.charAt(0).toUpperCase()}${text.slice(1)}`;

export class RoomMap {
  readonly plan: HTMLElement;
  private readonly outlines: HTMLElement;
  private readonly marks: HTMLElement;
  private readonly people: HTMLElement;
  private bounds: Bounds = { minX: -2, maxX: 2, minZ: -2, maxZ: 2 };
  private shownRoom = '';

  constructor(private readonly root: HTMLElement, private readonly name: string, private readonly events: MapEvents = {}) {
    root.classList.add('room-map');
    root.dataset.testid = name;
    this.plan = this.layer('room-map-plan');
    this.plan.dataset.testid = `${name}-plan`;
    this.outlines = this.layer('room-map-outlines', this.plan);
    this.marks = this.layer('room-map-marks', this.plan);
    this.people = this.layer('room-map-people', this.plan);
    this.listen();
  }

  /** Draws the room: its map image or outlines, and its objects as icons. */
  showRoom(room: Room): void {
    const shown = JSON.stringify([room.room_version, room.map, room.landmarks, room.entities.map(e => [e.id, e.position])]);
    if (shown === this.shownRoom) return;
    this.shownRoom = shown;
    this.bounds = room.map ?
      { minX: room.map.min_x, maxX: room.map.max_x, minZ: room.map.min_z, maxZ: room.map.max_z } :
      outlineBounds(room);
    const { minX, maxX, minZ, maxZ } = this.bounds;
    this.plan.style.aspectRatio = `${maxX - minX} / ${maxZ - minZ}`;
    this.plan.style.backgroundImage = room.map ? `url("${room.map.url}")` : '';
    this.plan.classList.toggle('drawn', !room.map);
    this.outlines.replaceChildren(...(room.map ? [] : room.entities
      .filter(entity => entity.kind === 'static' && entity.size.height > FLOOR_THICKNESS)
      .map(entity => {
        const outline = this.element('span', 'room-map-outline', this.outlines, false);
        outline.style.left = percent(this.across(entity.position.x - entity.size.width / 2));
        outline.style.top = percent(this.down(entity.position.z - entity.size.depth / 2));
        outline.style.width = percent(entity.size.width / (maxX - minX));
        outline.style.height = percent(entity.size.depth / (maxZ - minZ));
        return outline;
      })));
    const icons = [
      ...room.landmarks.map(mark => ({ id: mark.id, label: mark.label, x: mark.x, z: mark.z })),
      ...room.entities.filter(entity => entity.kind === 'movable')
        .map(entity => ({ id: entity.id, label: entity.label, x: entity.position.x, z: entity.position.z })),
    ];
    this.marks.replaceChildren(...icons.map(icon => {
      const mark = this.element('span', 'room-map-icon', this.marks, false);
      mark.dataset.testid = `${this.name}-icon-${icon.id}`;
      mark.title = capitalised(icon.label);
      mark.textContent = ICONS[icon.label.toLowerCase()] ?? PIN;
      this.place(mark, icon);
      return mark;
    }));
  }

  /** Draws each player who is here as a dot, with an arrow the way they face. */
  showPlayers(participants: Record<Role, PresenceState>, you: Role | null): void {
    this.people.replaceChildren(...(Object.entries(participants) as [Role, PresenceState][])
      .filter(([, presence]) => (presence.tracking_status === 'tracked' || presence.tracking_status === 'stale')
        && presence.position !== null && presence.heading !== null)
      .map(([role, presence]) => {
        const dot = this.element('span', `room-map-dot ${role === 'mobile_master' ? 'phone' : 'headset'}`, this.people, false);
        dot.dataset.testid = `${this.name}-dot-${role}`;
        dot.dataset.you = String(role === you);
        dot.title = role === you ? 'You' : role === 'mobile_master' ? 'Phone' : 'Headset';
        // A player off the map is kept at its edge, marked, so they never disappear.
        const across = this.across(presence.position!.x);
        const down = this.down(presence.position!.z);
        const clamp = (fraction: number) => Math.min(1, Math.max(0, fraction));
        dot.dataset.offMap = String(across !== clamp(across) || down !== clamp(down));
        dot.style.left = percent(clamp(across));
        dot.style.top = percent(clamp(down));
        // Facing -z is up the map; a heading turns to the left, which is anticlockwise on screen.
        this.element('span', 'room-map-arrow', dot, false).style.transform = `rotate(${(-presence.heading! * 180 / Math.PI).toFixed(1)}deg)`;
        return dot;
      }));
  }

  private place(element: HTMLElement, spot: Spot): void {
    element.style.left = percent(this.across(spot.x));
    element.style.top = percent(this.down(spot.z));
  }

  private across(x: number): number { return (x - this.bounds.minX) / (this.bounds.maxX - this.bounds.minX); }
  private down(z: number): number { return (z - this.bounds.minZ) / (this.bounds.maxZ - this.bounds.minZ); }

  /** Press to pick a spot, drag to pick the way to face, let go to choose. */
  private listen(): void {
    let pressed: { pointerId: number; x: number; y: number } | null = null;
    this.plan.addEventListener('pointerdown', event => {
      if (!this.events.pick || !this.root.classList.contains('picking')) return;
      pressed = { pointerId: event.pointerId, x: event.clientX, y: event.clientY };
      this.plan.setPointerCapture(event.pointerId);
      event.preventDefault();
    });
    this.plan.addEventListener('pointerup', event => {
      if (!pressed || pressed.pointerId !== event.pointerId) return;
      const box = this.plan.getBoundingClientRect();
      const { minX, maxX, minZ, maxZ } = this.bounds;
      const spot = {
        x: minX + ((pressed.x - box.left) / box.width) * (maxX - minX),
        z: minZ + ((pressed.y - box.top) / box.height) * (maxZ - minZ),
      };
      const dx = event.clientX - pressed.x;
      const dy = event.clientY - pressed.y;
      pressed = null;
      // Right is +x and down is +z; facing -z is heading 0.
      this.events.pick?.(spot, Math.hypot(dx, dy) < DRAG_PIXELS ? null : Math.atan2(-dx, -dy));
    });
    this.plan.addEventListener('pointercancel', () => { pressed = null; });
  }

  private layer(className: string, parent: HTMLElement = this.root): HTMLElement {
    return this.element('div', className, parent);
  }

  private element(tag: string, className: string, parent: HTMLElement, append = true): HTMLElement {
    const element = document.createElement(tag);
    element.className = className;
    if (append) parent.append(element);
    return element;
  }
}

/** The floor's extent, or every entity's, for a room without a map image. */
function outlineBounds(room: Room): Bounds {
  const floors = room.entities.filter(entity => entity.kind === 'static' && entity.size.height <= FLOOR_THICKNESS);
  const shapes = floors.length ? floors : room.entities;
  if (!shapes.length) return { minX: -2, maxX: 2, minZ: -2, maxZ: 2 };
  return {
    minX: Math.min(...shapes.map(e => e.position.x - e.size.width / 2)),
    maxX: Math.max(...shapes.map(e => e.position.x + e.size.width / 2)),
    minZ: Math.min(...shapes.map(e => e.position.z - e.size.depth / 2)),
    maxZ: Math.max(...shapes.map(e => e.position.z + e.size.depth / 2)),
  };
}
