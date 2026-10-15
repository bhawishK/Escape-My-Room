/** Room photos: choose or take photos, save them as one capture, and show the latest capture. */
import { element } from './dom';

type MediaType = 'image/jpeg' | 'image/png';

export interface CaptureImage {
  id: string;
  original_filename: string;
  media_type: MediaType;
  size_bytes: number;
  sha256: string;
  width: number;
  height: number;
  exif_orientation: number;
  processed: {
    source: 'original' | 'exif_orientation_applied';
    media_type: MediaType;
    width: number;
    height: number;
  };
  original_url: string;
  processed_url: string;
}

export interface CaptureSummary {
  id: string;
  created_at: string;
  instructions: string;
  overview_image_id: string;
  images: CaptureImage[];
}

interface PendingPhoto { file: File; url: string }

/** The server's refusal message, or a generic one when the response has none. */
async function errorMessage(response: Response): Promise<string> {
  try {
    const body = await response.json() as { detail?: unknown };
    if (typeof body.detail === 'string') return body.detail;
  } catch {
    // Fall through to a generic message.
  }
  return `The photos could not be saved (HTTP ${response.status}). Try again.`;
}

/** One photo in a list: picture, name, an overview choice, and any extra controls. */
function photoTile(src: string, name: string, overview: HTMLInputElement, ...extra: HTMLElement[]) {
  const item = document.createElement('li');
  const image = document.createElement('img');
  image.src = src;
  image.alt = name;
  const caption = document.createElement('span');
  caption.className = 'photo-name';
  caption.textContent = name;
  const label = document.createElement('label');
  label.append(overview, 'Overview');
  item.append(image, caption, label, ...extra);
  return item;
}

function overviewChoice(group: string, name: string, checked: boolean): HTMLInputElement {
  const input = document.createElement('input');
  input.type = 'radio';
  input.name = group;
  input.checked = checked;
  input.setAttribute('aria-label', `Use ${name} as overview`);
  return input;
}

export class RoomPhotos {
  private pending: PendingPhoto[] = [];
  private overview = 0;
  private saving = false;
  // Bumped whenever a capture is shown, so a slower earlier request cannot replace a newer one.
  private shown = 0;
  private readonly pendingList = element<HTMLUListElement>('pending-photos');
  private readonly instructions = element<HTMLTextAreaElement>('instructions');
  private readonly save = element<HTMLButtonElement>('save-capture');
  private readonly error = element('capture-error');
  private readonly overviewStatus = element('overview-status');

  constructor() {
    for (const id of ['camera-input', 'photo-input']) {
      const input = element<HTMLInputElement>(id);
      input.addEventListener('change', () => {
        this.add(Array.from(input.files ?? []));
        input.value = '';
      });
    }
    this.save.addEventListener('click', () => { void this.submit(); });
  }

  async showLatest(): Promise<void> {
    const request = this.shown;
    const response = await fetch('/api/captures');
    if (request !== this.shown) return;
    if (!response.ok) return this.showError(await errorMessage(response));
    const { captures } = await response.json() as { captures: CaptureSummary[] };
    if (request === this.shown && captures.length > 0) this.showSaved(captures[0]);
  }

  private add(files: File[]): void {
    for (const file of files) this.pending.push({ file, url: URL.createObjectURL(file) });
    this.renderPending();
  }

  private remove(index: number): void {
    const [removed] = this.pending.splice(index, 1);
    URL.revokeObjectURL(removed.url);
    if (this.overview >= this.pending.length || this.overview === index) this.overview = 0;
    else if (index < this.overview) this.overview -= 1;
    this.renderPending();
  }

  private renderPending(): void {
    this.pendingList.replaceChildren(...this.pending.map((photo, index) => {
      const name = photo.file.name;
      const choice = overviewChoice('pending-overview', name, index === this.overview);
      choice.addEventListener('change', () => { this.overview = index; });
      const remove = document.createElement('button');
      remove.className = 'secondary';
      remove.textContent = 'Remove';
      remove.setAttribute('aria-label', `Remove ${name}`);
      remove.addEventListener('click', () => this.remove(index));
      return photoTile(photo.url, name, choice, remove);
    }));
    this.save.disabled = this.saving || this.pending.length === 0;
  }

  private async submit(): Promise<void> {
    this.saving = true;
    this.save.disabled = true;
    this.error.hidden = true;
    const form = new FormData();
    for (const photo of this.pending) form.append('images', photo.file, photo.file.name);
    form.append('overview', String(this.overview));
    form.append('instructions', this.instructions.value);
    try {
      const response = await fetch('/api/captures', { method: 'POST', body: form });
      if (!response.ok) return this.showError(await errorMessage(response));
      this.showSaved(await response.json() as CaptureSummary);
      this.overviewStatus.textContent = '';
      for (const photo of this.pending) URL.revokeObjectURL(photo.url);
      this.pending = [];
      this.overview = 0;
      this.instructions.value = '';
    } catch {
      this.showError('The photos could not be sent. Check the connection and try again.');
    } finally {
      this.saving = false;
      this.renderPending();
    }
  }

  private showSaved(capture: CaptureSummary): void {
    this.shown += 1;
    element('saved-capture').hidden = false;
    element('saved-time').textContent = `Saved ${new Date(capture.created_at).toLocaleString()}`;
    element('saved-instructions').textContent = capture.instructions || 'No room instructions.';
    element('saved-photos').replaceChildren(...capture.images.map(photo => {
      const name = photo.original_filename;
      const choice = overviewChoice('saved-overview', name, photo.id === capture.overview_image_id);
      choice.addEventListener('change', () => { void this.chooseOverview(capture, photo); });
      return photoTile(photo.processed_url, name, choice);
    }));
  }

  private async chooseOverview(capture: CaptureSummary, photo: CaptureImage): Promise<void> {
    this.overviewStatus.textContent = 'Saving overview…';
    this.error.hidden = true;
    try {
      const response = await fetch(`/api/captures/${capture.id}/overview`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ image_id: photo.id }),
      });
      if (!response.ok) throw new Error(await errorMessage(response));
      this.showSaved(await response.json() as CaptureSummary);
      this.overviewStatus.textContent = `Overview saved: ${photo.original_filename}`;
    } catch (error) {
      // Show the overview that is actually saved, then explain why the change failed.
      this.showSaved(capture);
      this.overviewStatus.textContent = '';
      this.showError(error instanceof Error ? error.message : 'The overview could not be saved.');
    }
  }

  private showError(message: string): void {
    this.error.textContent = message;
    this.error.hidden = false;
  }
}
