/**
 * Preparing and running a drill from the headset (#234, part of #221). The commander chooses a
 * room object from the Drill menu, as on the headset page's Drill card; the server finds or makes
 * a fire for it; then Start and Stop run it. Which objects are offered, and what the menu says,
 * live here.
 */
import type { SessionHazard } from '../hazard-playback';
import type { RoomEntity } from '../protocol';

/** The drill as the headset is told it: on which object, and how far along. */
export interface DrillState {
  entity: string;
  hazard: string;
  state: 'preparing' | 'ready' | 'failed';
  job: string | null;
  hazard_id: string | null;
  error: string | null;
}

/** What isn't an object to set on fire: the floor, the walls. */
const SURFACES = /^(floor|wall|ceiling)/;

/** The room objects a drill can be on: all but the floor and the walls, in the room's order. */
export function drillObjects(entities: readonly RoomEntity[]): RoomEntity[] {
  return entities.filter(entity => !SURFACES.test(entity.id));
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
  chosen: string | null,
  jobState: string | null,
): string {
  const label = (id: string) => entities.find(entity => entity.id === id)?.label ?? id.replace(/_/g, ' ');
  // Another object chosen than the drill's: Prepare would make a drill on it instead.
  if (chosen && chosen !== drill?.entity) return `${label(chosen)} · pinch Prepare`;
  if (!drill) return 'Choose an object, then pinch Prepare';
  const name = label(drill.entity);
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
