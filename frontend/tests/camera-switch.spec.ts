import { expect, test, type Page } from '@playwright/test';
import { readFileSync, readdirSync } from 'node:fs';
import { join } from 'node:path';
import { cameraOverlaps, fakeCameras, liveCameras } from './fixtures/fake-cameras';
import { INITIALIZING, engineCalls, engineFrame, useFakeEngine, aimAtBox } from './fixtures/fake-engine';

/** Opens the phone's room view with the fake engine and fake cameras, tracking normally. */
async function trackingPhone(page: Page, path = '/'): Promise<void> {
  await useFakeEngine(page);
  await page.addInitScript(fakeCameras);
  await page.goto(path);
  await page.getByRole('button', { name: 'Connect phone', exact: true }).click();
  await engineFrame(page, { x: 0.3, y: 1.5, z: 1 });
  await expect(page.getByTestId('tracking-mode')).toHaveText('Tracking · 8th Wall, measured');
}

/** The newest movement log Python saved, after Send log. */
async function sentLog(page: Page): Promise<{ entries: { kind: string; name?: string; data?: Record<string, unknown> }[] }> {
  await page.getByRole('button', { name: 'Send log', exact: true }).click();
  await expect(page.getByTestId('view-status')).toHaveText(/^Log sent/);
  const folder = join(process.env.ESCAPE_ROOM_TEST_DATA!, '8771', 'movement-logs');
  const newest = readdirSync(folder).filter(name => name.endsWith('.json')).sort().at(-1)!;
  return JSON.parse(readFileSync(join(folder, newest), 'utf-8'));
}

