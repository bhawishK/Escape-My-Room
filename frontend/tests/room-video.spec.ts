import { expect, test, type Page } from '@playwright/test';

// The test servers send videos in 64 KB chunks, accept up to 1 MB, and stand in for ffprobe with
// a fixture probe: an MP4 `ftyp` box followed by the JSON ffprobe would print.
const MP4_HEADER = Buffer.from('000000146674797069736f6d0000020069736f6d', 'hex');

/** A file the fixture probe reads as a portrait 1080p video `seconds` long and `size` bytes. */
function fixtureVideo(seconds: number, size: number): Buffer {
  const probe = {
    streams: [{
      codec_type: 'video', codec_name: 'hevc', width: 1920, height: 1080, avg_frame_rate: '30/1',
      side_data_list: [{ rotation: -90 }],
    }],
    format: { format_name: 'mov,mp4,m4a,3gp,3g2,mj2', duration: String(seconds) },
  };
  const start = Buffer.concat([MP4_HEADER, Buffer.from(JSON.stringify(probe))]);
  return Buffer.concat([start, Buffer.alloc(size - start.length, 0x20)]);
}

async function openVideo(page: Page) {
  await page.goto('/photos.html');
  return page.getByRole('region', { name: 'Room video' });
}

test('a room video uploads in chunks, survives a dropped chunk, and is listed with its length', async ({ page }) => {
  const sent: string[] = [];
  let dropped = false;
  await page.route('**/api/videos/*/chunks/*', async route => {
    const number = route.request().url().split('/').pop()!;
    sent.push(number);
    // The connection drops once, on the second chunk.
    if (number === '1' && !dropped) {
      dropped = true;
      return route.abort('connectionreset');
    }
    return route.continue();
  });
  const video = await openVideo(page);
  await video.getByLabel('Choose video').setInputFiles({
    name: 'hallway.mov', mimeType: 'video/quicktime', buffer: fixtureVideo(83.4, 200 * 1024),
  });
  await expect(video.getByTestId('video-selected')).toHaveText('hallway.mov · 200 KB');
  await video.getByRole('button', { name: 'Upload video' }).click();

  const saved = video.getByRole('list', { name: 'Saved videos' });
  await expect(saved.getByRole('listitem').first()).toContainText('hallway.mov · 1 min 23 s · 1080 × 1920');
  expect(sent).toEqual(['0', '1', '1', '2', '3']);
  await expect(video.getByRole('progressbar')).toHaveAttribute('value', '1');

  await page.reload();
  await expect((await openVideo(page)).getByRole('list', { name: 'Saved videos' }).getByRole('listitem').first())
    .toContainText('hallway.mov · 1 min 23 s · 1080 × 1920');
});

test('a video too long for the server is refused with the reason', async ({ page }) => {
  const video = await openVideo(page);
  await video.getByLabel('Choose video').setInputFiles({
    name: 'long.mp4', mimeType: 'video/mp4', buffer: fixtureVideo(400, 70 * 1024),
  });
  await video.getByRole('button', { name: 'Upload video' }).click();

  await expect(video.getByTestId('video-error')).toHaveText('long.mp4 is 6 min 40 s long; keep it under 5 min 0 s.');
});

test('the camera records the video and the page says how to film the room', async ({ page }) => {
  const video = await openVideo(page);
  await expect(video.getByLabel('Record video')).toHaveAttribute('capture', 'environment');
  await expect(video.getByLabel('Record video')).toHaveAttribute('accept', 'video/*');
  await expect(video).toContainText('Film at 1080p');
  await expect(video).toContainText('both ways');
});

test('a video of another type is refused with the reason, before anything is sent', async ({ page }) => {
  const video = await openVideo(page);
  await video.getByLabel('Choose video').setInputFiles({
    name: 'room.webm', mimeType: 'video/webm', buffer: fixtureVideo(30, 70 * 1024),
  });
  await video.getByRole('button', { name: 'Upload video' }).click();

  await expect(video.getByTestId('video-error')).toHaveText('Upload an MP4 or MOV video; room.webm is video/webm.');
});

test('a MOV the browser gives no type is still sent as a MOV', async ({ page }) => {
  const video = await openVideo(page);
  await video.getByLabel('Choose video').setInputFiles({
    name: 'untyped.MOV', mimeType: '', buffer: fixtureVideo(12, 70 * 1024),
  });
  await video.getByRole('button', { name: 'Upload video' }).click();

  await expect(video.getByRole('list', { name: 'Saved videos' }).getByRole('listitem').first())
    .toContainText('untyped.MOV · 12 s · 1080 × 1920');
});

test('when the answer to finishing is lost, the page asks again and the video is saved once', async ({ page }) => {
  let lost = false;
  await page.route('**/api/videos/*/complete', async route => {
    if (!lost) {
      lost = true;
      // The server finishes the upload, but its answer never reaches the page.
      await route.fetch();
      return route.abort('connectionreset');
    }
    return route.continue();
  });
  const video = await openVideo(page);
  await video.getByLabel('Choose video').setInputFiles({
    name: 'once.mp4', mimeType: 'video/mp4', buffer: fixtureVideo(20, 70 * 1024),
  });
  await video.getByRole('button', { name: 'Upload video' }).click();

  // Other tests' videos may be listed too; this one must be listed exactly once.
  const saved = video.getByRole('list', { name: 'Saved videos' }).getByRole('listitem');
  await expect(saved.first()).toContainText('once.mp4 · 20 s');
  await expect(saved.filter({ hasText: 'once.mp4' })).toHaveCount(1);
});

test('reconstructing a saved video shows each stage, the live training steps, then what it made', async ({ page }) => {
  const video = await openVideo(page);
  await video.getByLabel('Choose video').setInputFiles({
    name: 'study.mov', mimeType: 'video/quicktime', buffer: fixtureVideo(64, 70 * 1024),
  });
  await video.getByRole('button', { name: 'Upload video' }).click();
  await video.getByRole('button', { name: 'Reconstruct room from study.mov' }).click();

  const stages = video.getByRole('list', { name: 'Reconstruction stages' }).getByRole('listitem');
  await expect(stages).toHaveText([
    /^Frames · /, /^COLMAP · /, /^Levelling · /, /^Splat training · /, /^Positioning map · /, /^Package · /,
  ]);
  await expect(stages.nth(3)).toContainText(/step [123] of 3 · [123],000 splats/);
  await expect(video.getByTestId('reconstruction-state')).toHaveText('Awaiting review', { timeout: 15_000 });
  await expect(stages.nth(0)).toHaveText(/^Frames · done in \d+\.\d s$/);
  await expect(video.getByTestId('reconstruction-summary')).toHaveText(
    'study.mov · 118 of 120 frames placed · 300,000 splats · PSNR 24.5 dB · 200,000 map keypoints',
  );

  await page.reload();
  await expect((await openVideo(page)).getByTestId('reconstruction-state')).toHaveText('Awaiting review');
});
