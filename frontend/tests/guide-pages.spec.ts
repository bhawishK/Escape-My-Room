import { expect, test, type Page } from '@playwright/test';

// Guiding from the dollhouse (#248) on the real pages: the headset's pointed spot reaches the
// phone's room view; the phone's facing reaches the headset's figure of it, as a view cone.

/** Opens the headset page; its socket is passed through, and the test can speak on it. */
async function headset(page: Page): Promise<(message: object) => void> {
  let speak: ((message: object) => void) | null = null;
  await page.routeWebSocket(/\/api\/ws/, socket => {
    const server = socket.connectToServer();
    speak = message => server.send(JSON.stringify(message));
  });
  await page.goto('/quest/');
  await page.getByRole('button', { name: 'Connect headset', exact: true }).click();
  await expect(page.getByTestId('connection')).toHaveText('Connected · VR headset');
  return message => speak!(message);
}

test('the spot the headset points at reaches the phone\'s room view, and goes when it stops', async ({ browser, page }) => {
  const send = await headset(page);
  const phone = await browser.newPage({ viewport: { width: 390, height: 844 } });
  await phone.goto('/');
  await phone.getByRole('button', { name: 'Connect phone', exact: true }).click();
  await expect(phone.getByTestId('connection')).toHaveText('Connected · Phone');
  const scene = phone.locator('#scene');

  send({ type: 'guide', sequence: 1001, spot: { x: 1.5, y: 0, z: -0.8 } });
  await expect(scene).toHaveAttribute('data-guide', '1.50,-0.80');
  send({ type: 'guide', sequence: 1002, spot: null });
  await expect(scene).toHaveAttribute('data-guide', '');

  // A spot that stops coming, as when the headset's tab freezes, goes by itself.
  send({ type: 'guide', sequence: 1003, spot: { x: 0.2, y: 0, z: 0.4 } });
  await expect(scene).toHaveAttribute('data-guide', '0.20,0.40');
  await expect(scene).toHaveAttribute('data-guide', '', { timeout: 4_000 });
  await phone.close();
});

test('the phone\'s facing turns its figure, and so its view cone, on the headset', async ({ page, baseURL }) => {
  await headset(page);
  // The phone, as its socket: tracked, standing in the room, facing one way then another.
  const phone = new WebSocket(`${baseURL!.replace('http', 'ws')}/api/ws?role=mobile_master`);
  await new Promise(resolve => phone.addEventListener('open', resolve, { once: true }));
  const presence = (sequence: number, heading: number) => phone.send(JSON.stringify({
    type: 'presence', sequence, tracking_status: 'tracked', position: { x: 0.3, y: 0, z: -0.2 }, heading,
  }));
  const scene = page.getByTestId('quest-scene');
  presence(1, 0.5);
  await expect(scene).toHaveAttribute('data-phone-shown', 'true');
  const first = Number(await scene.getAttribute('data-phone-facing'));
  presence(2, 1.5);
  await expect.poll(async () => Number(await scene.getAttribute('data-phone-facing'))).toBeCloseTo(first + 1, 2);
  phone.close();
});
