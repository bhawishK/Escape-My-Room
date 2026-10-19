import { expect, test, type Page } from '@playwright/test';

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

test('the phone opens the room full screen and the headset offers VR', async ({ browser }) => {
  const phone = await browser.newPage({ viewport: { width: 390, height: 844 } });
  const vr = await browser.newPage();
  // iPhone browsers expose no WebXR; the phone page must not depend on it.
  await phone.addInitScript(() => Object.defineProperty(navigator, 'xr', { value: undefined }));
  await phone.goto('/');
  await phone.getByRole('button', { name: 'Connect phone', exact: true }).click();
  await expect(phone.getByTestId('connection')).toHaveText('Connected · Phone');
  // The room fills the screen, looking from the floor center toward the desk.
  await expect(phone.locator('#scene')).toHaveClass(/room-view/);
  await expect(phone.locator('#scene')).toHaveAttribute('data-view', 'phone');
  expect(await phone.locator('#scene').boundingBox()).toEqual({ x: 0, y: 0, width: 390, height: 844 });
  await expect(phone.getByRole('button', { name: 'Turn with phone', exact: true })).toBeVisible();
  await expect(phone.getByRole('button', { name: 'Enter VR', exact: true })).toBeHidden();
  await expect(phone.getByTestId('view-status')).toHaveText('Turning off');
  // Close returns to the page; the room view opens again from the page.
  await phone.getByRole('button', { name: 'Close', exact: true }).click();
  await expect(phone.locator('#scene')).not.toHaveClass(/room-view/);
  await expect(phone.locator('#scene')).toHaveAttribute('data-view', 'overview');
  await phone.getByRole('button', { name: 'Open room view', exact: true }).click();
  await expect(phone.locator('#scene')).toHaveAttribute('data-view', 'phone');
  await vr.goto('/');
  await vr.getByRole('button', { name: 'Connect VR headset', exact: true }).click();
  await expect(vr.getByRole('button', { name: 'Enter VR', exact: true })).toBeVisible();
  await expect(vr.locator('#scene')).not.toHaveClass(/room-view/);
  await expect(vr.getByRole('button', { name: 'Open room view', exact: true })).toBeHidden();
  await phone.close();
  await vr.close();
});

