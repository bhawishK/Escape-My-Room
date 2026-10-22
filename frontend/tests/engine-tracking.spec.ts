import { expect, test } from '@playwright/test';
import { readFileSync, readdirSync } from 'node:fs';
import { join } from 'node:path';
import { INITIALIZING, engineCalls, engineFrame, useFakeEngine } from './fixtures/fake-engine';

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

test('while the engine starts, the phone asks for gentle movement and the headset sees it as inactive', async ({ browser }) => {
  const phone = await browser.newPage({ viewport: { width: 390, height: 844 } });
  const vr = await browser.newPage();
  await useFakeEngine(phone);
  await vr.goto('/');
  await vr.getByRole('button', { name: 'Connect VR headset', exact: true }).click();
  await phone.goto('/');
  await phone.getByRole('button', { name: 'Connect phone', exact: true }).click();
  // Working out scale, the engine reports poses that mean nothing yet.
  await engineFrame(phone, { x: 3, y: 0.4, z: -2 }, undefined, INITIALIZING);
  await expect(phone.getByTestId('view-status')).toHaveText('Starting tracking · move the phone gently');
  await expect(vr.getByTestId('tracking')).toHaveText('Inactive · no positional input');
  await engineFrame(phone, { x: 0.2, y: 1.55, z: 1.4 });
  await expect(vr.getByTestId('tracking')).toHaveText('Tracked');
  await expect(vr.getByTestId('marker-position')).toHaveText('0.20, 1.55, 1.40 m');
  await expect(phone.getByTestId('view-status')).toHaveText('Tap the box to select it');
  await phone.close();
  await vr.close();
});

test('a loss holds the view, tells the headset the phone is lost, and recovery tracks again', async ({ browser }) => {
  const phone = await browser.newPage({ viewport: { width: 390, height: 844 } });
  const vr = await browser.newPage();
  await useFakeEngine(phone);
  await vr.goto('/');
  await vr.getByRole('button', { name: 'Connect VR headset', exact: true }).click();
  await phone.goto('/');
  await phone.getByRole('button', { name: 'Connect phone', exact: true }).click();
  await engineFrame(phone, { x: 0.5, y: 1.5, z: 1 });
  await expect(vr.getByTestId('marker-position')).toHaveText('0.50, 1.50, 1.00 m');
  await expect(vr.getByTestId('presence-phone')).toHaveText('Phone · here · 0.50, 1.50, 1.00 m · heading 0.00 rad');
  // Lost, the engine reports a guess tens of metres away, as it did on the iPhone.
  await engineFrame(phone, { x: 46.5, y: 24.9, z: -25.2 }, undefined, INITIALIZING);
  await expect(phone.getByTestId('view-status')).toHaveText('Tracking lost · point at something with detail and move slower');
  await expect(vr.getByTestId('tracking')).toHaveText('Lost · position unavailable');
  // The phone stops reporting where it is, so the headset marks it stale at the last good place.
  await expect(vr.getByTestId('presence-phone')).toHaveText('Phone · stale · 0.50, 1.50, 1.00 m · heading 0.00 rad', { timeout: 5000 });
  // The engine finds its place again, away from the start, so its pose is kept as it is.
  await engineFrame(phone, { x: 0.6, y: 1.5, z: 0.9 });
  await expect(vr.getByTestId('tracking')).toHaveText('Tracked');
  await expect(vr.getByTestId('marker-position')).toHaveText('0.60, 1.50, 0.90 m');
  await expect(phone.getByTestId('view-status')).toHaveText('Tap the box to select it');
  await phone.close();
  await vr.close();
});

test('lost while pointing steeply at the floor, the hint says to raise the phone', async ({ page }) => {
  await useFakeEngine(page);
  await page.goto('/');
  await page.getByRole('button', { name: 'Connect phone', exact: true }).click();
  // Tilted 60° down, as before every loss on the iPhone.
  const down = { x: Math.sin(-Math.PI / 6), y: 0, z: 0, w: Math.cos(-Math.PI / 6) };
  await engineFrame(page, { x: 0, y: 1.5, z: 1 }, down);
  await engineFrame(page, { x: 0, y: 1.5, z: 1 }, down, INITIALIZING);
  await expect(page.getByTestId('view-status')).toHaveText('Tracking lost · raise the phone from the plain floor toward something with detail');
});

