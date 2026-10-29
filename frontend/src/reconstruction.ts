/**
 * Room reconstruction (#137): start a reconstruction job for a saved room video and follow its
 * stages, with splat training's steps as they happen, to what it made for review.
 */
import { errorMessage } from './api';
import { element } from './dom';
import type { LiveRoom } from './live-room';
import type { VideoCaptureSummary } from './room-video';

type StageName = 'frames' | 'colmap' | 'level' | 'splat' | 'vps_map' | 'package';

interface Stage {
  name: StageName;
  status: 'pending' | 'running' | 'done' | 'failed';
  elapsed_seconds: number | null;
  step: number | null;
  total: number | null;
  message: string | null;
}

export interface ReconstructionJob {
  id: string;
  state: 'queued' | 'running' | 'awaiting_review' | 'failed';
  input: { capture_id: string };
  stages: Stage[];
  error: { stage: StageName | null; kind: string; message: string } | null;
  reconstruction: {
    video: string;
    frames: number;
    frames_placed: number;
    splats: number;
    psnr_db: number | null;
    memory_retried: boolean;
    map_keypoints: number;
    // Relative to the job folder.
    splat: string;
    previews: string[];
  } | null;
}

const STAGE_NAMES: Record<StageName, string> = {
  frames: 'Frames',
  colmap: 'COLMAP',
  level: 'Levelling',
  splat: 'Splat training',
  vps_map: 'Positioning map',
  package: 'Package',
};
const STATES: Record<ReconstructionJob['state'], string> = {
  queued: 'Queued',
  running: 'Running',
  awaiting_review: 'Awaiting review',
  failed: 'Failed',
};
const POLL_MS = 500;
const count = (value: number) => value.toLocaleString('en-GB');

function stageText(stage: Stage): string {
  const name = STAGE_NAMES[stage.name];
  const seconds = (stage.elapsed_seconds ?? 0).toFixed(1);
  switch (stage.status) {
    case 'done': return `${name} · done in ${seconds} s`;
    case 'failed': return `${name} · failed after ${seconds} s`;
    case 'pending': return `${name} · not started`;
    case 'running': {
      const steps = stage.step && stage.total ? ` · step ${stage.step} of ${stage.total}` : '';
      const message = stage.message ? ` · ${stage.message}` : '';
      return `${name} · running for ${seconds} s${steps}${message}`;
    }
  }
}

function summaryText(made: NonNullable<ReconstructionJob['reconstruction']>): string {
  const parts = [
    made.video,
    `${made.frames_placed} of ${made.frames} frames placed`,
    `${count(made.splats)} splats`,
    ...(made.psnr_db === null ? [] : [`PSNR ${made.psnr_db} dB`]),
    `${count(made.map_keypoints)} map keypoints`,
    ...(made.memory_retried ? ['trained again smaller after running out of GPU memory'] : []),
  ];
  return parts.join(' · ');
}

export class RoomReconstruction {
  // Bumped whenever another job is shown, so a stale poll stops.
  private generation = 0;
  private readonly panel = element('reconstruction');
  private readonly video = element('reconstruction-video');
  private readonly state = element('reconstruction-state');
  private readonly stages = element<HTMLOListElement>('reconstruction-stages');
  private readonly error = element('reconstruction-error');
  private readonly summary = element('reconstruction-summary');
  private readonly review = element('reconstruction-review');
  private readonly previews = element<HTMLUListElement>('reconstruction-previews');
  private readonly viewer = element<HTMLAnchorElement>('reconstruction-viewer');
  private readonly makeLive = element<HTMLButtonElement>('make-live');
  // The job a press of Make live builds.
  private reviewing: string | null = null;

  constructor(private readonly live: LiveRoom) {
    this.makeLive.addEventListener('click', () => {
      if (this.reviewing) void this.live.makeLive(this.reviewing, this.makeLive);
    });
  }

