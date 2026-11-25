import { expect, test, type Page } from '@playwright/test';

// Guiding on the real pages: the exit the headset chooses gives the phone its way out (#283); the
// phone's facing reaches the headset's figure of it, as a view cone (#248).

/** The splat room's server: its layout has a door on its +x wall, door_0 (#280). */
const SPLAT_ROOM = 'http://127.0.0.1:8774';

/** Opens the headset page; its socket is passed through, and the test can speak on it. */
async function headset(page: Page, origin = ''): Promise<(message: object) => void> {
  let speak: ((message: object) => void) | null = null;
  await page.routeWebSocket(/\/api\/ws/, socket => {
    const server = socket.connectToServer();
    speak = message => server.send(JSON.stringify(message));
  });
  await page.goto(`${origin}/quest/`);
  await page.getByRole('button', { name: 'Connect headset', exact: true }).click();
  await expect(page.getByTestId('connection')).toHaveText('Connected · VR headset');
  return message => speak!(message);
}

test('the exit the headset chooses gives the phone chevrons and the distance, until it is out', async ({ browser, page }) => {
  const send = await headset(page, SPLAT_ROOM);
  const phone = await browser.newPage({ viewport: { width: 390, height: 844 } });
  // The phone's own socket, so the test can say where it stands.
  let say: ((message: object) => void) | null = null;
  await phone.routeWebSocket(/\/api\/ws/, socket => {
    const server = socket.connectToServer();
    say = message => server.send(JSON.stringify(message));
  });
  await phone.goto(`${SPLAT_ROOM}/`);
  await phone.getByRole('button', { name: 'Connect phone', exact: true }).click();
  await expect(phone.getByTestId('connection')).toHaveText('Connected · Phone');
  const scene = phone.locator('#scene');
  const line = phone.getByTestId('exit-line');
  const stand = (sequence: number, x: number, z: number) => say!({
    type: 'presence', sequence: 1000 + sequence, tracking_status: 'tracked', position: { x, y: 1.4, z }, heading: 0,
  });
  stand(1, -1, -1);

  // Nothing before the commander confirms an exit.
  await expect(line).toBeHidden();
  await expect(scene).toHaveAttribute('data-route', '');
  send({ type: 'guide_exit', room_version: 1, exit: 'door_0' });
  await expect(scene).toHaveAttribute('data-route', 'routing');
  await expect(line).toHaveText(/^Exit \d\.\d m · follow the arrows$/);
  expect(Number(await scene.getAttribute('data-chevrons'))).toBeGreaterThan(2);

  // At the door, it says so, and the chevrons go.
  stand(2, 0.8, 0.1);
  await expect(line).toHaveText("You're out");
  await expect(scene).toHaveAttribute('data-chevrons', '0');

  // The commander stops guiding: it all goes.
  send({ type: 'guide_exit', room_version: 1, exit: null });
  await expect(line).toBeHidden();
  await expect(scene).toHaveAttribute('data-route', '');
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
