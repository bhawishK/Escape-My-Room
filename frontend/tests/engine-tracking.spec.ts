import { type Browser, type Page, expect, test } from '@playwright/test';
import { readFileSync, readdirSync } from 'node:fs';
import { join } from 'node:path';
import { fakeCameras, liveCameras } from './fixtures/cameras';
import { INITIALIZING, closeMap, engineCalls, engineFrame, grantMotionPermission, useFakeEngine } from './fixtures/fake-engine';

test('the phone sends its movement log to Python, which saves it for reading after a device check', async ({ page }) => {
  await useFakeEngine(page);
  await page.goto('/');
  await page.getByRole('button', { name: 'Connect phone', exact: true }).click();
  await closeMap(page);
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
  // The diagnostic report's tracking summary comes along, so nothing has to be downloaded on the phone.
  expect(log.tracking).toMatchObject({
    mode: 'measured', fallback_reason: null, pose_rate_hz: expect.any(Number), frame_rate_hz: expect.any(Number),
    // This room has no splat.
    splat: null,
  });
  expect(log.tracking.status_changes.map((change: { status: string }) => change.status)).toEqual(['inactive', 'tracked']);
  expect(log.tracking.first_tracked_pose_ms).toEqual(expect.any(Number));
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
  await closeMap(phone);
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
  await closeMap(page);
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
  await closeMap(phone);
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
  await closeMap(phone);
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
  await closeMap(page);
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
  await closeMap(phone);
  await expect(phone.getByTestId('room-status')).toHaveAttribute('data-available', 'true');
  // 1.2 m back and up, tilted 45° down: the screen centre meets the floor at the box, which fills the
  // middle of the screen, and holding it aims at its own place, so dropping it leaves it there. Its
  // place comes from Python, since tests share one room.
  const room = await (await phone.request.get('/api/room')).json() as { entities: { id: string; position: { x: number; z: number } }[] };
  const box = room.entities.find(entity => entity.id === 'box')!.position;
  const tilted = { x: Math.sin(-Math.PI / 8), y: 0, z: 0, w: Math.cos(-Math.PI / 8) };
  await engineFrame(phone, { x: box.x, y: 1.2, z: box.z + 1.2 }, tilted);
  await expect(vr.getByTestId('tracking')).toHaveText('Tracked');
  // The view moves to the new pose on its next drawn frame.
  await phone.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
  await phone.mouse.click(195, 422);
  await expect(phone.getByTestId('view-status')).toHaveText('Box selected · press and hold it to pick it up');
  await phone.mouse.move(195, 422);
  await phone.mouse.down();
  await expect(phone.getByTestId('view-status')).toHaveText(/^Carrying box/);
  await engineFrame(phone, { x: 9, y: 7, z: -12 }, tilted, INITIALIZING);
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
  await closeMap(phone);
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
  await closeMap(phone);
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
  await closeMap(page);
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
  await closeMap(phone);
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

/** The diagnostic report the page offers for download, as JSON. */
async function downloadReport(page: Page): Promise<{ motion: { tracking: Record<string, unknown> } }> {
  const download = page.waitForEvent('download');
  // The room view covers the diagnostics while it is open; the report is still the same.
  await page.evaluate(() => document.getElementById('download-report')!.click());
  return JSON.parse(readFileSync(await (await download).path(), 'utf-8'));
}

test('the diagnostic report records how measured tracking behaved', async ({ page }) => {
  await useFakeEngine(page);
  await page.goto('/');
  await page.getByRole('button', { name: 'Connect phone', exact: true }).click();
  await closeMap(page);
  await expect(page.locator('#scene')).toHaveAttribute('data-view', 'phone');
  await engineFrame(page, { x: 3, y: 0.4, z: -2 }, undefined, INITIALIZING);
  await page.waitForTimeout(200);
  // Tracked, then lost while moving too fast, then tracked again: ten poses in all.
  for (let step = 0; step < 5; step++) await engineFrame(page, { x: 0, y: 1.6, z: 1.6 - step * 0.1 });
  await engineFrame(page, { x: 9, y: 9, z: 9 }, undefined, { trackingStatus: 'LIMITED', trackingReason: 'EXCESSIVE_MOTION' });
  for (let step = 0; step < 5; step++) await engineFrame(page, { x: 0, y: 1.6, z: 1.1 - step * 0.1 });

  await expect(page.getByTestId('tracking-stats')).toHaveText(/^Measured · tracked · 2\.0 poses\/s · \d+ fps$/);
  const tracking = (await downloadReport(page)).motion.tracking;
  expect(tracking.mode).toBe('measured');
  expect(tracking.fallback_reason).toBeNull();
  const changes = tracking.status_changes as { at_ms: number; status: string; reason: string }[];
  expect(changes.map(({ status, reason }) => `${status}: ${reason}`)).toEqual([
    'inactive: starting',
    'tracked: NORMAL UNSPECIFIED',
    'lost: LIMITED EXCESSIVE_MOTION',
    'tracked: NORMAL UNSPECIFIED',
  ]);
  // Times count from when the room view opened; the first pose came after the starting frame.
  expect(changes.map(change => change.at_ms)).toEqual([...changes.map(change => change.at_ms)].sort((a, b) => a - b));
  expect(Math.abs((tracking.first_tracked_pose_ms as number) - changes[1].at_ms)).toBeLessThanOrEqual(1);
  expect(tracking.first_tracked_pose_ms).toBeGreaterThanOrEqual(200);
  expect(tracking.pose_rate_hz).toBe(2);
});

test('the diagnostic report says when the phone counts steps instead, and why', async ({ page }) => {
  // No engine: the phone falls back to turning and counted steps.
  await page.route('**/@8thwall/**', route => route.abort());
  await grantMotionPermission(page);
  await page.goto('/');
  await page.getByRole('button', { name: 'Connect phone', exact: true }).click();
  await closeMap(page);
  await expect(page.locator('#scene')).toHaveAttribute('data-view', 'phone');

  await expect(page.getByTestId('tracking-stats')).toHaveText('Steps · engine not loaded · tracked');
  const tracking = (await downloadReport(page)).motion.tracking;
  expect(tracking.mode).toBe('steps');
  expect(tracking.fallback_reason).toBe('engine not loaded');
  expect(tracking.first_tracked_pose_ms).toBeNull();
  expect(tracking.pose_rate_hz).toBe(0);
});

test('each opening of the room view is timed to its own first pose, and every mode is kept', async ({ page }) => {
  await useFakeEngine(page);
  await page.goto('/');
  const before = (await downloadReport(page)).motion.tracking;
  // Nothing has started: no mode is claimed yet.
  expect(before.mode).toBeNull();
  expect(before.mode_changes).toEqual([]);

  await page.getByRole('button', { name: 'Connect phone', exact: true }).click();
  await closeMap(page);
  await expect(page.locator('#scene')).toHaveAttribute('data-view', 'phone');
  await engineFrame(page, { x: 0, y: 1.6, z: 1.6 });
  await page.getByRole('button', { name: 'Close', exact: true }).click();
  await page.getByRole('button', { name: 'Open room view', exact: true }).click();
  await closeMap(page);
  await page.waitForTimeout(300);
  await engineFrame(page, { x: 0, y: 1.6, z: 1.2 });

  const tracking = (await downloadReport(page)).motion.tracking;
  const openings = tracking.openings as { opened_at_ms: number; first_tracked_pose_ms: number | null }[];
  expect(openings).toHaveLength(2);
  expect(openings[1].opened_at_ms).toBeGreaterThan(openings[0].opened_at_ms);
  // The second opening's first pose came 300 ms or more after it opened, not counted from the first.
  expect(openings[1].first_tracked_pose_ms).toBeGreaterThanOrEqual(300);
  expect(tracking.first_tracked_pose_ms).toBe(openings[1].first_tracked_pose_ms);
  const changes = tracking.status_changes as { status: string; reason: string; mode: string }[];
  expect(changes.map(({ mode, status, reason }) => `${mode} ${status}: ${reason}`)).toEqual([
    'measured inactive: starting',
    'measured tracked: NORMAL UNSPECIFIED',
    'measured inactive: room view closed',
    'measured inactive: starting',
    'measured tracked: NORMAL UNSPECIFIED',
  ]);
  expect((tracking.mode_changes as { mode: string }[]).map(change => change.mode)).toEqual(['measured']);
});

test('the gaze cursor pauses measured tracking, which the headset sees as lost, and stopping it tracks again', async ({ browser }) => {
  const phone = await browser.newPage({ viewport: { width: 390, height: 844 } });
  const vr = await browser.newPage();
  await useFakeEngine(phone);
  await phone.addInitScript(fakeCameras);
  // The face model stays downloading, so the gaze cursor keeps the front camera until it is stopped.
  await phone.context().route('**/face_landmarker.task', () => undefined);
  await vr.goto('/');
  await vr.getByRole('button', { name: 'Connect VR headset', exact: true }).click();
  await phone.goto('/');
  await phone.getByRole('button', { name: 'Connect phone', exact: true }).click();
  await closeMap(phone);
  await engineFrame(phone, { x: 0.5, y: 1.5, z: 1 });
  await expect(vr.getByTestId('tracking')).toHaveText('Tracked');

  // The phone runs one camera at a time: the engine stops for the front camera.
  await phone.getByRole('button', { name: 'Gaze cursor', exact: true }).click();
  await expect(phone.getByLabel('Front camera')).toBeVisible();
  expect((await engineCalls(phone)).stops).toBe(1);
  await expect(phone.getByTestId('tracking-mode')).toHaveText('Tracking · 8th Wall, paused for the gaze cursor');
  await expect(vr.getByTestId('tracking')).toHaveText('Lost · position unavailable');
  expect(await liveCameras(phone)).toEqual(['front']);

  // Stopping the gaze cursor releases the front camera and starts the engine again, from the start.
  await phone.getByRole('button', { name: 'Stop gaze cursor', exact: true }).click();
  await expect.poll(async () => (await engineCalls(phone)).runs).toBe(2);
  expect((await engineCalls(phone)).origins.at(-1)).toEqual(START);
  expect(await liveCameras(phone)).toEqual([]);
  await expect(phone.getByTestId('tracking-mode')).toHaveText('Tracking · 8th Wall, measured');
  await engineFrame(phone, { x: 0.2, y: 1.5, z: 1.4 });
  await expect(vr.getByTestId('tracking')).toHaveText('Tracked');
  await expect(vr.getByTestId('marker-position')).toHaveText('0.20, 1.50, 1.40 m');
  await phone.close();
  await vr.close();
});

test('measuring the height is offered only while counting steps: measured tracking measures it', async ({ browser }) => {
  const measuring = await browser.newPage({ viewport: { width: 390, height: 844 } });
  await useFakeEngine(measuring);
  await measuring.goto('/');
  await measuring.getByRole('button', { name: 'Connect phone', exact: true }).click();
  await closeMap(measuring);
  await expect(measuring.getByTestId('tracking-mode')).toHaveText('Tracking · 8th Wall, measured');
  await expect(measuring.getByRole('button', { name: 'Measure height', exact: true })).toBeHidden();
  await expect(measuring.getByRole('button', { name: 'Gaze cursor', exact: true })).toBeVisible();
  await measuring.close();

  const counting = await browser.newPage({ viewport: { width: 390, height: 844 } });
  await counting.route('**/@8thwall/**', route => route.abort());
  await grantMotionPermission(counting);
  await counting.goto('/');
  await counting.getByRole('button', { name: 'Connect phone', exact: true }).click();
  await closeMap(counting);
  await expect(counting.getByTestId('tracking-mode')).toHaveText('Tracking · step counting');
  await expect(counting.getByRole('button', { name: 'Measure height', exact: true })).toBeVisible();
  await counting.close();
});

test('closing the room view stops the engine, and reopening starts it again from the starting viewpoint', async ({ browser }) => {
  const phone = await browser.newPage({ viewport: { width: 390, height: 844 } });
  const vr = await browser.newPage();
  await useFakeEngine(phone);
  await vr.goto('/');
  await vr.getByRole('button', { name: 'Connect VR headset', exact: true }).click();
  await phone.goto('/');
  await phone.getByRole('button', { name: 'Connect phone', exact: true }).click();
  await closeMap(phone);
  await engineFrame(phone, { x: 0.8, y: 1.5, z: 0.3 });
  await expect(vr.getByTestId('marker-position')).toHaveText('0.80, 1.50, 0.30 m');

  await phone.getByRole('button', { name: 'Close', exact: true }).click();
  expect((await engineCalls(phone)).stops).toBe(1);
  await expect(vr.getByTestId('tracking')).toHaveText('Inactive · no positional input');

  await phone.getByRole('button', { name: 'Open room view', exact: true }).click();
  await closeMap(phone);
  await expect.poll(async () => (await engineCalls(phone)).runs).toBe(2);
  expect((await engineCalls(phone)).origins.at(-1)).toEqual(START);
  await engineFrame(phone, { x: 0, y: 1.5, z: 1.5 });
  await expect(vr.getByTestId('marker-position')).toHaveText('0.00, 1.50, 1.50 m');
  await phone.close();
  await vr.close();
});

/** The starting viewpoint the engine is told to start from, facing the desk. */
const START = { origin: { x: 0, y: 1.5, z: 1.6 }, facing: { w: 1, x: 0, y: 0, z: 0 } };

/** A phone tracking with the fake engine, with fake cameras and a face model that never loads. */
async function trackingPhone(page: Page): Promise<void> {
  await useFakeEngine(page);
  await page.addInitScript(fakeCameras);
  await page.context().route('**/face_landmarker.task', () => undefined);
  await page.goto('/');
  await page.getByRole('button', { name: 'Connect phone', exact: true }).click();
  await closeMap(page);
  await engineFrame(page, { x: 0.5, y: 1.5, z: 1 });
}

test('closing the room view while the gaze cursor has the camera does not start the engine, reopening does', async ({ page }) => {
  await trackingPhone(page);
  await page.getByRole('button', { name: 'Gaze cursor', exact: true }).click();
  await expect(page.getByTestId('tracking-mode')).toHaveText('Tracking · 8th Wall, paused for the gaze cursor');

  await page.getByRole('button', { name: 'Close', exact: true }).click();
  expect(await liveCameras(page)).toEqual([]);
  expect(await engineCalls(page)).toMatchObject({ runs: 1, stops: 1 });

  await page.getByRole('button', { name: 'Open room view', exact: true }).click();
  await closeMap(page);
  await expect.poll(async () => (await engineCalls(page)).runs).toBe(2);
  expect((await engineCalls(page)).origins.at(-1)).toEqual(START);
  await engineFrame(page, { x: 0, y: 1.5, z: 1.5 });
  const changes = (await downloadReport(page)).motion.tracking.status_changes as { status: string; reason: string }[];
  expect(changes.map(({ status, reason }) => `${status}: ${reason}`)).toEqual([
    'inactive: starting',
    'tracked: NORMAL UNSPECIFIED',
    'lost: paused for the gaze cursor',
    'inactive: room view closed',
    'inactive: starting',
    'tracked: NORMAL UNSPECIFIED',
  ]);
});

test('hiding the page stops the gaze cursor but starts the engine only once the page is back', async ({ page }) => {
  await trackingPhone(page);
  await page.getByRole('button', { name: 'Gaze cursor', exact: true }).click();
  await expect(page.getByLabel('Front camera')).toBeVisible();

  const visibility = (state: 'hidden' | 'visible') => page.evaluate(value => {
    Object.defineProperty(document, 'visibilityState', { value, configurable: true });
    document.dispatchEvent(new Event('visibilitychange'));
  }, state);
  await visibility('hidden');
  await expect(page.getByLabel('Front camera')).toBeHidden();
  await page.waitForTimeout(300);
  expect((await engineCalls(page)).runs).toBe(1);
  await expect(page.getByTestId('tracking-mode')).toHaveText('Tracking · 8th Wall, paused for the gaze cursor');

  await visibility('visible');
  await expect.poll(async () => (await engineCalls(page)).runs).toBe(2);
  expect((await engineCalls(page)).origins.at(-1)).toEqual(START);
  await expect(page.getByTestId('tracking-mode')).toHaveText('Tracking · 8th Wall, measured');
  // The restarted engine has no reason of its own yet: the old engine's is not carried over.
  const changes = (await downloadReport(page)).motion.tracking.status_changes as { status: string; reason: string }[];
  expect(changes.slice(-2).map(({ status, reason }) => `${status}: ${reason}`)).toEqual([
    'lost: paused for the gaze cursor',
    'inactive: starting',
  ]);
});

test('a link can choose step counting even where 8th Wall could track, and the report says so', async ({ page }) => {
  await useFakeEngine(page);
  await page.goto('/?tracking=steps');
  await page.getByRole('button', { name: 'Connect phone', exact: true }).click();
  await closeMap(page);

  await expect(page.getByTestId('tracking-mode')).toHaveText('Tracking · step counting');
  expect((await engineCalls(page)).runs).toBe(0);
  await expect(page.getByRole('button', { name: 'Measure height', exact: true })).toBeVisible();
  const tracking = (await downloadReport(page)).motion.tracking;
  expect(tracking.mode).toBe('steps');
  expect(tracking.fallback_reason).toBe('step counting chosen in the link');
});

/** Frames at one place for `ms`, as 8th Wall delivers them while the phone is held still. */
async function holdStill(page: Page, position: { x: number; y: number; z: number }, ms: number): Promise<void> {
  for (let elapsed = 0; elapsed <= ms; elapsed += 150) {
    await engineFrame(page, position);
    await page.waitForTimeout(150);
  }
}

/** A phone tracking with the fake engine, opened from `link`, and a connected headset. */
async function phoneAndHeadset(browser: Browser, link = '/'): Promise<{ phone: Page; vr: Page }> {
  const phone = await browser.newPage({ viewport: { width: 390, height: 844 } });
  const vr = await browser.newPage();
  await useFakeEngine(phone);
  await vr.goto('/');
  await vr.getByRole('button', { name: 'Connect VR headset', exact: true }).click();
  await phone.goto(link);
  await phone.getByRole('button', { name: 'Connect phone', exact: true }).click();
  await closeMap(phone);
  return { phone, vr };
}

test("8th Wall's distances are scaled by the phone's real height over the height it reports", async ({ browser }) => {
  const { phone, vr } = await phoneAndHeadset(browser);
  // 8th Wall thinks the phone is 0.7 m up: everything it measures is half the real size.
  await holdStill(phone, { x: 0, y: 0.7, z: 1.6 }, 1700);
  await engineFrame(phone, { x: 0.5, y: 0.7, z: 1.6 });

  // Half a metre by 8th Wall is a metre in the room, and the phone is at its real 1.4 m.
  await expect(vr.getByTestId('marker-position')).toHaveText('1.00, 1.40, 1.60 m');
  await phone.getByRole('button', { name: 'Send log', exact: true }).click();
  await expect(phone.getByTestId('view-status')).toHaveText(/^Log sent/);
  const folder = join(process.env.ESCAPE_ROOM_TEST_DATA!, '8771', 'movement-logs');
  const log = JSON.parse(readFileSync(join(folder, readdirSync(folder).sort().at(-1)!), 'utf-8'));
  expect(log.tracking.scale).toEqual({ factor: 2, engine_height_m: 0.7, real_height_m: 1.4, clamped: false });
  await phone.close();
  await vr.close();
});

test('the scale is measured again after 8th Wall restarts, and an impossible one is clamped', async ({ browser }) => {
  const { phone, vr } = await phoneAndHeadset(browser);
  await holdStill(phone, { x: 0, y: 0.7, z: 1.6 }, 1700);
  // Lost, then restarted at the start: this time it thinks the phone is 0.2 m up.
  await engineFrame(phone, { x: 9, y: 9, z: 9 }, undefined, INITIALIZING);
  await holdStill(phone, { x: 0, y: 0.2, z: 1.6 }, 1700);

  const tracking = (await downloadReport(phone)).motion.tracking;
  // 1.4 / 0.2 = 7 is no real scale error: it is kept at the most believable, 2.
  expect(tracking.scale).toEqual({ factor: 2, engine_height_m: 0.2, real_height_m: 1.4, clamped: true });
  await phone.close();
  await vr.close();
});

test('the link can give the phone its real height', async ({ browser }) => {
  const { phone, vr } = await phoneAndHeadset(browser, '/?height=1.2');
  await holdStill(phone, { x: 0, y: 0.8, z: 1.6 }, 1700);
  await engineFrame(phone, { x: 0.4, y: 0.8, z: 1.6 });

  await expect(vr.getByTestId('marker-position')).toHaveText('0.60, 1.20, 1.60 m');
  await phone.close();
  await vr.close();
});

test('when the scale is measured the view does not jump: only the height rises to the real one', async ({ browser }) => {
  const { phone, vr } = await phoneAndHeadset(browser);
  // The person has stepped 0.3 m by 8th Wall's measure before the scale is known.
  await holdStill(phone, { x: 0.3, y: 0.7, z: 1.6 }, 1700);
  await engineFrame(phone, { x: 0.3, y: 0.7, z: 1.6 });
  await expect(vr.getByTestId('marker-position')).toHaveText('0.30, 1.40, 1.60 m');

  // From there, half a metre by 8th Wall is a metre in the room.
  await engineFrame(phone, { x: 0.8, y: 0.7, z: 1.6 });
  await expect(vr.getByTestId('marker-position')).toHaveText('1.30, 1.40, 1.60 m');
  await phone.close();
  await vr.close();
});

test('after a restart the room is lined up and the new scale takes over without a jump', async ({ browser }) => {
  const { phone, vr } = await phoneAndHeadset(browser);
  await holdStill(phone, { x: 0, y: 0.7, z: 1.6 }, 1700);
  await engineFrame(phone, { x: 0.25, y: 0.7, z: 1.6 });
  await expect(vr.getByTestId('marker-position')).toHaveText('0.50, 1.40, 1.60 m');
  // Lost; 8th Wall restarts 0.3 m from its start by its own measure, now nearer the truth.
  await engineFrame(phone, { x: 9, y: 9, z: 9 }, undefined, INITIALIZING);
  await holdStill(phone, { x: 0.3, y: 1.4, z: 1.6 }, 1700);

  // Lined up with the last good place, at the real height, with no jump when the scale changed.
  await expect(vr.getByTestId('marker-position')).toHaveText('0.50, 1.40, 1.60 m');
  // The new scale is 1: a 0.4 m move is 0.4 m.
  await engineFrame(phone, { x: 0.7, y: 1.4, z: 1.6 });
  await expect(vr.getByTestId('marker-position')).toHaveText('0.90, 1.40, 1.60 m');
  await phone.close();
  await vr.close();
});

test('a height given once in the link is kept on the phone', async ({ page }) => {
  await useFakeEngine(page);
  await page.goto('/?height=1.2');
  await page.goto('/');
  await page.getByRole('button', { name: 'Connect phone', exact: true }).click();
  await closeMap(page);
  await holdStill(page, { x: 0, y: 0.6, z: 1.6 }, 1700);

  const tracking = (await downloadReport(page)).motion.tracking;
  expect(tracking.scale).toEqual({ factor: 2, engine_height_m: 0.6, real_height_m: 1.2, clamped: false });
});