test('a camera switch pauses the engine, uses the front camera alone, resumes, and logs every stage', async ({ page }) => {
  await trackingPhone(page);
  await expect.poll(() => liveCameras(page)).toEqual(['back']);
  await page.getByRole('button', { name: 'Switch cameras', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Switch cameras', exact: true })).toBeDisabled();
  await expect.poll(async () => (await engineCalls(page)).resumes, { timeout: 5000 }).toBe(1);
  expect((await engineCalls(page)).pauses).toBe(1);
  // Back on the back camera, the engine works out where it is again, then tracks.
  await engineFrame(page, { x: 0, y: 1.5, z: 1.6 }, undefined, INITIALIZING);
  await engineFrame(page, { x: 0.35, y: 1.5, z: 1 });
  await expect(page.getByTestId('view-status')).toHaveText(/^Switched cameras · \d+\.\d s without the back camera · tracking came back after initialising$/);
  await expect(page.getByRole('button', { name: 'Switch cameras', exact: true })).toBeEnabled();
  expect(await cameraOverlaps(page)).toEqual([]);
  expect(await liveCameras(page)).toEqual(['back']);
  const switches = (await sentLog(page)).entries.filter(entry => entry.name === 'camera switch');
  expect(switches).toHaveLength(1);
  const summary = switches[0].data!;
  expect(summary).toMatchObject({ outcome: 'tracking came back after initialising', initializing: true, front_camera: 'opened' });
  for (const field of ['front_first_frame_ms', 'front_closed_ms', 'resumed_ms', 'back_video_ms', 'first_pose_ms', 'normal_ms', 'no_back_camera_ms']) {
    expect(typeof summary[field], field).toBe('number');
  }
  expect(summary.offset).toMatchObject({ metres: 0.05, degrees: 0 });
});

test('an engine that goes straight back to normal tracking is logged as having kept it', async ({ page }) => {
  await trackingPhone(page);
  await page.getByRole('button', { name: 'Switch cameras', exact: true }).click();
  await expect.poll(async () => (await engineCalls(page)).resumes, { timeout: 5000 }).toBe(1);
  await engineFrame(page, { x: 0.3, y: 1.5, z: 1 });
  await expect(page.getByTestId('view-status')).toHaveText(/· tracking kept$/);
  const summary = (await sentLog(page)).entries.find(entry => entry.name === 'camera switch')!.data!;
  expect(summary).toMatchObject({ outcome: 'tracking kept', initializing: false, offset: { metres: 0, degrees: 0 } });
});

test('an engine that does not track again within the limit ends the switch as failed', async ({ page }) => {
  await trackingPhone(page, '/?switch-timeout-ms=1500');
  await page.getByRole('button', { name: 'Switch cameras', exact: true }).click();
  await expect.poll(async () => (await engineCalls(page)).resumes, { timeout: 5000 }).toBe(1);
  await engineFrame(page, { x: 0, y: 1.5, z: 1.6 }, undefined, INITIALIZING);
  await expect(page.getByTestId('view-status')).toHaveText(/· tracking did not come back$/, { timeout: 5000 });
  await expect(page.getByRole('button', { name: 'Switch cameras', exact: true })).toBeEnabled();
  const summary = (await sentLog(page)).entries.find(entry => entry.name === 'camera switch')!.data!;
  expect(summary).toMatchObject({ outcome: 'tracking did not come back', initializing: true, normal_ms: null });
});

test('closing the room view during a switch closes the front camera and stops tracking', async ({ page }) => {
  await trackingPhone(page);
  await page.getByRole('button', { name: 'Switch cameras', exact: true }).click();
  await expect.poll(() => liveCameras(page)).toEqual(['front']);
  await page.getByRole('button', { name: 'Close', exact: true }).click();
  await expect.poll(() => liveCameras(page)).toEqual([]);
  expect((await engineCalls(page)).stops).toBe(1);
  expect((await engineCalls(page)).resumes).toBe(0);
  await page.getByRole('button', { name: 'Open room view', exact: true }).click();
  const summary = (await sentLog(page)).entries.find(entry => entry.name === 'camera switch')!.data!;
  expect(summary).toMatchObject({ outcome: 'cancelled' });
});

test('Switch cameras appears only with measured tracking, and is refused while carrying the box', async ({ browser }) => {
  const counting = await browser.newPage({ viewport: { width: 390, height: 844 } });
  await counting.route('**/@8thwall/**', route => route.abort());
  await counting.addInitScript(() => {
    for (const event of [DeviceOrientationEvent, DeviceMotionEvent]) Object.assign(event, { requestPermission: async () => 'granted' });
  });
  await counting.goto('/');
  await counting.getByRole('button', { name: 'Connect phone', exact: true }).click();
  await expect(counting.getByTestId('tracking-mode')).toHaveText('Tracking · step counting');
  await expect(counting.getByRole('button', { name: 'Switch cameras', exact: true })).toBeHidden();
  await counting.close();

  const phone = await browser.newPage({ viewport: { width: 390, height: 844 } });
  await trackingPhone(phone);
  await expect(phone.getByTestId('room-status')).toHaveAttribute('data-available', 'true');
  await aimAtBox(phone);
  await phone.mouse.click(195, 422);
  await expect(phone.getByTestId('view-status')).toHaveText('Box selected · press and hold it to pick it up');
  await phone.mouse.move(195, 422);
  await phone.mouse.down();
  await expect(phone.getByTestId('view-status')).toHaveText(/^Carrying box/);
  // A second finger taps the button while the first still holds the box.
  await phone.getByRole('button', { name: 'Switch cameras', exact: true }).dispatchEvent('click');
  await expect(phone.getByTestId('view-status')).toHaveText('Let go of the box before switching cameras');
  expect((await engineCalls(phone)).pauses).toBe(0);
  await phone.close();
});

test('one normal frame followed by initialising is a restart, not tracking kept', async ({ page }) => {
  await trackingPhone(page);
  await page.getByRole('button', { name: 'Switch cameras', exact: true }).click();
  await expect.poll(async () => (await engineCalls(page)).resumes, { timeout: 5000 }).toBe(1);
  await engineFrame(page, { x: 0.3, y: 1.5, z: 1 });
  await engineFrame(page, { x: 0, y: 1.5, z: 1.6 }, undefined, INITIALIZING);
  await engineFrame(page, { x: 0.3, y: 1.5, z: 1 });
  await expect(page.getByTestId('view-status')).toHaveText(/· tracking came back after initialising$/);
});

test('during a switch the view turns with the orientation sensor and holds its place, and the headset sees both', async ({ browser }) => {
  const phone = await browser.newPage({ viewport: { width: 390, height: 844 } });
  const vr = await browser.newPage();
  await vr.goto('/');
  await vr.getByRole('button', { name: 'Connect VR headset', exact: true }).click();
  await trackingPhone(phone);
  const turnSensor = (alpha: number) => phone.evaluate(alpha => {
    window.dispatchEvent(new DeviceOrientationEvent('deviceorientation', { alpha, beta: 90, gamma: 0 }));
  }, alpha);
  await turnSensor(0);
  await expect(vr.getByTestId('presence-phone')).toHaveText('Phone · here · 0.30, 1.50, 1.00 m · heading 0.00 rad');
  await phone.getByRole('button', { name: 'Switch cameras', exact: true }).click();
  await expect.poll(() => liveCameras(phone)).toEqual(['front']);
  // With the engine paused, the person turns a quarter to the left.
  await turnSensor(90);
  await expect(vr.getByTestId('presence-phone')).toHaveText('Phone · here · 0.30, 1.50, 1.00 m · heading 1.57 rad');
  await expect(vr.getByTestId('marker-position')).toHaveText('0.30, 1.50, 1.00 m');
  // Back on the back camera, the view follows the engine again.
  await expect.poll(async () => (await engineCalls(phone)).resumes, { timeout: 5000 }).toBe(1);
  await engineFrame(phone, { x: 0.32, y: 1.5, z: 1 });
  await expect(vr.getByTestId('presence-phone')).toHaveText('Phone · here · 0.32, 1.50, 1.00 m · heading 0.00 rad');
  const log = await sentLog(phone);
  const start = log.entries.findIndex(entry => entry.name === 'camera switch start');
  const end = log.entries.findIndex(entry => entry.name === 'camera switch');
  const gap = log.entries.slice(start, end).filter(entry => entry.kind === 'pose') as unknown as { heading: number; x: number }[];
  expect(gap.some(pose => Math.abs(pose.heading - 1.571) < 0.01 && pose.x === 0.3)).toBe(true);
  await phone.close();
  await vr.close();
});

test('a turn made during a switch survives the engine restarting at the start afterwards', async ({ browser }) => {
  const phone = await browser.newPage({ viewport: { width: 390, height: 844 } });
  const vr = await browser.newPage();
  await vr.goto('/');
  await vr.getByRole('button', { name: 'Connect VR headset', exact: true }).click();
  await trackingPhone(phone);
  const turnSensor = (alpha: number) => phone.evaluate(alpha => {
    window.dispatchEvent(new DeviceOrientationEvent('deviceorientation', { alpha, beta: 90, gamma: 0 }));
  }, alpha);
  await turnSensor(0);
  await expect(vr.getByTestId('presence-phone')).toHaveText('Phone · here · 0.30, 1.50, 1.00 m · heading 0.00 rad');
  await phone.getByRole('button', { name: 'Switch cameras', exact: true }).click();
  await expect.poll(() => liveCameras(phone)).toEqual(['front']);
  await turnSensor(90);
  await expect.poll(async () => (await engineCalls(phone)).resumes, { timeout: 5000 }).toBe(1);
  // Back, the engine initialises, then restarts at the start facing the desk.
  await engineFrame(phone, { x: 4, y: 3, z: -2 }, undefined, INITIALIZING);
  await engineFrame(phone, { x: 0, y: 1.5, z: 1.6 });
  await expect(vr.getByTestId('marker-position')).toHaveText('0.30, 1.50, 1.00 m');
  await expect(vr.getByTestId('presence-phone')).toHaveText('Phone · here · 0.30, 1.50, 1.00 m · heading 1.57 rad');
  await phone.close();
  await vr.close();
});