  /** A button that reconstructs this video. */
  button(capture: VideoCaptureSummary): HTMLButtonElement {
    const button = document.createElement('button');
    button.className = 'secondary';
    button.textContent = 'Reconstruct room';
    button.setAttribute('aria-label', `Reconstruct room from ${capture.original_filename}`);
    button.addEventListener('click', () => { void this.start(capture); });
    return button;
  }

  /** Show the latest reconstruction of any of these videos, if there is one. */
  async showLatest(videos: VideoCaptureSummary[]): Promise<void> {
    const generation = this.generation;
    const response = await fetch('/api/preparations');
    if (!response.ok || generation !== this.generation) return;
    const { jobs } = await response.json() as { jobs: ReconstructionJob[] };
    const names = new Map(videos.map(video => [video.id, video.original_filename]));
    const latest = jobs.find(job => names.has(job.input.capture_id));
    if (latest) this.follow(latest, names.get(latest.input.capture_id)!, ++this.generation);
  }

  private async start(capture: VideoCaptureSummary): Promise<void> {
    const generation = ++this.generation;
    this.panel.hidden = false;
    this.video.textContent = `From ${capture.original_filename}`;
    this.state.textContent = 'Starting…';
    this.stages.replaceChildren();
    this.summary.hidden = true;
    this.error.hidden = true;
    try {
      const response = await fetch('/api/preparations', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ capture_id: capture.id }),
      });
      if (!response.ok) throw new Error(await errorMessage(response, 'The reconstruction could not start'));
      this.follow(await response.json() as ReconstructionJob, capture.original_filename, generation);
    } catch (error) {
      this.state.textContent = '';
      this.showError(error instanceof Error ? error.message : 'The reconstruction could not start.');
    }
  }

  private follow(job: ReconstructionJob, video: string, generation: number): void {
    if (generation !== this.generation) return;
    this.panel.hidden = false;
    this.video.textContent = `From ${video}`;
    this.state.textContent = STATES[job.state];
    this.stages.replaceChildren(...job.stages.map(stage => {
      const item = document.createElement('li');
      item.textContent = stageText(stage);
      item.dataset.status = stage.status;
      return item;
    }));
    this.error.hidden = job.error === null;
    if (job.error) this.error.textContent = job.error.message;
    this.summary.hidden = job.reconstruction === null;
    if (job.reconstruction) this.summary.textContent = summaryText(job.reconstruction);
    this.showReview(job);
    if (job.state === 'queued' || job.state === 'running') {
      setTimeout(() => { void this.poll(job.id, video, generation); }, POLL_MS);
    }
  }

  /** The finished reconstruction's previews, a link to look round its splat, and Make live. */
  private showReview(job: ReconstructionJob): void {
    const finished = job.state === 'awaiting_review' ? job.reconstruction : null;
    this.review.hidden = finished === null;
    this.reviewing = finished ? job.id : null;
    if (!finished) return;
    const file = (path: string) => `/api/preparations/${job.id}/files/${path}`;
    this.previews.replaceChildren(...finished.previews.map(path => {
      const item = document.createElement('li');
      const image = document.createElement('img');
      image.src = file(path);
      image.alt = `Held-out frame and the splat's view: ${path.split('/').pop()}`;
      item.append(image);
      return item;
    }));
    this.viewer.href = `/splat.html?src=${encodeURIComponent(file(finished.splat))}`;
  }

  private async poll(id: string, video: string, generation: number): Promise<void> {
    if (generation !== this.generation) return;
    try {
      const response = await fetch(`/api/preparations/${id}`);
      if (response.ok) return this.follow(await response.json() as ReconstructionJob, video, generation);
      // A refusal, such as a job that no longer exists, will not change by asking again.
      if (response.status < 500) {
        return this.showError(await errorMessage(response, 'The reconstruction could not be followed'));
      }
    } catch {
      // Try again at the next poll; the connection may come back.
    }
    setTimeout(() => { void this.poll(id, video, generation); }, POLL_MS);
  }

  private showError(message: string): void {
    this.error.textContent = message;
    this.error.hidden = false;
  }
}
