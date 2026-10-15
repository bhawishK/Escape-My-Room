import { expect, test, type Locator, type Page } from '@playwright/test';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

const photo = (name: string) => fileURLToPath(new URL(`./fixtures/photos/${name}`, import.meta.url));

async function openPhotos(page: Page) {
  await page.goto('/');
  return page.getByRole('region', { name: 'Room photos' });
}

test('saved photos, overview and instructions come back after a reload', async ({ page }) => {
  let photos = await openPhotos(page);
  await photos.getByLabel('Choose photos').setInputFiles([photo('overview.png'), photo('desk.jpg')]);
  await photos.getByRole('list', { name: 'Photos to save' }).getByLabel('Use desk.jpg as overview').check();
  await photos.getByLabel('Room instructions').fill('The key hides under the desk.');
  await photos.getByRole('button', { name: 'Save photos' }).click();
  await expect(photos.getByTestId('saved-instructions')).toHaveText('The key hides under the desk.');

  await page.reload();
  photos = page.getByRole('region', { name: 'Room photos' });
  const saved = photos.getByTestId('saved-capture');
  await expect(saved.getByTestId('saved-instructions')).toHaveText('The key hides under the desk.');
  await expect(saved.getByRole('img')).toHaveCount(2);
  await expect(saved.getByRole('img', { name: 'overview.png' })).toBeVisible();
  await expect(saved.getByRole('img', { name: 'desk.jpg' })).toBeVisible();
  await expect(saved.getByLabel('Use desk.jpg as overview')).toBeChecked();
  await expect(saved.getByLabel('Use overview.png as overview')).not.toBeChecked();
});

test('a camera photo and a library photo are saved as one capture', async ({ page }) => {
  const photos = await openPhotos(page);
  const camera = photos.getByLabel('Take photo');
  await expect(camera).toHaveAttribute('capture', 'environment');
  await camera.setInputFiles(photo('camera.jpg'));
  await photos.getByLabel('Choose photos').setInputFiles(photo('overview.png'));
  await expect(photos.getByRole('list', { name: 'Photos to save' }).getByRole('img')).toHaveCount(2);
  await expect(photos.getByRole('list', { name: 'Photos to save' }).getByLabel('Use camera.jpg as overview')).toBeChecked();
  await photos.getByRole('button', { name: 'Save photos' }).click();

  const saved = photos.getByTestId('saved-capture');
  await expect(saved.getByRole('img')).toHaveCount(2);
  await expect(saved.getByRole('img', { name: 'camera.jpg' })).toBeVisible();
  await expect(saved.getByLabel('Use camera.jpg as overview')).toBeChecked();
  await expect(photos.getByRole('list', { name: 'Photos to save' }).getByRole('img')).toHaveCount(0);
});

/**
 * Pixels of a saved photo as processing will read them. Browsers apply EXIF when displaying, but
 * processing code reads raw pixels, so the processed file must be upright with no orientation tag.
 */
async function processedPixels(page: Page, shown: Locator) {
  const file = await (await page.request.get(await shown.getAttribute('src') ?? '')).body();
  const pixels = await shown.evaluate(async (image: HTMLImageElement) => {
    const bitmap = await createImageBitmap(await (await fetch(image.src)).blob());
    const canvas = new OffscreenCanvas(bitmap.width, bitmap.height);
    const context = canvas.getContext('2d')!;
    context.drawImage(bitmap, 0, 0);
    // JPEG is lossy, so round each channel to fully off or on.
    const at = (x: number, y: number) => Array.from(context.getImageData(x, y, 1, 1).data.slice(0, 3), v => Math.round(v / 255));
    return { width: bitmap.width, height: bitmap.height, top: at(10, 5), bottom: at(10, 35) };
  });
  return { ...pixels, orientationTag: file.includes('Exif') || file.includes('eXIf') };
}

