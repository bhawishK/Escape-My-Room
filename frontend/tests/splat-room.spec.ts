import { expect, test, type Browser } from '@playwright/test';

const origin = 'http://127.0.0.1:8774';

async function connectBoth(browser: Browser, breakSplat = false) {
  const phone = await browser.newPage({ viewport: { width: 390, height: 844 } });
  const vr = await browser.newPage();
  for (const page of [phone, vr]) {
    if (breakSplat) await page.route('**/assets/prepared-room/room.ply', route => route.fulfill({ status: 404 }));
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
    const failure = 'The prepared room splat room.ply could not be loaded.';
    await expect(page.getByRole('alert')).toHaveText(failure);
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
