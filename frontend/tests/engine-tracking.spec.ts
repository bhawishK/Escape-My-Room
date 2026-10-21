import { expect, test } from '@playwright/test';
import { readFileSync, readdirSync } from 'node:fs';
import { join } from 'node:path';
import { engineCalls, engineFrame, useFakeEngine } from './fixtures/fake-engine';

test('the phone sends its movement log to Python, which saves it for reading after a device check', async ({ page }) => {
  await useFakeEngine(page);
  await page.goto('/');
  await page.getByRole('button', { name: 'Connect phone', exact: true }).click();
  await expect(page.locator('#scene')).toHaveAttribute('data-view', 'phone');
  // Tracking starts, then the person walks a metre toward the desk over a second.
  await page.evaluate(() => {
    (window as unknown as { fakeEngine: { frame: (reality: unknown) => void } }).fakeEngine.frame({
      position: { x: 0, y: 1.5, z: 1.6 }, rotation: { x: 0, y: 0, z: 0, w: 1 }, trackingStatus: 'LIMITED', trackingReason: 'INITIALIZING',
    });
  });
  for (let step = 0; step <= 10; step++) {
    await engineFrame(page, { x: 0, y: 1.6, z: 1.6 - step * 0.1 });
    await page.waitForTimeout(100);
  }
  await page.getByRole('button', { name: 'Send log', exact: true }).click();
  await expect(page.getByTestId('view-status')).toHaveText(/^Log sent · \d+ entries$/);
  const folder = join(process.env.ESCAPE_ROOM_TEST_DATA!, '8771', 'movement-logs');
  const newest = readdirSync(folder).filter(name => name.endsWith('.json')).sort().at(-1)!;
  const log = JSON.parse(readFileSync(join(folder, newest), 'utf-8'));
  expect(log.user_agent).toContain('Mozilla');
  const events = log.entries.filter((entry: { kind: string }) => entry.kind === 'event').map((entry: { name: string; detail: string }) => `${entry.name}: ${entry.detail}`);
  expect(events).toEqual(expect.arrayContaining([
    'mode: measured', 'camera: requesting', 'camera: hasVideo', 'engine tracking: LIMITED INITIALIZING',
    'engine tracking: NORMAL UNSPECIFIED',
  ]));
  const poses = log.entries.filter((entry: { kind: string }) => entry.kind === 'pose');
  expect(poses.length).toBeGreaterThanOrEqual(5);
  expect(poses.at(-1)).toMatchObject({ mode: 'measured', status: 'tracked', x: 0, y: 1.6, z: 0.6, heading: 0, pitch: 0 });
  // Times count up from when the room view opened, in milliseconds.
  const times = log.entries.map((entry: { t: number }) => entry.t);
  expect(times).toEqual([...times].sort((a, b) => a - b));
});

test('8th Wall poses move the phone, and the headset sees where it really is', async ({ browser }) => {
  const phone = await browser.newPage({ viewport: { width: 390, height: 844 } });
  const vr = await browser.newPage();
  await useFakeEngine(phone);
  await vr.goto('/');
  await vr.getByRole('button', { name: 'Connect VR headset', exact: true }).click();
  await phone.goto('/');
  await phone.getByRole('button', { name: 'Connect phone', exact: true }).click();
  await expect(phone.locator('#scene')).toHaveAttribute('data-view', 'phone');
  // The person stands 1.62 m tall at the phone, a step to the right and toward the desk, turned a quarter left.
  const quarterLeft = { x: 0, y: Math.sin(Math.PI / 4), z: 0, w: Math.cos(Math.PI / 4) };
  await engineFrame(phone, { x: 0.4, y: 1.62, z: 0.9 }, quarterLeft);
  await expect(vr.getByTestId('marker-position')).toHaveText('0.40, 1.62, 0.90 m');
  await expect(vr.getByTestId('presence-phone')).toHaveText('Phone · here · 0.40, 1.62, 0.90 m · heading 1.57 rad');
  await phone.close();
  await vr.close();
});

test('the engine starts in metres at the room view’s starting place, facing the desk, with the camera hidden', async ({ page }) => {
  await useFakeEngine(page);
  await page.goto('/');
  await page.getByRole('button', { name: 'Connect phone', exact: true }).click();
  await expect(page.locator('#scene')).toHaveAttribute('data-view', 'phone');
  const calls = await engineCalls(page);
  expect(calls.runs).toBe(1);
  expect(calls.configure).toContainEqual(expect.objectContaining({ scale: 'absolute' }));
  expect(calls.origins.at(-1)).toEqual({ origin: { x: 0, y: 1.5, z: 1.6 }, facing: { w: 1, x: 0, y: 0, z: 0 } });
  expect(calls.modules).toContain('reality');
  expect(calls.cameraFeed).toBe(false);
  // Step-counting controls belong to the fallback.
  await expect(page.getByRole('button', { name: 'Back to start', exact: true })).toBeHidden();
  await expect(page.getByTestId('engine-credits')).toContainText('Niantic Spatial');
  await expect(page.getByRole('link', { name: 'XR Engine License Agreement' })).toHaveAttribute(
    'href', 'https://github.com/8thwall/engine/blob/main/LICENSE');
});