test('turning with the phone follows its orientation sensor', async ({ page }) => {
  // The person allows motion access when the phone asks.
  await page.addInitScript(() => Object.assign(DeviceOrientationEvent, { requestPermission: async () => 'granted' }));
  await page.goto('/');
  await page.getByRole('button', { name: 'Connect phone', exact: true }).click();
  await page.getByRole('button', { name: 'Turn with phone', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Stop turning', exact: true })).toBeVisible();
  await expect(page.getByTestId('view-status')).toHaveText('Turning with the phone');
  await page.evaluate(() => window.dispatchEvent(new DeviceOrientationEvent('deviceorientation', { alpha: 0, beta: 90, gamma: 0 })));
  await page.getByRole('button', { name: 'Stop turning', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Turn with phone', exact: true })).toBeVisible();
  await expect(page.getByTestId('view-status')).toHaveText('Turning off');
});

test('a refused motion permission is explained', async ({ page }) => {
  // iPhone browsers ask for motion permission; this one says no.
  await page.addInitScript(() => Object.assign(DeviceOrientationEvent, { requestPermission: async () => 'denied' }));
  await page.goto('/');
  await page.getByRole('button', { name: 'Connect phone', exact: true }).click();
  await page.getByRole('button', { name: 'Turn with phone', exact: true }).click();
  await expect(page.getByTestId('view-status')).toHaveText(
    'Motion permission was denied. Allow motion access for this site, then try again.');
  await expect(page.getByRole('button', { name: 'Turn with phone', exact: true })).toBeVisible();
});

test('walking steps move the phone, and the headset sees where it went', async ({ browser }) => {
  const phone = await browser.newPage({ viewport: { width: 390, height: 844 } });
  const vr = await browser.newPage();
  // The person allows motion access when the phone asks.
  await phone.addInitScript(() => {
    for (const event of [DeviceOrientationEvent, DeviceMotionEvent]) Object.assign(event, { requestPermission: async () => 'granted' });
  });
  await vr.goto('/');
  await vr.getByRole('button', { name: 'Connect VR headset', exact: true }).click();
  await phone.goto('/');
  await phone.getByRole('button', { name: 'Connect phone', exact: true }).click();
  await phone.getByRole('button', { name: 'Walk with steps', exact: true }).click();
  await expect(phone.getByTestId('view-status')).toHaveText('Walking · 0 steps');
  await expect(vr.getByTestId('marker-position')).toHaveText('0.00, 1.50, 1.60 m');
  // Three seconds of a phone bouncing with each step, read 60 times a second.
  await phone.evaluate(() => new Promise<void>(resolve => {
    let index = 0;
    const timer = setInterval(() => {
      const up = 9.81 + 2.5 * Math.sin(2 * Math.PI * 1.8 * index / 60);
      window.dispatchEvent(new DeviceMotionEvent('devicemotion', {
        accelerationIncludingGravity: { x: 0, y: up, z: 0 }, rotationRate: { alpha: 0, beta: 0, gamma: 0 }, interval: 16,
      }));
      if (++index >= 180) {
        clearInterval(timer);
        resolve();
      }
    }, 1000 / 60);
  }));
  await expect(phone.getByTestId('view-status')).toHaveText(/Walking · \d+ steps/);
  const steps = Number((await phone.getByTestId('view-status').textContent())!.match(/\d+/)![0]);
  expect(steps).toBeGreaterThanOrEqual(3);
  // Without turning readings, steps go toward the desk, each 0.6 m, until the desk stops the third at z = -0.2.
  await expect(vr.getByTestId('marker-position')).toHaveText(`0.00, 1.50, ${(1.6 - 0.6 * Math.min(steps, 3)).toFixed(2)} m`);
  await phone.getByRole('button', { name: 'Back to start', exact: true }).click();
  await expect(vr.getByTestId('marker-position')).toHaveText('0.00, 1.50, 1.60 m');
  await phone.getByRole('button', { name: 'Stop walking', exact: true }).click();
  await expect(vr.getByTestId('tracking')).toHaveText('Inactive · no positional input');
  await phone.close();
  await vr.close();
});

test('a refused camera permission for the gaze cursor is explained', async ({ page }) => {
  await page.addInitScript(() => Object.defineProperty(navigator, 'mediaDevices', { value: {
    getUserMedia: async () => { throw new DOMException('Denied for test', 'NotAllowedError'); },
  } }));
  await page.goto('/');
  await page.getByRole('button', { name: 'Connect phone', exact: true }).click();
  await page.getByRole('button', { name: 'Gaze cursor', exact: true }).click();
  await expect(page.getByTestId('view-status')).toHaveText(
    'Camera permission was denied. Allow camera access for this site in the browser settings, then try again.');
  await expect(page.getByRole('button', { name: 'Gaze cursor', exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Calibrate', exact: true })).toBeHidden();
  await expect(page.getByLabel('Front camera')).toBeHidden();
});

/** Cameras that play a blank picture, remembering which way each was asked to face. */
function fakeCameras(): void {
  // The canvas is kept, so its track only ends when the page stops it.
  const opened: { facing: string; stream: MediaStream; canvas: HTMLCanvasElement }[] = [];
  Object.assign(window, { openedCameras: opened });
  Object.defineProperty(navigator.mediaDevices, 'getUserMedia', { value: async (constraints: MediaStreamConstraints) => {
    const canvas = document.createElement('canvas');
    canvas.width = 640;
    canvas.height = 480;
    canvas.getContext('2d')!.fillRect(0, 0, 640, 480);
    const stream = canvas.captureStream(10);
    opened.push({ facing: JSON.stringify((constraints.video as MediaTrackConstraints).facingMode), stream, canvas });
    return stream;
  } });
}
/** Which cameras are still running: "front", "back", or both. */
const liveCameras = (page: Page) => page.evaluate(() =>
  (window as unknown as { openedCameras: { facing: string; stream: MediaStream }[] }).openedCameras
    .filter(camera => camera.stream.getTracks().some(track => track.readyState === 'live'))
    .map(camera => (camera.facing.includes('environment') ? 'back' : 'front')));

test('a refused back camera for floor height is explained', async ({ page }) => {
  await page.addInitScript(() => Object.defineProperty(navigator, 'mediaDevices', { value: {
    getUserMedia: async () => { throw new DOMException('Denied for test', 'NotAllowedError'); },
  } }));
  await page.goto('/');
  await page.getByRole('button', { name: 'Connect phone', exact: true }).click();
  await page.getByRole('button', { name: 'Floor height', exact: true }).click();
  await expect(page.getByTestId('view-status')).toHaveText(
    'Camera permission was denied. Allow camera access for this site in the browser settings, then try again.');
  await expect(page.getByRole('button', { name: 'Floor height', exact: true })).toBeVisible();
  await expect(page.getByLabel('Back camera')).toBeHidden();
});

test('a depth model that cannot download is explained, and the back camera is released', async ({ page, context }) => {
  await context.route('**/metric3d-vit-small/**', route => route.abort());
  await page.addInitScript(fakeCameras);
  await page.goto('/');
  await page.getByRole('button', { name: 'Connect phone', exact: true }).click();
  await page.getByRole('button', { name: 'Floor height', exact: true }).click();
  await expect(page.getByTestId('view-status')).toContainText('The depth model could not load');
  await expect(page.getByLabel('Back camera')).toBeHidden();
  expect(await liveCameras(page)).toEqual([]);
  await expect(page.getByRole('button', { name: 'Floor height', exact: true })).toBeVisible();
});

test('the gaze cursor and floor height never run their cameras together', async ({ page, context }) => {
  // Both models stay downloading, so each feature keeps its camera open until it is stopped.
  await context.route('**/metric3d-vit-small/**', () => undefined);
  await context.route('**/face_landmarker.task', () => undefined);
  await page.addInitScript(fakeCameras);
  await page.goto('/');
  await page.getByRole('button', { name: 'Connect phone', exact: true }).click();
  await page.getByRole('button', { name: 'Floor height', exact: true }).click();
  await expect(page.getByLabel('Back camera')).toBeVisible();
  expect(await liveCameras(page)).toEqual(['back']);
  await page.getByRole('button', { name: 'Gaze cursor', exact: true }).click();
  await expect(page.getByLabel('Front camera')).toBeVisible();
  await expect(page.getByLabel('Back camera')).toBeHidden();
  expect(await liveCameras(page)).toEqual(['front']);
  await page.getByRole('button', { name: 'Floor height', exact: true }).click();
  await expect(page.getByLabel('Back camera')).toBeVisible();
  await expect(page.getByLabel('Front camera')).toBeHidden();
  expect(await liveCameras(page)).toEqual(['back']);
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