test('a loss while carrying the box keeps the hold, and letting go then drops it and reports the loss', async ({ browser }) => {
  const phone = await browser.newPage({ viewport: { width: 390, height: 844 } });
  const vr = await browser.newPage();
  await useFakeEngine(phone);
  await vr.goto('/');
  await vr.getByRole('button', { name: 'Connect VR headset', exact: true }).click();
  await phone.goto('/');
  await phone.getByRole('button', { name: 'Connect phone', exact: true }).click();
  await expect(phone.getByTestId('room-status')).toHaveAttribute('data-available', 'true');
  // Straight above the box, looking down, so it fills the middle of the screen.
  const lookingDown = { x: Math.sin(-Math.PI / 4), y: 0, z: 0, w: Math.cos(-Math.PI / 4) };
  await engineFrame(phone, { x: -0.5, y: 1.2, z: -0.4 }, lookingDown);
  await expect(vr.getByTestId('tracking')).toHaveText('Tracked');
  await phone.mouse.click(195, 422);
  await expect(phone.getByTestId('view-status')).toHaveText('Box selected · press and hold it to pick it up');
  await phone.mouse.move(195, 422);
  await phone.mouse.down();
  await expect(phone.getByTestId('view-status')).toHaveText(/^Carrying box/);
  await engineFrame(phone, { x: 9, y: 7, z: -12 }, lookingDown, INITIALIZING);
  await expect(phone.getByTestId('view-status')).toHaveText(/^Tracking lost/);
  // Python would drop the box at a pose without a position, so none is sent while it is held.
  await phone.waitForTimeout(800);
  await expect(vr.getByTestId('tracking')).toHaveText('Tracked');
  await expect(phone.getByTestId('view-status')).toHaveText(/^Tracking lost/);
  await phone.mouse.up();
  await expect(phone.getByTestId('view-status')).toHaveText('Dropped box');
  await expect(vr.getByTestId('tracking')).toHaveText('Lost · position unavailable');
  await phone.close();
  await vr.close();
});

test('after a loss the engine restarts at the start, so the room is lined up again with where the phone was', async ({ browser }) => {
  const phone = await browser.newPage({ viewport: { width: 390, height: 844 } });
  const vr = await browser.newPage();
  await useFakeEngine(phone);
  await vr.goto('/');
  await vr.getByRole('button', { name: 'Connect VR headset', exact: true }).click();
  await phone.goto('/');
  await phone.getByRole('button', { name: 'Connect phone', exact: true }).click();
  // Standing beside the cabinet, facing a quarter left, when tracking is lost.
  const quarterLeft = { x: 0, y: Math.sin(Math.PI / 4), z: 0, w: Math.cos(Math.PI / 4) };
  await engineFrame(phone, { x: 1.4, y: 1.46, z: -0.6 }, quarterLeft);
  await expect(vr.getByTestId('marker-position')).toHaveText('1.40, 1.46, -0.60 m');
  await engineFrame(phone, { x: 9, y: 9, z: 9 }, quarterLeft, INITIALIZING);
  // Recovered, the engine says the phone is back at the start facing the desk, 2.8 m higher, as on the iPhone.
  await engineFrame(phone, { x: 0, y: 4.26, z: 1.5 });
  await expect(vr.getByTestId('marker-position')).toHaveText('1.40, 1.46, -0.60 m');
  await expect(vr.getByTestId('presence-phone')).toContainText('heading 1.57 rad');
  // Half a metre forward in the engine's new world is half a metre where the phone faces: toward -x.
  await engineFrame(phone, { x: 0, y: 4.26, z: 1.0 });
  await expect(vr.getByTestId('marker-position')).toHaveText('0.90, 1.46, -0.60 m');
  await phone.close();
  await vr.close();
});

