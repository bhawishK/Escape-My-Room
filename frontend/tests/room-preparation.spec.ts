import { expect, test, type Page } from '@playwright/test';
import { fileURLToPath } from 'node:url';

const photo = (name: string) => fileURLToPath(new URL(`./fixtures/photos/${name}`, import.meta.url));

async function saveCapture(page: Page, origin = '') {
  await page.goto(`${origin}/`);
  const photos = page.getByRole('region', { name: 'Room photos' });
  await photos.getByLabel('Choose photos').setInputFiles([photo('overview.png'), photo('desk.jpg')]);
  await photos.getByRole('button', { name: 'Save photos' }).click();
  await expect(photos.getByTestId('saved-capture').getByRole('img')).toHaveCount(2);
  return photos;
}

test('a saved capture is prepared into a labelled fixture candidate', async ({ page }) => {
  const photos = await saveCapture(page);
  await photos.getByRole('button', { name: 'Prepare room' }).click();
  const preparation = photos.getByRole('region', { name: 'Room preparation' });
  await expect(preparation.getByTestId('preparation-state')).toHaveText(/^Running · /);
  const stageList = preparation.getByRole('list', { name: 'Preparation stages' });
  await expect(stageList.getByText(/ · running for \d+\.\d s$/)).toBeVisible();
  await expect(preparation.getByTestId('preparation-state')).toHaveText('Awaiting review', { timeout: 10_000 });
  await expect(preparation.getByTestId('preparation-elapsed')).toHaveText(/^Total \d+\.\d s$/);

  const stages = preparation.getByRole('list', { name: 'Preparation stages' }).getByRole('listitem');
  await expect(stages).toHaveText([
    /^Scene understanding · done in \d+\.\d s$/,
    /^Geometry · done in \d+\.\d s$/,
    /^Stabilization · done in \d+\.\d s$/,
    /^Export · done in \d+\.\d s$/,
  ]);
  const candidate = preparation.getByTestId('candidate');
  await expect(candidate.getByTestId('candidate-label')).toHaveText('Fixture output, not AI inference');
  await expect(candidate.getByRole('img', { name: 'Overview: overview.png' })).toBeVisible();
  await expect(candidate.getByRole('list', { name: 'Candidate objects' }).getByRole('listitem')).toHaveText([
    'Floor · static · 3.00 × 0.02 × 3.00 m',
    'Table · static · 1.00 × 0.75 × 0.60 m',
    'Mug · movable · 0.09 × 0.10 × 0.08 m',
    'Book · movable · 0.20 × 0.04 × 0.15 m',
  ]);

  await page.reload();
  const reloaded = page.getByRole('region', { name: 'Room preparation' });
  await expect(reloaded.getByTestId('preparation-state')).toHaveText('Awaiting review');
  await expect(reloaded.getByTestId('candidate-label')).toHaveText('Fixture output, not AI inference');
});

test('a failed preparation stage is shown with its reason', async ({ page }) => {
  const photos = await saveCapture(page, 'http://127.0.0.1:8773');
  await photos.getByRole('button', { name: 'Prepare room' }).click();
  const preparation = photos.getByRole('region', { name: 'Room preparation' });
  await expect(preparation.getByTestId('preparation-state')).toHaveText('Failed', { timeout: 10_000 });
  await expect(preparation.getByTestId('preparation-error')).toHaveText(
    'Geometry failed: The fixture worker was configured to fail at the geometry stage.',
  );
  await expect(preparation.getByRole('list', { name: 'Preparation stages' }).getByRole('listitem')).toHaveText([
    /^Scene understanding · done in \d+\.\d s$/,
    /^Geometry · failed after \d+\.\d s$/,
    'Stabilization · not started',
    'Export · not started',
  ]);
  await expect(preparation.getByTestId('candidate')).toBeHidden();
});

test('a job waits as queued while another is being prepared', async ({ page }) => {
  const photos = await saveCapture(page);
  const { captures } = await (await page.request.get('/api/captures')).json();
  const capture = captures[0];
  const first = await page.request.post('/api/preparations', {
    data: { capture_id: capture.id, overview_image_id: capture.overview_image_id },
  });
  expect(first.status()).toBe(202);
  await photos.getByRole('button', { name: 'Prepare room' }).click();
  const preparation = photos.getByRole('region', { name: 'Room preparation' });
  await expect(preparation.getByTestId('preparation-state')).toHaveText('Queued');
  await expect(preparation.getByRole('button', { name: 'Prepare room' })).toBeDisabled();
  await expect(preparation.getByTestId('preparation-state')).toHaveText('Awaiting review', { timeout: 15_000 });
});
