/**
 * The live room (#138): which room both devices share, making a reviewed reconstruction live, and
 * going back to the room before. Devices see the room version change and reload by themselves.
 */
import { errorMessage } from './api';
import { element } from './dom';

export interface LiveRoomSummary {
  job_id: string | null;
  room_version: number | null;
  made_live_at: string | null;
  floor_width_m: number | null;
  floor_depth_m: number | null;
  scale_source: string | null;
  // Whether the room has its map from above (#124), and the positioning map (#133).
  overview_map: boolean;
  positioning_map: boolean;
  can_restore: boolean;
}

function liveText(live: LiveRoomSummary): string {
  if (live.room_version === null) return 'No room is loaded.';
  const parts = [`Live · room version ${live.room_version}`];
  parts.push(live.job_id ? 'a reconstructed room' : "the server's configured room");
  if (live.floor_width_m !== null && live.floor_depth_m !== null) {
    parts.push(`floor ${live.floor_width_m} × ${live.floor_depth_m} m`);
  }
  if (live.scale_source) parts.push(`scale ${live.scale_source}`);
  if (live.job_id) parts.push(live.positioning_map ? 'positioning map ready' : 'no positioning map');
  return parts.join(' · ');
}

export class LiveRoom {
  private readonly status = element('live-room');
  private readonly error = element('live-room-error');
  private readonly restore = element<HTMLButtonElement>('restore-room');

  constructor() {
    this.restore.addEventListener('click', () => { void this.change('/api/rooms/restore', this.restore); });
  }

  async refresh(): Promise<void> {
    const response = await fetch('/api/rooms/live');
    if (response.ok) this.show(await response.json() as LiveRoomSummary);
  }

  /** Builds the job's reconstruction into a room and makes it live; `button` waits meanwhile. */
  makeLive(jobId: string, button: HTMLButtonElement): Promise<void> {
    return this.change(`/api/preparations/${jobId}/activate`, button);
  }

  private async change(url: string, button: HTMLButtonElement): Promise<void> {
    button.disabled = true;
    this.error.hidden = true;
    this.status.textContent = 'Changing the room…';
    try {
      const response = await fetch(url, { method: 'POST' });
      if (!response.ok) throw new Error(await errorMessage(response, 'The room could not be changed'));
      this.show(await response.json() as LiveRoomSummary);
    } catch (error) {
      this.error.textContent = error instanceof Error ? error.message : 'The room could not be changed.';
      this.error.hidden = false;
      await this.refresh();
    } finally {
      button.disabled = false;
    }
  }

  private show(live: LiveRoomSummary): void {
    this.status.textContent = liveText(live);
    this.restore.hidden = !live.can_restore;
  }
}
