import { expect, test, type Page } from '@playwright/test';

// #100: the filming coach records the room video in the page, on the browser's fake camera, and
// the recording becomes the video to upload. Its checks are tested on real frames in
// filming-coach.spec.ts; here, that they reach the screen.

test.use({
  launchOptions: { args: ['--use-fake-device-for-media-stream', '--use-fake-ui-for-media-stream'] },
  permissions: ['camera'],
});

async function openVideo(page: Page) {
  await page.goto('/photos.html');
  return page.getByRole('region', { name: 'Room video' });
}

/**
 * A painted camera: a still grid in `colour`, so these tests don't depend on Edge's fake camera,
 * which can't always be opened again straight after another page has recorded from it.
 */
async function paintedCamera(page: Page, colour: string) {
  await page.addInitScript(fill => {
    navigator.mediaDevices.getUserMedia = async () => {
      const canvas = document.createElement('canvas');
      canvas.width = 360;
      canvas.height = 640;
      const context = canvas.getContext('2d')!;
      const paint = () => {
        context.fillStyle = fill;
        context.fillRect(0, 0, 360, 640);
        context.fillStyle = 'rgba(0, 0, 0, 0.5)';
        for (let x = 0; x < 360; x += 24) for (let y = (x / 24) % 2 ? 0 : 24; y < 640; y += 48) context.fillRect(x, y, 24, 24);
      };
      paint();
      setInterval(paint, 100);
      return canvas.captureStream(30);
    };
  }, colour);
}

test('the coach records the room in the page and the recording is the video to upload', async ({ page }) => {
  const video = await openVideo(page);
  await video.getByRole('button', { name: 'Film with coach' }).click();
  const coach = page.getByRole('dialog', { name: 'Filming coach' });
  await expect(coach).toBeVisible();
  // The test films for a second, not the 20 s a room needs.
  await coach.evaluate(element => { element.dataset.minSeconds = '1'; });
  await coach.getByRole('button', { name: 'Record' }).click();
  await expect(coach.getByRole('button', { name: 'Stop' })).toBeVisible();
  await expect(coach.getByText(/^0:0[1-9]$/)).toBeVisible({ timeout: 5000 });
  await coach.getByRole('button', { name: 'Stop' }).click();

  await expect(coach).toBeHidden();
  await expect(video.getByTestId('video-selected')).toHaveText(/^room-\d{4}-\d{2}-\d{2}-\d{4}\.mp4 · \d+ KB/);
  await expect(video.getByRole('button', { name: 'Upload video' })).toBeEnabled();
});

test('stopping before a room is filmed keeps filming and says why', async ({ page }) => {
  await paintedCamera(page, '#c8b89a');
  const video = await openVideo(page);
  await video.getByRole('button', { name: 'Film with coach' }).click();
  const coach = page.getByRole('dialog', { name: 'Filming coach' });
  await coach.getByRole('button', { name: 'Record' }).click();
  await coach.getByRole('button', { name: 'Stop' }).click();
  await expect(coach.getByRole('status')).toHaveText('Keep filming: at least 20 s, round the whole room');
  await expect(coach.getByRole('button', { name: 'Stop' })).toBeVisible();

  await coach.getByRole('button', { name: 'Cancel' }).click();
  await expect(coach).toBeHidden();
  await expect(video.getByTestId('video-selected')).toBeHidden();
});

test('filming in the dark is told to turn the lights on', async ({ page }) => {
  await paintedCamera(page, '#050505');
  const video = await openVideo(page);
  await video.getByRole('button', { name: 'Film with coach' }).click();
  const coach = page.getByRole('dialog', { name: 'Filming coach' });
  await coach.getByRole('button', { name: 'Record' }).click();
  await expect(coach.getByRole('status')).toHaveText('Too dark: turn the lights on');
  await coach.getByRole('button', { name: 'Cancel' }).click();
});

test("Qwen's check on the server prompts while filming, and its failures stay quiet", async ({ page }) => {
  await paintedCamera(page, '#c8b89a');
  const sent: { recording: string; image: string }[] = [];
  let failing = false;
  await page.route('**/api/coach/check', async route => {
    sent.push(route.request().postDataJSON());
    if (failing) return route.abort('connectionreset');
    return route.fulfill({ json: { status: 'ok', prompt: 'Step back to show more of the room', in_shot: 'a door' } });
  });
  const video = await openVideo(page);
  await video.getByRole('button', { name: 'Film with coach' }).click();
  const coach = page.getByRole('dialog', { name: 'Filming coach' });
  await coach.getByRole('button', { name: 'Record' }).click();
  await expect(coach.getByRole('status')).toHaveText('Step back to show more of the room', { timeout: 5000 });
  // A small JPEG of the camera, under the recording's own name.
  expect(sent[0].recording).toMatch(/^rec-/);
  expect(Buffer.from(sent[0].image, 'base64').subarray(0, 2).toString('hex')).toBe('ffd8');

  // Checks that fail leave the prompt off once it has had its time, and filming goes on.
  failing = true;
  await expect(coach.getByRole('status')).toBeHidden({ timeout: 12_000 });
  await expect(coach.getByRole('button', { name: 'Stop' })).toBeVisible();
  await expect(video.getByTestId('video-error')).toBeHidden();
  await coach.getByRole('button', { name: 'Cancel' }).click();
});

test('without MP4 recording, the coach is not offered and the camera app still records', async ({ page }) => {
  await page.addInitScript(() => { MediaRecorder.isTypeSupported = () => false; });
  const video = await openVideo(page);
  await expect(video.getByRole('button', { name: 'Film with coach' })).toBeHidden();
  await expect(video.getByLabel('Record video')).toBeAttached();
});

test('a camera that is refused says how to go on', async ({ page }) => {
  await page.addInitScript(() => {
    navigator.mediaDevices.getUserMedia = async () => { throw new DOMException('denied', 'NotAllowedError'); };
  });
  const video = await openVideo(page);
  await video.getByRole('button', { name: 'Film with coach' }).click();
  await expect(video.getByTestId('video-error'))
    .toHaveText('The camera could not be opened. Allow camera access, or use Record video instead.');
  await expect(page.getByRole('dialog', { name: 'Filming coach' })).toBeHidden();
});
