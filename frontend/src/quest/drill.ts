/**
 * Preparing and running a drill from the headset (#234, part of #221). The commander chooses a
 * room object by touching it, in the dollhouse or at life size; the server finds or makes a fire
 * for it; then Start and Stop run it. What a touch is on, and what the menu says, live here.
 */
import type { SessionHazard } from '../hazard-playback';
import type { Position, RoomEntity } from '../protocol';

/** The drill as the headset is told it: on which object, and how far along. */
export interface DrillState {
  entity: string;
  hazard: string;
  state: 'preparing' | 'ready' | 'failed';
  job: string | null;
  hazard_id: string | null;
  error: string | null;
}

/** A fingertip this far outside an object's box (room metres) still touches it. */
export const TOUCH_MARGIN = 0.05;

/** What isn't an object to set on fire: the floor, the walls. */
const SURFACES = /^(floor|wall|ceiling)/;

/**
 * The room object whose box holds `point` (room metres), give or take `margin`; the smallest when
 * several do, so a lamp on a desk is the lamp. Null on nothing, or on the floor and walls.
 */
export function objectAt(entities: readonly RoomEntity[], point: Position, margin = TOUCH_MARGIN): RoomEntity | null {
  let best: RoomEntity | null = null;
  let smallest = Infinity;
  for (const entity of entities) {
    if (SURFACES.test(entity.id)) continue;
    const { position, rotation, size } = entity;
    // The point in the object's own frame: turned back by its yaw about its centre.
    const yaw = 2 * Math.atan2(rotation.y, rotation.w);
    const dx = point.x - position.x;
    const dz = point.z - position.z;
    const cosine = Math.cos(-yaw);
    const sine = Math.sin(-yaw);
    const x = cosine * dx + sine * dz;
    const z = -sine * dx + cosine * dz;
    const y = point.y - position.y;
    const inside = Math.abs(x) <= size.width / 2 + margin && Math.abs(z) <= size.depth / 2 + margin &&
      y >= -margin && y <= size.height + margin;
    const volume = size.width * size.height * size.depth;
    if (inside && volume < smallest) [best, smallest] = [entity, volume];
  }
  return best;
}

/** How a fire job's steps read, from the job's state. */
const STEPS: Record<string, string> = {
  queued: 'starting',
  image_ready: 'picture done, making the video',
  video_ready: 'video done, making it 3D',
};

/** The Drill page's line: what to do next, the plan, or how far along it is. */
export function drillLine(
  drill: DrillState | null,
  entities: readonly RoomEntity[],
  hazards: readonly SessionHazard[],
  picking: boolean,
  jobState: string | null,
): string {
  if (picking) return 'Touch an object to set it on fire';
  if (!drill) return 'Choose an object for the drill';
  const name = entities.find(entity => entity.id === drill.entity)?.label ?? drill.entity.replace(/_/g, ' ');
  const plan = `${name} ${drill.hazard}`;
  if (drill.state === 'failed') return `Couldn't prepare: ${drill.error ?? 'try again'}`;
  if (drill.state === 'preparing') return `${plan} · ${STEPS[jobState ?? 'queued'] ?? 'making it'}…`;
  const playing = hazards.find(hazard => hazard.id === drill.hazard_id)?.playing ?? false;
  return playing ? `${plan} · running, Stop to end` : `${plan} · ready, pinch Start`;
}

/** Whether the drill's fire is playing now. */
export function drillPlaying(drill: DrillState | null, hazards: readonly SessionHazard[]): boolean {
  return !!drill?.hazard_id && (hazards.find(hazard => hazard.id === drill.hazard_id)?.playing ?? false);
}
