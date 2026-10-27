import { type Page, expect, test } from '@playwright/test';
import { readFileSync, readdirSync } from 'node:fs';
import { join } from 'node:path';
import * as THREE from 'three';
import { fakeCameras } from './fixtures/cameras';
import { engineCalls, engineFrame, useFakeEngine } from './fixtures/fake-engine';

// A room whose look is a Gaussian splat (#92).
const SPLAT_ROOM = 'http://127.0.0.1:8774';

async function openPhone(page: Page, url: string): Promise<void> {
  await page.goto(url);
  await page.getByRole('button', { name: 'Connect phone', exact: true }).click();
  await expect(page.locator('#scene')).toHaveAttribute('data-view', 'phone');
}

/** One engine frame that also carries the engine's camera intrinsics. */
async function frameWithIntrinsics(page: Page, intrinsics: number[]): Promise<void> {
  await page.evaluate(intrinsics => {
    (window as unknown as { fakeEngine: { frame: (reality: unknown) => void } }).fakeEngine.frame({
      position: { x: 0, y: 1.5, z: 1.6 }, rotation: { x: 0, y: 0, z: 0, w: 1 }, intrinsics,
    });
  }, intrinsics);
}

test('with 8th Wall the phone shows its camera, with the room’s objects over it and not the splat room', async ({ browser }) => {
  const page = await browser.newPage({ viewport: { width: 390, height: 844 } });
  await useFakeEngine(page);
  await openPhone(page, SPLAT_ROOM);
  await expect(page.locator('#scene')).toHaveAttribute('data-mode', 'ar');
  await expect(page.locator('#scene')).toHaveAttribute('data-splat', 'hidden');
  const calls = await engineCalls(page);
  expect(calls.cameraFeed).toBe(true);
  // The engine works out its camera for the room view's screen and clipping distances.
  expect(calls.origins.at(-1)).toMatchObject({ cam: { pixelRectWidth: 390, pixelRectHeight: 844, nearClipPlane: 0.01, farClipPlane: 100 } });
  // The camera image shows through the room view.
  const look = await page.evaluate(() => {
    const engine = document.getElementById('engine-canvas') as HTMLCanvasElement;
    return {
      scene: getComputedStyle(document.getElementById('scene')!).backgroundColor,
      engineAbove: Number(getComputedStyle(engine).zIndex) > 0,
      engineSize: [engine.width, engine.height],
    };
  });
  expect(look).toEqual({ scene: 'rgba(0, 0, 0, 0)', engineAbove: true, engineSize: [390, 844] });
  await page.close();
});

test('the overlay is projected with the engine’s own camera intrinsics', async ({ browser }) => {
  const page = await browser.newPage({ viewport: { width: 390, height: 844 } });
  await useFakeEngine(page);
  await openPhone(page, '/');
  // A camera with a narrower view than the room view's own 70°.
  const intrinsics = new THREE.PerspectiveCamera(48, 390 / 844, 0.01, 100).projectionMatrix.toArray();
  await frameWithIntrinsics(page, intrinsics);
  await expect(page.locator('#scene')).toHaveAttribute('data-projection', intrinsics.map(value => value.toFixed(4)).join(','));
  await page.close();
});

test('counting steps, the phone keeps today’s room view of the splat, with no camera', async ({ browser }) => {
  const page = await browser.newPage({ viewport: { width: 390, height: 844 } });
  await useFakeEngine(page);
  await openPhone(page, `${SPLAT_ROOM}/?tracking=steps`);
  await expect(page.locator('#scene')).toHaveAttribute('data-mode', 'vr');
  await expect(page.locator('#scene')).toHaveAttribute('data-splat', 'shown');
  await expect(page.getByRole('button', { name: 'Show room model', exact: true })).toBeHidden();
  const calls = await engineCalls(page);
  expect(calls.runs).toBe(0);
  expect(calls.cameraFeed).toBe(false);
  await expect(page.locator('#scene')).not.toHaveAttribute('data-projection', /./);
  await page.close();
});

test('the room model can be shown faintly over the camera to check the alignment', async ({ browser }) => {
  const page = await browser.newPage({ viewport: { width: 390, height: 844 } });
  await useFakeEngine(page);
  await openPhone(page, SPLAT_ROOM);
  await page.getByRole('button', { name: 'Show room model', exact: true }).click();
  await expect(page.locator('#scene')).toHaveAttribute('data-mode', 'ghost');
  await expect(page.locator('#scene')).toHaveAttribute('data-splat', 'ghost');
  await page.getByRole('button', { name: 'Hide room model', exact: true }).click();
  await expect(page.locator('#scene')).toHaveAttribute('data-mode', 'ar');
  await expect(page.locator('#scene')).toHaveAttribute('data-splat', 'hidden');
  await page.close();
});

test('while the gaze cursor has the camera the phone shows the room model, not a frozen camera image', async ({ browser }) => {
  const page = await browser.newPage({ viewport: { width: 390, height: 844 } });
  await useFakeEngine(page);
  await page.addInitScript(fakeCameras);
  // The face model stays downloading, so the gaze cursor keeps the front camera until it is stopped.
  await page.context().route('**/face_landmarker.task', () => undefined);
  await openPhone(page, SPLAT_ROOM);
  await engineFrame(page, { x: 0.5, y: 1.5, z: 1 });
  await page.getByRole('button', { name: 'Gaze cursor', exact: true }).click();
  await expect(page.locator('#scene')).toHaveAttribute('data-mode', 'vr');
  await expect(page.locator('#scene')).toHaveAttribute('data-splat', 'shown');
  await page.getByRole('button', { name: 'Stop gaze cursor', exact: true }).click();
  await expect(page.locator('#scene')).toHaveAttribute('data-mode', 'ar');
  await page.close();
});

test('the tracking summary and Send log record whether the phone showed AR or the room model', async ({ page }) => {
  await useFakeEngine(page);
  await openPhone(page, '/');
  await engineFrame(page, { x: 0, y: 1.5, z: 1.6 });
  await page.getByRole('button', { name: 'Send log', exact: true }).click();
  await expect(page.getByTestId('view-status')).toHaveText(/^Log sent/);
  const folder = join(process.env.ESCAPE_ROOM_TEST_DATA!, '8771', 'movement-logs');
  const newest = readdirSync(folder).filter(name => name.endsWith('.json')).sort().at(-1)!;
  const log = JSON.parse(readFileSync(join(folder, newest), 'utf-8'));
  expect(log.tracking.view_mode).toBe('ar');
  const events = log.entries.filter((entry: { kind: string }) => entry.kind === 'event').map((entry: { name: string; detail: string }) => `${entry.name}: ${entry.detail}`);
  expect(events).toContain('view: ar');
});
