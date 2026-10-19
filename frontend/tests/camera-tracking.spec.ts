import { expect, test, type Page } from '@playwright/test';
import { STANDING_AT } from './fake-camera';

/*
 * Chromium's fake camera plays a synthetic video of the stand-in room's desk tag, seen from
 * STANDING_AT with the lens the page assumes, for 1.5 s and then 1 s without it, in a loop. This checks the browser, worker and
 * Python path. It is not evidence of physical iPhone tracking.
 */

async function open(page: Page, role: 'phone' | 'VR headset'): Promise<void> {
  await page.goto('/');
  await page.getByRole('button', { name: `Connect ${role}`, exact: true }).click();
  await expect(page.getByTestId('connection')).toHaveText(`Connected · ${role === 'phone' ? 'Phone' : 'VR headset'}`);
}

/** The accepted position a page shows, or null. */
async function shown(page: Page): Promise<number[] | null> {
  const text = await page.getByTestId('marker-position').textContent();
  const match = text?.match(/^(-?[\d.]+), (-?[\d.]+), (-?[\d.]+) m$/);
  return match ? match.slice(1).map(Number) : null;
}

function near(position: number[] | null): boolean {
  return position !== null &&
    Math.hypot(position[0] - STANDING_AT.x, position[1] - STANDING_AT.y, position[2] - STANDING_AT.z) < 0.03;
}

test('the phone camera places the phone in the room and the headset sees it there', async ({ browser }) => {
  const phone = await browser.newPage({ viewport: { width: 390, height: 844 } });
  const headset = await browser.newPage();
  await open(phone, 'phone');
  await open(headset, 'VR headset');
  await expect(phone.getByRole('button', { name: 'Enter VR' })).toBeHidden();
  await phone.getByRole('button', { name: 'Start tracking', exact: true }).click();
  await expect(phone.getByTestId('tracking-status')).toHaveText('Tracking · tag 0', { timeout: 20_000 });
  // Both pages show the same position that Python accepted.
  await expect.poll(async () => near(await shown(headset)), { timeout: 10_000 }).toBe(true);
  await expect.poll(async () => near(await shown(phone))).toBe(true);
  await expect(headset.getByTestId('tracking')).toHaveText('Tracked · room markers');
  await expect(phone.locator('#scene')).toHaveAttribute('data-view', 'phone');
  await expect(phone.getByTestId('alignment-status')).toHaveText('Placed by the room markers');
  // The video then hides the tag: the phone reports lost instead of repeating its last position.
  await expect(headset.getByTestId('tracking')).toHaveText('Lost · marker unavailable', { timeout: 10_000 });
  await expect(headset.getByTestId('marker-position')).toHaveText('No accepted position');
  await expect(phone.getByTestId('tracking-status')).toHaveText('Lost · No room marker in view.');
  // When the tag returns, so does the position.
  await expect.poll(async () => near(await shown(headset)), { timeout: 10_000 }).toBe(true);
  await phone.close();
  await headset.close();
});

test('stopping releases the camera and clears the position, and tracking resumes', async ({ browser }) => {
  const phone = await browser.newPage();
  const headset = await browser.newPage();
  await phone.addInitScript(() => {
    const tracks: MediaStreamTrack[] = [];
    (window as unknown as { cameraTracks: MediaStreamTrack[] }).cameraTracks = tracks;
    const original = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
    navigator.mediaDevices.getUserMedia = async constraints => {
      const stream = await original(constraints);
      tracks.push(...stream.getTracks());
      return stream;
    };
  });
  await open(phone, 'phone');
  await open(headset, 'VR headset');
  const live = () => phone.evaluate(() => (window as unknown as { cameraTracks: MediaStreamTrack[] })
    .cameraTracks.filter(track => track.readyState === 'live').length);
  await phone.getByRole('button', { name: 'Start tracking', exact: true }).click();
  await expect.poll(async () => near(await shown(headset)), { timeout: 20_000 }).toBe(true);
  expect(await live()).toBe(1);
  await phone.getByRole('button', { name: 'Stop tracking', exact: true }).click();
  await expect(headset.getByTestId('tracking')).toHaveText('Inactive · no positional input');
  await expect(headset.getByTestId('marker-position')).toHaveText('No accepted position');
  await expect(phone.getByTestId('tracking-status')).toHaveText('Tracking off');
  expect(await live()).toBe(0);
  await phone.getByRole('button', { name: 'Start tracking', exact: true }).click();
  await expect.poll(async () => near(await shown(headset)), { timeout: 20_000 }).toBe(true);
  // Disconnecting the phone also stops its camera, and Python clears the position.
  await phone.getByRole('button', { name: 'Close', exact: true }).click();
  await phone.getByRole('button', { name: 'Disconnect', exact: true }).click();
  await expect(headset.getByTestId('marker-position')).toHaveText('No accepted position');
  expect(await live()).toBe(0);
  await phone.close();
  await headset.close();
});

test('hiding the page stops tracking and says so', async ({ browser }) => {
  const phone = await browser.newPage();
  const headset = await browser.newPage();
  await open(phone, 'phone');
  await open(headset, 'VR headset');
  await phone.getByRole('button', { name: 'Start tracking', exact: true }).click();
  await expect.poll(async () => near(await shown(headset)), { timeout: 20_000 }).toBe(true);
  await phone.evaluate(() => {
    Object.defineProperty(document, 'visibilityState', { value: 'hidden', configurable: true });
    document.dispatchEvent(new Event('visibilitychange'));
  });
  await expect(headset.getByTestId('tracking')).toHaveText('Inactive · no positional input');
  await expect(phone.getByTestId('tracking-status')).toHaveText(/Tracking stopped while the page was hidden/);
  await expect(phone.getByRole('button', { name: 'Start tracking', exact: true })).toBeEnabled();
  await phone.close();
  await headset.close();
});

test('a refused camera permission is explained and leaves the phone connected', async ({ page }) => {
  await page.addInitScript(() => {
    navigator.mediaDevices.getUserMedia = async () => { throw new DOMException('Denied for test', 'NotAllowedError'); };
  });
  await open(page, 'phone');
  await page.getByRole('button', { name: 'Start tracking', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText('Camera permission was denied');
  await expect(page.getByTestId('tracking-status')).toContainText('Camera permission was denied');
  await expect(page.getByTestId('connection')).toHaveText('Connected · Phone');
  await expect(page.getByRole('button', { name: 'Start tracking', exact: true })).toBeEnabled();
});

test.describe('a room without tracking markers', () => {
  test.use({ baseURL: 'http://127.0.0.1:8772' });

  test('cannot place the phone and says why', async ({ page }) => {
    await open(page, 'phone');
    await expect(page.getByTestId('room-status')).toContainText('Room version 1');
    await page.getByRole('button', { name: 'Start tracking', exact: true }).click();
    await expect(page.getByRole('alert')).toHaveText('This room has no tracking markers, so the phone cannot be placed in it.');
    await expect(page.getByTestId('tracking')).toHaveText('Inactive · no positional input');
  });
});
