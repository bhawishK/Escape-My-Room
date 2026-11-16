/**
 * The phone makes a piece of furniture from a photo (#187): a photo of something the resident
 * likes, sent to the server, made into a 3D piece and added to the catalogue for the designer.
 */
import { errorMessage } from './api';
import { element } from './dom';
import type { FurnitureJob } from './protocol';

/** How often the job is asked about, in milliseconds. */
const POLL_MS = 1000;

export function setUpPhotoPiece(): void {
  const form = element<HTMLFormElement>('photo-piece');
  const file = element<HTMLInputElement>('photo-piece-file');
  const description = element<HTMLInputElement>('photo-piece-description');
  const make = element<HTMLButtonElement>('photo-piece-make');
  const cancel = element<HTMLButtonElement>('photo-piece-cancel');
  const status = element('photo-piece-status');
  let making: string | null = null;

  const show = (job: FurnitureJob): void => {
    making = job.state === 'queued' || job.state === 'image_ready' ? job.id : null;
    make.disabled = making !== null;
    cancel.hidden = making === null;
    if (making) status.textContent = 'Making it into a 3D piece, which can take a few minutes…';
    else if (job.state === 'ready' && job.item) status.textContent = `${job.item.name} is ready. The designer can place it now.`;
    else if (job.state === 'failed') status.textContent = job.error ?? 'The piece could not be made.';
    else if (job.state === 'cancelled') status.textContent = 'Stopped. Nothing was added.';
  };

  const follow = async (id: string): Promise<void> => {
    while (making === id) {
      await new Promise(resolve => setTimeout(resolve, POLL_MS));
      if (making !== id) return;
      try {
        const response = await fetch(`/api/furniture/jobs/${id}`);
        if (response.ok) show(await response.json() as FurnitureJob);
        // Jobs live in the server's memory: after a restart this one is gone.
        else if (response.status === 404) {
          show({ id, state: 'failed', error: 'The server lost this piece, perhaps because it restarted. Try again.', image_url: null, item: null });
        }
      } catch {
        // A dropped request is asked again next time.
      }
    }
  };

  form.addEventListener('submit', event => {
    event.preventDefault();
    const photo = file.files?.[0];
    if (!photo || making) {
      if (!photo) status.textContent = 'Take or choose a photo first.';
      return;
    }
    make.disabled = true;
    const body = new FormData();
    body.append('image', photo);
    body.append('description', description.value.trim());
    void (async () => {
      try {
        const response = await fetch('/api/furniture/jobs/photo', { method: 'POST', body }).catch(() => null);
        if (!response?.ok) {
          make.disabled = false;
          status.textContent = response
            ? await errorMessage(response, 'The photo could not be sent.')
            : 'The server could not be reached. Try again.';
          return;
        }
        const job = await response.json() as FurnitureJob;
        show(job);
        void follow(job.id);
      } catch {
        // An answer that wasn't a job: let the person try again.
        make.disabled = false;
        status.textContent = 'The server sent something unexpected. Try again.';
      }
    })();
  });

  cancel.addEventListener('click', () => {
    const id = making;
    if (!id) return;
    void fetch(`/api/furniture/jobs/${id}/cancel`, { method: 'POST' })
      .then(response => response.ok ? response.json() as Promise<FurnitureJob> : null)
      .then(job => { if (job) show(job); });
  });
}
