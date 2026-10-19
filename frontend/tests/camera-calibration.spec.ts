import { expect, test } from '@playwright/test';
import type { CameraCalibration } from '../src/protocol';
import { BOARD_CAMERA } from './fake-camera';

/*
 * Chromium's fake camera plays the calibration board in a series of tilts, rendered with
 * BOARD_CAMERA's known intrinsics. The page must recover them and save them with Python.
 */

test('calibrating the camera saves its intrinsics for this resolution', async ({ page, request }) => {
  test.setTimeout(60_000);
  await page.goto('/');
  await page.getByRole('button', { name: 'Connect phone', exact: true }).click();
  await page.getByRole('button', { name: 'Calibrate camera', exact: true }).click();
  await expect(page.getByTestId('tracking-status')).toContainText('Calibrating ·', { timeout: 20_000 });
  await expect(page.getByRole('button', { name: 'Start tracking', exact: true })).toBeDisabled();
  await expect(page.getByTestId('tracking-status')).toHaveText(/^Calibrated 640×360 · error \d\.\d\d px$/, { timeout: 40_000 });
  await expect(page.locator('#camera-preview')).toBeHidden();
  const saved = (await (await request.get('/api/tracking/cameras')).json() as { calibrations: CameraCalibration[] })
    .calibrations.find(item => item.width === 640 && item.height === 360);
  expect(saved).toBeDefined();
  expect(Math.abs(saved!.fx / BOARD_CAMERA.fx - 1)).toBeLessThan(0.02);
  expect(Math.abs(saved!.fy / BOARD_CAMERA.fy - 1)).toBeLessThan(0.02);
  expect(Math.abs(saved!.cx - BOARD_CAMERA.cx)).toBeLessThan(8);
  expect(Math.abs(saved!.cy - BOARD_CAMERA.cy)).toBeLessThan(8);
  expect(saved!.views).toBe(15);
});