test('in measured mode, Recentre makes where the phone is the start again; tapping the room never recentres', async ({ browser }) => {
  const phone = await browser.newPage({ viewport: { width: 390, height: 844 } });
  const vr = await browser.newPage();
  await useFakeEngine(phone);
  await vr.goto('/');
  await vr.getByRole('button', { name: 'Connect VR headset', exact: true }).click();
  await phone.goto('/');
  await phone.getByRole('button', { name: 'Connect phone', exact: true }).click();
  await expect(phone.getByTestId('tracking-mode')).toHaveText('Tracking · 8th Wall, measured');
  await expect(phone.getByRole('button', { name: 'Back to start', exact: true })).toBeHidden();
  await expect(phone.getByRole('button', { name: 'Step 0.6 m', exact: true })).toBeHidden();
  // A loss lines the room up with where the phone was.
  await engineFrame(phone, { x: 1, y: 1.5, z: 0 });
  await engineFrame(phone, { x: 1, y: 1.5, z: 0 }, undefined, INITIALIZING);
  await engineFrame(phone, { x: 0, y: 1.5, z: 1.6 });
  await expect(vr.getByTestId('marker-position')).toHaveText('1.00, 1.50, 0.00 m');
  await phone.mouse.click(195, 300);
  expect((await engineCalls(phone)).recenters).toBe(0);
  // Standing on the start facing the desk, the person recentres: the engine's start is the room's again.
  await phone.getByRole('button', { name: 'Recentre', exact: true }).click();
  expect((await engineCalls(phone)).recenters).toBe(1);
  await engineFrame(phone, { x: 0, y: 1.5, z: 1.6 });
  await expect(vr.getByTestId('marker-position')).toHaveText('0.00, 1.50, 1.60 m');
  await phone.close();
  await vr.close();
});

test('counting steps, the phone says so and shows Back to start and step length, not Recentre', async ({ page }) => {
  await page.route('**/@8thwall/**', route => route.abort());
  await page.addInitScript(() => {
    for (const event of [DeviceOrientationEvent, DeviceMotionEvent]) Object.assign(event, { requestPermission: async () => 'granted' });
  });
  await page.goto('/');
  await page.getByRole('button', { name: 'Connect phone', exact: true }).click();
  await expect(page.getByTestId('tracking-mode')).toHaveText('Tracking · step counting');
  await expect(page.getByRole('button', { name: 'Back to start', exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Step 0.6 m', exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Recentre', exact: true })).toBeHidden();
});

test('turning while tracking is lost is measured by the orientation sensor and kept when the room is lined up again', async ({ browser }) => {
  const phone = await browser.newPage({ viewport: { width: 390, height: 844 } });
  const vr = await browser.newPage();
  await useFakeEngine(phone);
  await vr.goto('/');
  await vr.getByRole('button', { name: 'Connect VR headset', exact: true }).click();
  await phone.goto('/');
  await phone.getByRole('button', { name: 'Connect phone', exact: true }).click();
  const turnSensor = (alpha: number) => phone.evaluate(alpha => {
    window.dispatchEvent(new DeviceOrientationEvent('deviceorientation', { alpha, beta: 90, gamma: 0 }));
  }, alpha);
  await turnSensor(0);
  await engineFrame(phone, { x: 0, y: 1.5, z: 1 });
  await expect(vr.getByTestId('presence-phone')).toContainText('heading 0.00 rad');
  await engineFrame(phone, { x: 0, y: 1.5, z: 1 }, undefined, INITIALIZING);
  // Lost, the person turns a quarter to the left.
  await turnSensor(90);
  await engineFrame(phone, { x: 0, y: 1.5, z: 1.6 });
  await expect(vr.getByTestId('marker-position')).toHaveText('0.00, 1.50, 1.00 m');
  await expect(vr.getByTestId('presence-phone')).toContainText('heading 1.57 rad');
  await phone.close();
  await vr.close();
});
