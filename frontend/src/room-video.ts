/**
 * Room video (#136): record or choose a video of the room and upload it in chunks.
 *
 * The free Cloudflare tunnel refuses requests over 100 MB, so the server names a chunk size and the
 * page sends the video piece by piece. A chunk whose connection drops is sent again; the server
 * writes each chunk at its own place, so a repeat does no harm. Finishing is asked again the same
 * way: if its answer was lost, the server answers with the capture it already saved.
 */
import { errorMessage } from './api';
import { element } from './dom';

export interface VideoCaptureSummary {
  id: string;
  kind: 'video';
  created_at: string;
  instructions: string;
  original_filename: string;
  size_bytes: number;
  video: { seconds: number; width: number; height: number; frames_per_second: number; codec: string };
}

interface StartedUpload { id: string; chunk_bytes: number; chunks: number }

// Tries for each chunk and for finishing, and the wait before each retry grows by this much.
const TRIES = 4;
const RETRY_STEP_MS = 500;

/** A size as the server words it: KB under a megabyte, MB above. */
export function sizeText(bytes: number): string {
  return bytes < 1024 ** 2
    ? `${Math.round(bytes / 1024).toLocaleString('en-GB')} KB`
    : `${Math.round(bytes / 1024 ** 2).toLocaleString('en-GB')} MB`;
}

export function durationText(seconds: number): string {
  const whole = Math.round(seconds);
  const minutes = Math.floor(whole / 60);
  return minutes ? `${minutes} min ${whole % 60} s` : `${whole} s`;
}

// Phones name the type of what they record; some browsers leave a picked file's type blank.
const TYPES_BY_EXTENSION: Record<string, string> = { mov: 'video/quicktime', mp4: 'video/mp4' };

class Refused extends Error {}

export function videoType(file: File): string {
  return file.type || TYPES_BY_EXTENSION[file.name.split('.').pop()?.toLowerCase() ?? ''] || '';
}

/**
 * Makes the request, again after a dropped connection or a server error, and returns the answer.
 * A refusal (4xx) is final: asking again would not change it.
 */
async function withRetries(request: () => Promise<Response>, failure: string): Promise<Response> {
  for (let attempt = 1; ; attempt += 1) {
    try {
      const response = await request();
      if (response.ok) return response;
      if (response.status < 500) throw new Refused(await errorMessage(response, failure));
    } catch (error) {
      if (error instanceof Refused) throw error;
    }
    if (attempt === TRIES) throw new Error('The connection kept dropping. Check it and upload the video again.');
    await new Promise(resolve => setTimeout(resolve, RETRY_STEP_MS * attempt));
  }
}

/** Uploads `file` in the server's chunks and returns the saved capture; `progress` gets 0 to 1. */
export async function uploadVideo(
  file: File, instructions: string, progress: (done: number) => void,
): Promise<VideoCaptureSummary> {
  const started = await fetch('/api/videos', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ filename: file.name, size_bytes: file.size, media_type: videoType(file) }),
  });
  if (!started.ok) throw new Refused(await errorMessage(started, 'The video could not be started'));
  const upload = await started.json() as StartedUpload;
  for (let number = 0; number < upload.chunks; number += 1) {
    const start = number * upload.chunk_bytes;
    const chunk = file.slice(start, start + upload.chunk_bytes);
    await withRetries(
      () => fetch(`/api/videos/${upload.id}/chunks/${number}`, { method: 'PUT', body: chunk }),
      'The video could not be sent',
    );
    progress((number + 1) / upload.chunks);
  }
  const completed = await withRetries(() => fetch(`/api/videos/${upload.id}/complete`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ instructions }),
  }), 'The video could not be saved');
  return await completed.json() as VideoCaptureSummary;
}

export class RoomVideo {
  private file: File | null = null;
  private uploading = false;
  private readonly selected = element('video-selected');
  private readonly instructions = element<HTMLTextAreaElement>('video-instructions');
  private readonly uploadButton = element<HTMLButtonElement>('upload-video');
  private readonly bar = element<HTMLProgressElement>('video-progress');
  private readonly status = element('video-status');
  private readonly error = element('video-error');
  private readonly saved = element<HTMLUListElement>('saved-videos');

  constructor() {
    for (const id of ['video-camera', 'video-input']) {
      const input = element<HTMLInputElement>(id);
      input.addEventListener('change', () => {
        const [file] = Array.from(input.files ?? []);
        input.value = '';
        if (file) this.choose(file);
      });
    }
    this.uploadButton.addEventListener('click', () => { void this.submit(); });
  }

  showSaved(videos: VideoCaptureSummary[]): void {
    this.saved.replaceChildren(...videos.map(capture => {
      const item = document.createElement('li');
      const { seconds, width, height } = capture.video;
      item.textContent = `${capture.original_filename} · ${durationText(seconds)} · ${width} × ${height}`;
      const when = document.createElement('span');
      when.className = 'hint';
      when.textContent = ` Saved ${new Date(capture.created_at).toLocaleString()}`;
      item.append(when);
      return item;
    }));
  }

  private choose(file: File): void {
    this.file = file;
    this.selected.textContent = `${file.name} · ${sizeText(file.size)}`;
    this.selected.hidden = false;
    this.showLength(file);
    this.error.hidden = true;
    this.status.textContent = '';
    this.render();
  }

  /** Adds the video's length once the browser has read it; a file it cannot play keeps the size. */
  private showLength(file: File): void {
    const probe = document.createElement('video');
    probe.preload = 'metadata';
    const url = URL.createObjectURL(file);
    const done = () => URL.revokeObjectURL(url);
    probe.addEventListener('loadedmetadata', () => {
      done();
      if (this.file === file && Number.isFinite(probe.duration)) {
        this.selected.textContent = `${file.name} · ${sizeText(file.size)} · ${durationText(probe.duration)}`;
      }
    }, { once: true });
    probe.addEventListener('error', done, { once: true });
    probe.src = url;
  }

  private render(): void {
    this.uploadButton.disabled = this.uploading || this.file === null;
  }

  private async submit(): Promise<void> {
    if (!this.file) return;
    this.uploading = true;
    this.render();
    this.error.hidden = true;
    this.bar.value = 0;
    this.bar.hidden = false;
    this.status.textContent = 'Uploading…';
    try {
      const capture = await uploadVideo(this.file, this.instructions.value, done => {
        this.bar.value = done;
        this.status.textContent = done < 1 ? `Uploading… ${Math.round(done * 100)}%` : 'Checking the video…';
      });
      this.status.textContent = `Saved ${capture.original_filename}.`;
      this.file = null;
      this.selected.hidden = true;
      this.instructions.value = '';
      await this.refresh();
    } catch (error) {
      this.status.textContent = '';
      this.error.textContent = error instanceof Error && error.message
        ? error.message : 'The video could not be sent. Check the connection and try again.';
      this.error.hidden = false;
    } finally {
      this.uploading = false;
      this.render();
    }
  }

  async refresh(): Promise<void> {
    const response = await fetch('/api/captures');
    if (!response.ok) return;
    const { captures } = await response.json() as { captures: { kind: string }[] };
    this.showSaved(captures.filter((c): c is VideoCaptureSummary => c.kind === 'video'));
  }
}
