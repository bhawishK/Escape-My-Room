import { expect, test } from '@playwright/test';

test('explicit simulator movement crosses Python into a separate solver view', async ({ browser }) => {
  const master = await browser.newPage();
  const solver = await browser.newPage();
  await master.goto('/');
  await master.getByLabel('Pose input').selectOption('simulator');
  await master.getByRole('button', { name: 'Create session' }).click();
  await expect(master.getByTestId('connection')).toHaveText('Connected · Mobile master');
  const session = await master.getByLabel('Session ID').inputValue();
  await solver.goto(`/?session=${session}`);
  await solver.getByRole('button', { name: 'Join as solver' }).click();
  await expect(solver.getByTestId('connection')).toHaveText('Connected · VR solver');
  await master.getByLabel('Simulator X (meters)').fill('0.75');
  await master.getByLabel('Simulator Y (meters)').fill('0.20');
  await master.getByLabel('Simulator Z (meters)').fill('-0.40');
  await master.getByRole('button', { name: 'Send simulated pose' }).click();
  await expect(solver.getByTestId('marker-position')).toHaveText('0.75, 0.20, -0.40 m');
  await expect(solver.getByTestId('tracking')).toContainText('SIMULATED');
  await expect(master.getByTestId('marker-position')).toHaveText('0.75, 0.20, -0.40 m');
  await master.getByRole('button', { name: 'Leave session' }).click();
  await expect(solver.getByTestId('tracking')).toContainText('Lost');
  await master.close();
  await solver.close();
});

test('mobile-sized view joins with unavailable WebXR and no simulated tracking', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.addInitScript(() => Object.defineProperty(navigator, 'xr', { value: undefined }));
  await page.goto('/');
  await expect(page.locator('#xr-support')).toContainText('physical phone tracking is pending');
  await page.getByRole('button', { name: 'Create session' }).click();
  await expect(page.getByTestId('connection')).toHaveText('Connected · Mobile master');
  await expect(page.getByTestId('tracking')).toHaveText('Inactive · no positional input');
  await expect(page.getByTestId('marker-position')).toHaveText('No accepted position');
  await expect(page.locator('#simulator')).toBeHidden();
  await page.getByRole('button', { name: 'Enter AR', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText('WebXR is unavailable');
  await expect(page.getByRole('button', { name: 'Leave session' })).toBeEnabled();
});

test('denied XR permission explains recovery and preserves the connected view', async ({ page }) => {
  await page.addInitScript(() => Object.defineProperty(navigator, 'xr', { value: {
    isSessionSupported: async () => true,
    requestSession: async () => { throw new DOMException('Denied for test', 'NotAllowedError'); },
  } }));
  await page.goto('/');
  await page.getByRole('button', { name: 'Create session' }).click();
  await expect(page.getByTestId('connection')).toContainText('Connected');
  await page.getByRole('button', { name: 'Enter AR', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText('XR permission was denied');
  await expect(page.getByTestId('connection')).toContainText('Connected');
});

test('solver can retry in the same session after its initial WebSocket fails', async ({ page, request }) => {
  const session = await (await request.post('/api/sessions')).json() as { session_id: string };
  let blockSocket = true;
  await page.routeWebSocket(/\/api\/sessions\/.*\/ws/, socket => {
    if (blockSocket) socket.close({ code: 1008, reason: 'Initial connection failure for test' });
    else socket.connectToServer();
  });
  await page.goto(`/?session=${session.session_id}`);
  await page.getByRole('button', { name: 'Join as solver' }).click();
  await expect(page.getByRole('alert')).toContainText('Connection failed');
  await expect(page.getByRole('button', { name: 'Join as solver' })).toBeEnabled();
  blockSocket = false;
  await page.getByRole('button', { name: 'Join as solver' }).click();
  await expect(page.getByTestId('connection')).toHaveText('Connected · VR solver');
  await expect(page.getByLabel('Session ID')).toHaveValue(session.session_id);
});
