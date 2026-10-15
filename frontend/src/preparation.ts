/** Room preparation: start a job for the saved capture and follow its stages to a candidate. */
import type { CaptureSummary } from './capture';
import { errorMessage } from './api';
import { element } from './dom';

type StageName = 'scene_understanding' | 'geometry' | 'stabilization' | 'export';

interface Stage {
  name: StageName;
  status: 'pending' | 'running' | 'done' | 'failed';
  elapsed_seconds: number | null;
}

interface CandidateEntity {
  id: string;
  label: string;
  kind: 'static' | 'movable';
  width: number;
  height: number;
  depth: number;
}

type ErrorKind =
  | 'configuration' | 'resource' | 'provider' | 'inference' | 'validation'
  | 'fixture' | 'worker' | 'interrupted';

/** What the browser asks to prepare. */
interface JobRequest { capture_id: string; overview_image_id: string }

export interface PreparationJob {
  id: string;
  state: 'queued' | 'running' | 'awaiting_review' | 'failed';
  // Since submission, including time queued; up to now while the job is active.
  elapsed_seconds: number | null;
  input: JobRequest;
  stages: Stage[];
  error: { stage: StageName | null; kind: ErrorKind; message: string } | null;
  candidate: { label: string; entities: CandidateEntity[] } | null;
}

const isActive = (job: PreparationJob) => job.state === 'queued' || job.state === 'running';

const STAGE_NAMES: Record<StageName, string> = {
  scene_understanding: 'Scene understanding',
  geometry: 'Geometry',
  stabilization: 'Stabilization',
  export: 'Export',
};
const POLL_MS = 500;

function stageText(stage: Stage): string {
  const seconds = stage.elapsed_seconds?.toFixed(1);
  switch (stage.status) {
    case 'done': return `${STAGE_NAMES[stage.name]} · done in ${seconds} s`;
    case 'failed': return `${STAGE_NAMES[stage.name]} · failed after ${seconds} s`;
    case 'running': return `${STAGE_NAMES[stage.name]} · running for ${seconds ?? '0.0'} s`;
    case 'pending': return `${STAGE_NAMES[stage.name]} · not started`;
  }
}

function stateText(job: PreparationJob): string {
  switch (job.state) {
    case 'queued': return 'Queued';
    case 'running': {
      const stage = job.stages.find(item => item.status === 'running');
      return stage ? `Running · ${STAGE_NAMES[stage.name]}` : 'Running';
    }
    case 'awaiting_review': return 'Awaiting review';
    case 'failed': return 'Failed';
  }
}

export class RoomPreparation {
  private capture: CaptureSummary | null = null;
  // Bumped whenever another capture or job is shown, so stale polls stop.
  private generation = 0;
  private readonly button = element<HTMLButtonElement>('prepare-room');
  private readonly state = element('preparation-state');
  private readonly error = element('preparation-error');

  constructor() {
    this.button.addEventListener('click', () => { void this.submit(); });
  }

  /** Show the latest job for this capture, if any. */
  async showCapture(capture: CaptureSummary): Promise<void> {
    this.capture = capture;
    const generation = ++this.generation;
    this.clear();
    const response = await fetch('/api/preparations');
    if (!response.ok || generation !== this.generation) return;
    const { jobs } = await response.json() as { jobs: PreparationJob[] };
    const latest = jobs.find(job => job.input.capture_id === capture.id);
    if (latest) this.follow(latest, generation);
  }

  private async submit(): Promise<void> {
    if (!this.capture) return;
    const generation = ++this.generation;
    this.clear();
    this.button.disabled = true;
    try {
      const request: JobRequest = {
        capture_id: this.capture.id,
        overview_image_id: this.capture.overview_image_id,
      };
      const response = await fetch('/api/preparations', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(request),
      });
      if (!response.ok) throw new Error(await errorMessage(response, 'Room preparation could not start'));
      this.follow(await response.json() as PreparationJob, generation);
    } catch (error) {
      this.button.disabled = false;
      this.showError(error instanceof Error ? error.message : 'Room preparation could not start.');
    }
  }

  private follow(job: PreparationJob, generation: number): void {
    if (generation !== this.generation) return;
    this.show(job);
    if (!isActive(job)) return;
    window.setTimeout(() => {
      void fetch(`/api/preparations/${job.id}`)
        .then(async response => {
          if (!response.ok) throw new Error(await errorMessage(response, 'Preparation progress is unavailable'));
          this.follow(await response.json() as PreparationJob, generation);
        })
        .catch(error => {
          if (generation !== this.generation) return;
          this.button.disabled = false;
          this.showError(error instanceof Error ? error.message : 'Preparation progress is unavailable.');
        });
    }, POLL_MS);
  }

  private show(job: PreparationJob): void {
    this.button.disabled = isActive(job);
    this.state.hidden = false;
    this.state.textContent = stateText(job);
    const elapsed = element('preparation-elapsed');
    elapsed.hidden = job.elapsed_seconds === null;
    elapsed.textContent = `Total ${job.elapsed_seconds?.toFixed(1)} s`;
    element('preparation-stages').replaceChildren(...job.stages.map(stage => {
      const item = document.createElement('li');
      item.dataset.status = stage.status;
      item.textContent = stageText(stage);
      return item;
    }));
    if (job.error) {
      const where = job.error.stage ? `${STAGE_NAMES[job.error.stage]} failed: ` : '';
      this.showError(`${where}${job.error.message}`);
    } else {
      this.error.hidden = true;
    }
    this.showCandidate(job);
  }

  private showCandidate(job: PreparationJob): void {
    const box = element('candidate');
    box.hidden = job.candidate === null;
    if (!job.candidate) return;
    element('candidate-label').textContent = job.candidate.label;
    const overview = this.capture?.images.find(image => image.id === job.input.overview_image_id);
    const picture = element<HTMLImageElement>('candidate-overview');
    picture.hidden = !overview;
    if (overview) {
      picture.src = overview.processed_url;
      picture.alt = `Overview: ${overview.original_filename}`;
    }
    element('candidate-objects').replaceChildren(...job.candidate.entities.map(entity => {
      const item = document.createElement('li');
      const size = [entity.width, entity.height, entity.depth].map(value => value.toFixed(2)).join(' × ');
      item.textContent = `${entity.label} · ${entity.kind} · ${size} m`;
      return item;
    }));
  }

  private clear(): void {
    this.state.hidden = true;
    this.error.hidden = true;
    element('preparation-elapsed').hidden = true;
    element('preparation-stages').replaceChildren();
    element('candidate').hidden = true;
    this.button.disabled = false;
  }

  private showError(message: string): void {
    this.error.textContent = message;
    this.error.hidden = false;
  }
}
