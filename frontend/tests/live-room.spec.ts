import { expect, test } from '@playwright/test';

// Its own server: making a room live changes the shared room for everything that uses it.
const SERVER = 'http://127.0.0.1:8775';
const MP4_HEADER = Buffer.from('000000146674797069736f6d0000020069736f6d', 'hex');

/** A file the test server's fixture probe reads as a 1080p video `seconds` long. */
function fixtureVideo(seconds: number, size: number): Buffer {
  const probe = {
    streams: [{ codec_type: 'video', codec_name: 'hevc', width: 1920, height: 1080, avg_frame_rate: '30/1' }],
    format: { format_name: 'mov,mp4,m4a,3gp,3g2,mj2', duration: String(seconds) },
  };
  const start = Buffer.concat([MP4_HEADER, Buffer.from(JSON.stringify(probe))]);
  return Buffer.concat([start, Buffer.alloc(size - start.length, 0x20)]);
}

test("making a reconstruction live changes the headset's room, and restoring brings the old one back", async ({ browser }) => {
  test.setTimeout(90_000);
  const headset = await (await browser.newContext()).newPage();
  await headset.goto(`${SERVER}/`);
  await headset.getByRole('button', { name: 'Connect VR headset', exact: true }).click();
  const status = headset.getByTestId('room-status');
  await expect(status).toHaveText('Room version 1 · floor, desk, cabinet, box (movable)');

  const page = await (await browser.newContext()).newPage();
  await page.goto(`${SERVER}/photos.html`);
  const video = page.getByRole('region', { name: 'Room video' });
  await video.getByLabel('Choose video').setInputFiles({
    name: 'lounge.mov', mimeType: 'video/quicktime', buffer: fixtureVideo(40, 70 * 1024),
  });
  await video.getByRole('button', { name: 'Upload video' }).click();
  await video.getByRole('button', { name: 'Reconstruct room from lounge.mov' }).click();
  await expect(video.getByTestId('reconstruction-state')).toHaveText('Awaiting review', { timeout: 20_000 });

  await video.getByRole('button', { name: 'Make live' }).click();
  await expect(video.getByTestId('live-room')).toContainText('Live · room version 2', { timeout: 30_000 });
  await expect(status).toHaveText('Room version 2 · floor, box (movable)', { timeout: 15_000 });

  await video.getByRole('button', { name: 'Restore previous room' }).click();
  await expect(video.getByTestId('live-room')).toContainText('Live · room version 3');
  await expect(status).toHaveText('Room version 3 · floor, desk, cabinet, box (movable)', { timeout: 15_000 });
});
