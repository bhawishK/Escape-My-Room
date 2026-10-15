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

test('phone page stays usable when positional WebXR is unavailable', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.addInitScript(() => Object.defineProperty(navigator, 'xr', { value: undefined }));
  await page.goto('/');
  await page.getByRole('button', { name: 'Connect phone', exact: true }).click();
  await expect(page.getByTestId('connection')).toHaveText('Connected · Phone');
  await expect(page.getByTestId('marker-position')).toHaveText('No accepted position');
  await page.getByRole('button', { name: 'Enter AR', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText('WebXR is unavailable');
  await expect(page.getByRole('button', { name: 'Disconnect', exact: true })).toBeEnabled();
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
