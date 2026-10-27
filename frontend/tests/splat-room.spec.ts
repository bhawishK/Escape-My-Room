import { expect, test, type Browser } from '@playwright/test';
import { readFileSync } from 'node:fs';

const origin = 'http://127.0.0.1:8774';

async function connectBoth(browser: Browser, breakSplat = false) {
  const phone = await browser.newPage({ viewport: { width: 390, height: 844 } });
  const vr = await browser.newPage();
  for (const page of [phone, vr]) {
    if (breakSplat) await page.route('**/assets/prepared-room/room*.ply', route => route.fulfill({ status: 404 }));
    await page.goto(origin);
  }
  await phone.getByRole('button', { name: 'Connect phone', exact: true }).click();
  await vr.getByRole('button', { name: 'Connect VR headset', exact: true }).click();
  return [phone, vr];
}

test('phone and headset both show a splat room, with its box still movable', async ({ browser }) => {
  const pages = await connectBoth(browser);
  for (const page of pages) {
    await expect(page.getByTestId('room-status')).toHaveText('Room version 1 · floor, box (movable)');
    await expect(page.locator('#scene')).toHaveAttribute('data-splat', 'shown');
    await expect(page.getByRole('alert')).toBeHidden();
  }
  for (const page of pages) await page.close();
});

test('a splat that cannot be loaded is a visible failure on both devices', async ({ browser }) => {
  const pages = await connectBoth(browser, true);
  for (const page of pages) {
    // The phone loads its lighter copy (#109), the headset the full splat.
    const file = page === pages[0] ? 'room-phone.ply' : 'room.ply';
    await expect(page.getByRole('alert')).toHaveText(`The prepared room splat ${file} could not be loaded.`);
    await expect(page.getByTestId('room-status')).toHaveAttribute('data-available', 'false');
    await expect(page.locator('#scene')).not.toHaveAttribute('data-splat', 'shown');
  }
  for (const page of pages) await page.close();
});

test('a room without a splat loads no splat code', async ({ page }) => {
  const scripts: string[] = [];
  page.on('request', request => { if (request.resourceType() === 'script') scripts.push(request.url()); });
  await page.goto('http://127.0.0.1:8771');
  await page.getByRole('button', { name: 'Connect VR headset', exact: true }).click();
  await expect(page.getByTestId('room-status')).toHaveText('Room version 1 · floor, desk, cabinet, box (movable)');
  expect(scripts.filter(url => url.includes('spark'))).toEqual([]);
});

test('the phone loads the lighter splat and the headset the full one', async ({ browser }) => {
  const splats = new Map<string, string[]>();
  const phone = await browser.newPage({ viewport: { width: 390, height: 844 } });
  const vr = await browser.newPage();
  for (const [name, page] of [['phone', phone], ['vr', vr]] as const) {
    splats.set(name, []);
    page.on('request', request => {
      if (request.url().endsWith('.ply')) splats.get(name)!.push(request.url().split('/').pop()!);
    });
    await page.goto(origin);
  }
  await phone.getByRole('button', { name: 'Connect phone', exact: true }).click();
  await vr.getByRole('button', { name: 'Connect VR headset', exact: true }).click();
  for (const page of [phone, vr]) await expect(page.locator('#scene')).toHaveAttribute('data-splat', 'shown');
  expect(splats.get('phone')).toEqual(['room-phone.ply']);
  expect(splats.get('vr')).toEqual(['room.ply']);
  await phone.close();
  await vr.close();
});

test("the phone draws at the screen's own resolution, not two or three pixels to each", async ({ browser }) => {
  const phone = await browser.newPage({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 3 });
  const vr = await browser.newPage({ deviceScaleFactor: 3 });
  await phone.goto(origin);
  await vr.goto(origin);
  await phone.getByRole('button', { name: 'Connect phone', exact: true }).click();
  await vr.getByRole('button', { name: 'Connect VR headset', exact: true }).click();
  await expect(phone.locator('#scene')).toHaveAttribute('data-view', 'phone');
  const pixels = (page: typeof phone) => page.evaluate(() => {
    const canvas = document.querySelector<HTMLCanvasElement>('#scene canvas')!;
    return canvas.width / canvas.clientWidth;
  });
  expect(await pixels(phone)).toBe(1);
  expect(await pixels(vr)).toBe(2);
  await phone.close();
  await vr.close();
});

test('a phone standing still draws only a few times a second, and its report says so', async ({ page }) => {
  await page.addInitScript(() => {
    for (const event of [DeviceOrientationEvent, DeviceMotionEvent]) Object.assign(event, { requestPermission: async () => 'granted' });
  });
  await page.goto(origin);
  await page.getByRole('button', { name: 'Connect phone', exact: true }).click();
  await expect(page.locator('#scene')).toHaveAttribute('data-splat', 'shown');
  await page.waitForTimeout(5500);

  const download = page.waitForEvent('download');
  await page.evaluate(() => document.getElementById('download-report')!.click());
  const report = JSON.parse(readFileSync(await (await download).path(), 'utf-8'));
  const tracking = report.motion.tracking;
  // Nothing moved, so it drew about ten times a second to keep up with the room, not sixty.
  expect(tracking.frame_rate_hz).toBeGreaterThan(5);
  expect(tracking.frame_rate_hz).toBeLessThan(15);
  expect(tracking.splat).toEqual({ file: 'room-phone.ply', splats: 1564 });
});
