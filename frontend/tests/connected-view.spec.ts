import { expect, test } from '@playwright/test';

test('phone sees VR connect and disconnect without session IDs or simulator controls', async ({ browser }) => {
  const phone = await browser.newPage({ viewport: { width: 390, height: 844 } });
  const vr = await browser.newPage();
  await phone.goto('/');
  await phone.getByRole('button', { name: 'Connect phone', exact: true }).click();
  await expect(phone.getByTestId('connection')).toHaveText('Connected · Phone');
  await expect(phone.getByTestId('vr-status')).toHaveText('Waiting for VR device');
  await expect(phone.getByLabel('Session ID')).toHaveCount(0);
  await expect(phone.getByLabel('Pose input')).toHaveCount(0);
  await expect(phone.locator('#simulator')).toHaveCount(0);
  await vr.goto('/');
  await vr.getByRole('button', { name: 'Connect VR headset', exact: true }).click();
  await expect(vr.getByTestId('connection')).toHaveText('Connected · VR headset');
  await expect(phone.getByTestId('vr-status')).toHaveText('VR device connected');
  await vr.getByRole('button', { name: 'Disconnect', exact: true }).click();
  await expect(phone.getByTestId('vr-status')).toHaveText('Waiting for VR device');
  await phone.close();
  await vr.close();
});

test('the phone offers camera tracking and the headset offers VR', async ({ browser }) => {
  const phone = await browser.newPage({ viewport: { width: 390, height: 844 } });
  const vr = await browser.newPage();
  // iPhone browsers expose no WebXR; the phone page must not depend on it.
  await phone.addInitScript(() => Object.defineProperty(navigator, 'xr', { value: undefined }));
  await phone.goto('/');
  await phone.getByRole('button', { name: 'Connect phone', exact: true }).click();
  await expect(phone.getByTestId('connection')).toHaveText('Connected · Phone');
  await expect(phone.getByRole('button', { name: 'Start tracking', exact: true })).toBeEnabled();
  await expect(phone.getByRole('button', { name: 'Calibrate camera', exact: true })).toBeEnabled();
  await expect(phone.getByRole('button', { name: 'Enter VR', exact: true })).toBeHidden();
  await expect(phone.getByTestId('marker-position')).toHaveText('No accepted position');
  await vr.goto('/');
  await vr.getByRole('button', { name: 'Connect VR headset', exact: true }).click();
  await expect(vr.getByRole('button', { name: 'Enter VR', exact: true })).toBeVisible();
  await expect(vr.getByRole('button', { name: 'Start tracking', exact: true })).toBeHidden();
  await phone.close();
  await vr.close();
});

test('Quest entry requests VR and reports permission denial without disconnecting', async ({ page }) => {
  await page.addInitScript(() => Object.defineProperty(navigator, 'xr', { value: {
    isSessionSupported: async () => true,
    requestSession: async (mode: string) => {
      document.documentElement.dataset.requestedMode = mode;
      throw new DOMException('Denied for test', 'NotAllowedError');
    },
  } }));
  await page.goto('/');
  await page.getByRole('button', { name: 'Connect VR headset', exact: true }).click();
  await page.getByRole('button', { name: 'Enter VR', exact: true }).click();
  await expect(page.locator('html')).toHaveAttribute('data-requested-mode', 'immersive-vr');
  await expect(page.getByRole('alert')).toContainText('XR permission was denied');
  await expect(page.getByTestId('connection')).toHaveText('Connected · VR headset');
});

test('phone and headset show the same prepared room', async ({ browser }) => {
  const phone = await browser.newPage({ viewport: { width: 390, height: 844 } });
  const vr = await browser.newPage();
  await phone.goto('/');
  await vr.goto('/');
  await phone.getByRole('button', { name: 'Connect phone', exact: true }).click();
  await vr.getByRole('button', { name: 'Connect VR headset', exact: true }).click();
  const ready = 'Room version 1 · floor, desk, cabinet, box (movable)';
  await expect(phone.getByTestId('room-status')).toHaveText(ready);
  await expect(vr.getByTestId('room-status')).toHaveText(ready);
  await expect(phone.getByRole('alert')).toBeHidden();
  await phone.close();
  await vr.close();
});

test('confirming alignment marks this device aligned', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('button', { name: 'Connect VR headset', exact: true }).click();
  await expect(page.getByTestId('alignment-status')).toHaveText('Not aligned');
  await page.locator('#confirm-alignment').click();
  await expect(page.getByTestId('alignment-status')).toHaveText('Aligned · yaw 0.00 rad · origin 0.00, 0.00, 0.00');
  await expect(page.locator('#scene')).toHaveAttribute('data-view', 'calibrated');
});

test('failed initial socket can retry with one role button', async ({ page }) => {
  let blockSocket = true;
  await page.routeWebSocket(/\/api\/ws/, socket => {
    if (blockSocket) socket.close({ code: 1008, reason: 'Initial connection failure for test' });
    else socket.connectToServer();
  });
  await page.goto('/');
  await page.getByRole('button', { name: 'Connect VR headset', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText('Connection failed');
  await expect(page.getByRole('button', { name: 'Connect VR headset', exact: true })).toBeEnabled();
  blockSocket = false;
  await page.getByRole('button', { name: 'Connect VR headset', exact: true }).click();
  await expect(page.getByTestId('connection')).toHaveText('Connected · VR headset');
});
