import { type Browser, type Page, expect, test } from '@playwright/test';

// The voice call between the phone's page and the headset's page (#13, #170). Chromium plays a
// test tone as each page's microphone, so real audio flows between the two pages over WebRTC.
// Each page is given the microphone permission outright: only then does Chromium offer every
// local address, the loopback one included, so the call connects on a machine with no network
// or behind a VPN that drops traffic to itself.
test.use({
  launchOptions: {
    args: [
      '--use-fake-device-for-media-stream',
      '--use-fake-ui-for-media-stream',
      '--allow-loopback-in-peer-connection',
    ],
  },
});
const MICROPHONE = { permissions: ['microphone'] };

async function connectPhone(browser: Browser): Promise<Page> {
  const phone = await browser.newPage({ viewport: { width: 390, height: 844 }, ...MICROPHONE });
  await phone.goto('/');
  await phone.getByRole('button', { name: 'Connect phone', exact: true }).click();
  await expect(phone.getByTestId('connection')).toHaveText('Connected · Phone');
  return phone;
}

async function connectHeadset(headset: Page): Promise<void> {
  await headset.goto('/quest/');
  await headset.getByRole('button', { name: 'Connect headset', exact: true }).click();
  await expect(headset.getByTestId('connection')).toHaveText('Connected · VR headset');
}

/** The call is up and the other person's audio is arriving. */
async function expectTalking(page: Page): Promise<void> {
  await expect(page.getByTestId('voice-status')).toHaveText('Voice connected', { timeout: 15_000 });
  await expect(page.getByTestId('voice-status')).toHaveAttribute('data-receiving', 'true', { timeout: 15_000 });
}

/** Whether the other person is still playing on this page. */
const speakerLive = (page: Page) => page.evaluate(() => {
  const speaker = document.querySelector<HTMLAudioElement>('[data-testid="voice-speaker"]');
  return (speaker?.srcObject as MediaStream | null)?.getAudioTracks().some(track => track.readyState === 'live') ?? false;
});

test('the phone and the headset hear each other once both start voice', async ({ browser }) => {
  const phone = await connectPhone(browser);
  const headset = await browser.newPage(MICROPHONE);
  await connectHeadset(headset);
  await expect(phone.getByTestId('voice-status')).toHaveText('Voice off');

  // The room view covers the phone's page, so its button is in the room view.
  await phone.locator('#hud-voice').click();
  await expect(phone.getByTestId('voice-status')).toHaveText('Voice on · waiting for the headset to start voice');
  await expect(phone.locator('#hud-voice')).toHaveText('Stop voice');

  await headset.getByRole('button', { name: 'Start voice', exact: true }).click();
  await expectTalking(phone);
  await expectTalking(headset);
  expect(await speakerLive(phone)).toBe(true);
  expect(await speakerLive(headset)).toBe(true);
  await phone.close();
  await headset.close();
});

test('the call comes back by itself when the other device reloads', async ({ browser }) => {
  const phone = await connectPhone(browser);
  const headset = await browser.newPage(MICROPHONE);
  await connectHeadset(headset);
  await phone.locator('#hud-voice').click();
  await headset.getByRole('button', { name: 'Start voice', exact: true }).click();
  await expectTalking(phone);

  await headset.reload();
  await expect(phone.getByTestId('voice-status')).toHaveText('Voice on · waiting for the headset to start voice');
  // Connecting again is enough: voice was on in that tab, and the phone presses nothing.
  await headset.getByRole('button', { name: 'Connect headset', exact: true }).click();
  await expectTalking(headset);
  await expectTalking(phone);
  await phone.close();
  await headset.close();
});

test('stopping voice ends the call for both, and starting again brings it back', async ({ browser }) => {
  const phone = await connectPhone(browser);
  const headset = await browser.newPage(MICROPHONE);
  await connectHeadset(headset);
  await phone.locator('#hud-voice').click();
  await headset.getByRole('button', { name: 'Start voice', exact: true }).click();
  await expectTalking(headset);

  await headset.getByRole('button', { name: 'Stop voice', exact: true }).click();
  await expect(headset.getByTestId('voice-status')).toHaveText('Voice off');
  await expect(phone.getByTestId('voice-status')).toHaveText('Voice on · waiting for the headset to start voice');
  expect(await speakerLive(phone)).toBe(false);

  await headset.getByRole('button', { name: 'Start voice', exact: true }).click();
  await expectTalking(phone);
  await expectTalking(headset);
  await phone.close();
  await headset.close();
});

test('the room still works while the two are talking', async ({ browser }) => {
  const phone = await connectPhone(browser);
  const headset = await browser.newPage(MICROPHONE);
  await connectHeadset(headset);
  await phone.locator('#hud-voice').click();
  await headset.getByRole('button', { name: 'Start voice', exact: true }).click();
  await expectTalking(phone);
  await expect(headset.getByTestId('room-status')).toHaveText(/^Room ready · version \d+$/);
  await expect(headset.getByTestId('phone-status')).toHaveText('Phone connected');
  // Leaving the session ends the call and the other person goes back to waiting.
  await headset.getByRole('button', { name: 'Disconnect', exact: true }).click();
  await expect(headset.getByTestId('voice-status')).toHaveText('Voice off');
  await expect(phone.getByTestId('voice-status')).toHaveText('Voice on · waiting for the headset to start voice');
  await phone.close();
  await headset.close();
});