for (const sideways of [
  { name: 'sideways.jpg', case: 'a sideways phone photo' },
  { name: 'cmyk-sideways.jpg', case: 'a sideways CMYK photo' },
]) {
  test(`${sideways.case} is stored upright for processing`, async ({ page }) => {
    const photos = await openPhotos(page);
    await photos.getByLabel('Choose photos').setInputFiles(photo(sideways.name));
    await photos.getByRole('button', { name: 'Save photos' }).click();
    const shown = photos.getByTestId('saved-capture').getByRole('img', { name: sideways.name });
    await expect(shown).toBeVisible();
    // Both fixtures are stored 40 x 20, red left and blue right, with "turn 90 degrees clockwise".
    expect(await processedPixels(page, shown)).toEqual({
      width: 20, height: 40, top: [1, 0, 0], bottom: [0, 0, 1], orientationTag: false,
    });
  });
}

test('a phone JPEG carrying extra embedded pictures is accepted', async ({ page }) => {
  const photos = await openPhotos(page);
  await photos.getByLabel('Choose photos').setInputFiles(photo('multi-picture.jpg'));
  await photos.getByRole('button', { name: 'Save photos' }).click();
  await expect(photos.getByTestId('saved-capture').getByRole('img', { name: 'multi-picture.jpg' })).toBeVisible();
  await expect(photos.getByTestId('capture-error')).toBeHidden();
});

// The Playwright servers allow 4 photos of at most 64 KiB and 250,000 pixels each.
const rejected = [
  {
    case: 'an unreadable file', files: [photo('overview.png'), photo('not-a-photo.jpg')],
    reason: 'not-a-photo.jpg could not be read as a JPEG or PNG photo.',
  },
  {
    case: 'a photo over the byte limit', files: [photo('too-many-bytes.png')],
    reason: 'too-many-bytes.png is larger than 64 KiB.',
  },
  {
    case: 'a photo over the pixel limit', files: [photo('too-many-pixels.png')],
    reason: 'too-many-pixels.png has 300,000 pixels; the limit is 250,000.',
  },
  {
    case: 'too many photos',
    files: [1, 2, 3, 4, 5].map(n => ({ name: `view-${n}.jpg`, mimeType: 'image/jpeg', buffer: readFileSync(photo('desk.jpg')) })),
    reason: 'Choose at most 4 photos; 5 were selected.',
  },
];

for (const attempt of rejected) {
  test(`${attempt.case} is refused with a reason and saves nothing`, async ({ page }) => {
    let photos = await openPhotos(page);
    await photos.getByLabel('Choose photos').setInputFiles(photo('desk.jpg'));
    await photos.getByLabel('Room instructions').fill(`Kept before ${attempt.case}.`);
    await photos.getByRole('button', { name: 'Save photos' }).click();
    await expect(photos.getByTestId('saved-instructions')).toHaveText(`Kept before ${attempt.case}.`);

    await photos.getByLabel('Choose photos').setInputFiles(attempt.files);
    await photos.getByLabel('Room instructions').fill('This attempt must not be saved.');
    await photos.getByRole('button', { name: 'Save photos' }).click();
    await expect(photos.getByTestId('capture-error')).toHaveText(attempt.reason);

    await page.reload();
    photos = page.getByRole('region', { name: 'Room photos' });
    const saved = photos.getByTestId('saved-capture');
    await expect(saved.getByTestId('saved-instructions')).toHaveText(`Kept before ${attempt.case}.`);
    await expect(saved.getByRole('img')).toHaveCount(1);
  });
}

test('the overview can be changed after saving', async ({ page }) => {
  let photos = await openPhotos(page);
  await photos.getByLabel('Choose photos').setInputFiles([photo('overview.png'), photo('desk.jpg')]);
  await photos.getByRole('button', { name: 'Save photos' }).click();
  let saved = photos.getByTestId('saved-capture');
  await expect(saved.getByLabel('Use overview.png as overview')).toBeChecked();
  await saved.getByLabel('Use desk.jpg as overview').check();
  await expect(saved.getByTestId('overview-status')).toHaveText('Overview saved: desk.jpg');

  await page.reload();
  photos = page.getByRole('region', { name: 'Room photos' });
  saved = photos.getByTestId('saved-capture');
  await expect(saved.getByLabel('Use desk.jpg as overview')).toBeChecked();
  await expect(saved.getByLabel('Use overview.png as overview')).not.toBeChecked();
});
