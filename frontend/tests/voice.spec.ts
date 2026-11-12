import { type Browser, type Page, expect, test } from '@playwright/test';
import { voiceLine, voiceNote, type VoiceStatus } from '../src/voice';

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

/** Remembers every microphone the page opens, to see later whether each is running or muted. */
async function watchMicrophones(page: Page): Promise<void> {
  await page.addInitScript(() => {
    const opened: MediaStream[] = [];
    Object.assign(window, { openedMicrophones: opened });
    const real = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
    navigator.mediaDevices.getUserMedia = async constraints => {
      const stream = await real(constraints);
      opened.push(stream);
      return stream;
    };
  });
}

/** The page's microphones that are still open: "sending" or "muted" for each. */
const microphones = (page: Page) => page.evaluate(() =>
  (window as unknown as { openedMicrophones: MediaStream[] }).openedMicrophones
    .flatMap(stream => stream.getTracks())
    .filter(track => track.readyState === 'live')
    .map(track => (track.enabled ? 'sending' : 'muted')));

/** The call is up and the other person's audio is arriving. */
async function expectTalking(page: Page): Promise<void> {
  await expect(page.getByTestId('voice-status')).toHaveText('Voice connected · direct', { timeout: 15_000 });
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

test('a mute silences this person, shows on both pages, and keeps the call', async ({ browser }) => {
  const phone = await connectPhone(browser);
  const headset = await browser.newPage(MICROPHONE);
  await watchMicrophones(headset);
  await connectHeadset(headset);
  // Mute is only offered once voice is on.
  await expect(headset.getByRole('button', { name: 'Mute', exact: true })).toBeHidden();
  await phone.locator('#hud-voice').click();
  await headset.getByRole('button', { name: 'Start voice', exact: true }).click();
  await expectTalking(phone);
  await expectTalking(headset);

  await headset.getByRole('button', { name: 'Mute', exact: true }).click();
  await expect(headset.getByTestId('voice-status')).toHaveText('Voice connected · direct · you are muted');
  await expect(phone.getByTestId('voice-status')).toHaveText('Voice connected · direct · the headset is muted');
  // The room view covers the phone's page, so it shows the line too.
  await expect(phone.getByTestId('hud-voice-status')).toHaveText('Voice connected · direct · the headset is muted');
  // The headset's microphone is switched off, not closed: it sends silence, and the call stays.
  expect(await microphones(headset)).toEqual(['muted']);
  await expect(headset.getByTestId('voice-status')).toHaveAttribute('data-voice', 'connected');

  await headset.getByRole('button', { name: 'Unmute', exact: true }).click();
  await expect(phone.getByTestId('voice-status')).toHaveText('Voice connected · direct');
  expect(await microphones(headset)).toEqual(['sending']);
  await expectTalking(phone);
  await phone.close();
  await headset.close();
});

test('stopping voice and disconnecting each let the microphone go', async ({ browser }) => {
  const phone = await connectPhone(browser);
  const headset = await browser.newPage(MICROPHONE);
  await watchMicrophones(headset);
  const live = async () => (await microphones(headset)).length;
  await connectHeadset(headset);
  await phone.locator('#hud-voice').click();
  await headset.getByRole('button', { name: 'Start voice', exact: true }).click();
  await expectTalking(headset);
  expect(await live()).toBe(1);

  await headset.getByRole('button', { name: 'Stop voice', exact: true }).click();
  await expect(headset.getByTestId('voice-status')).toHaveText('Voice off');
  expect(await live()).toBe(0);

  await headset.getByRole('button', { name: 'Start voice', exact: true }).click();
  await expectTalking(headset);
  expect(await live()).toBe(1);
  await headset.getByRole('button', { name: 'Disconnect', exact: true }).click();
  await expect(headset.getByTestId('voice-status')).toHaveText('Voice off');
  expect(await live()).toBe(0);
  await phone.close();
  await headset.close();
});

test('a refused microphone says why, leaves the session working, and can be tried again', async ({ browser }) => {
  const phone = await connectPhone(browser);
  const headset = await browser.newPage(MICROPHONE);
  // The first request is refused, as when the person taps Don't Allow; the next is allowed.
  await headset.addInitScript(() => {
    const real = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
    let refused = false;
    navigator.mediaDevices.getUserMedia = async constraints => {
      if (!refused) {
        refused = true;
        throw new DOMException('Permission denied', 'NotAllowedError');
      }
      return real(constraints);
    };
  });
  await connectHeadset(headset);
  await phone.locator('#hud-voice').click();
  await headset.getByRole('button', { name: 'Start voice', exact: true }).click();
  await expect(headset.getByTestId('voice-status')).toHaveText(
    'Voice off · The microphone was not allowed. Allow it for this site in the browser, then press Start voice again.',
  );
  // The session is untouched: still connected, the room there, and the phone still waiting.
  await expect(headset.getByTestId('connection')).toHaveText('Connected · VR headset');
  await expect(headset.getByTestId('room-status')).toHaveText(/^Room ready/);
  await expect(phone.getByTestId('voice-status')).toHaveText('Voice on · waiting for the headset to start voice');

  await headset.getByRole('button', { name: 'Start voice', exact: true }).click();
  await expectTalking(headset);
  await expectTalking(phone);
  await phone.close();
  await headset.close();
});

test('a call that finds no path is tried once more, then both pages say it failed', async ({ browser }) => {
  test.setTimeout(90_000);
  const phone = await connectPhone(browser);
  const headset = await browser.newPage(MICROPHONE);
  // Neither browser learns where the other is, as on two networks with no path between them.
  for (const page of [phone, headset]) {
    await page.addInitScript(() => { RTCPeerConnection.prototype.addIceCandidate = async () => undefined; });
  }
  await phone.reload();
  await phone.getByRole('button', { name: 'Connect phone', exact: true }).click();
  await connectHeadset(headset);
  await phone.locator('#hud-voice').click();
  await headset.getByRole('button', { name: 'Start voice', exact: true }).click();
  await expect(phone.getByTestId('voice-status')).toHaveText('Voice connecting…');
  for (const page of [phone, headset]) {
    await expect(page.getByTestId('voice-status')).toHaveText(
      'Voice failed · The two devices found no way to reach each other. Stop voice and start it again, or try another network.',
      { timeout: 45_000 },
    );
  }
  // The session carries on, and stopping voice clears the failure.
  await expect(headset.getByTestId('connection')).toHaveText('Connected · VR headset');
  await headset.getByRole('button', { name: 'Stop voice', exact: true }).click();
  await expect(headset.getByTestId('voice-status')).toHaveText('Voice off');
  await phone.close();
  await headset.close();
});

test('each page reports how its call connected, using the servers from the settings', async ({ browser }) => {
  const phone = await connectPhone(browser);
  const headset = await browser.newPage(MICROPHONE);
  const asked: string[] = [];
  headset.on('request', request => { if (request.url().endsWith('/api/voice/config')) asked.push(request.method()); });
  await connectHeadset(headset);
  await phone.locator('#hud-voice').click();
  await headset.getByRole('button', { name: 'Start voice', exact: true }).click();
  await expectTalking(headset);
  await expectTalking(phone);
  expect(asked).toEqual(['GET']);
  // Two pages on one machine reach each other straight, without a relay.
  await expect(headset.getByTestId('voice-status')).toHaveAttribute('data-path', 'direct');
  interface Report {
    voice: { phase: string; path: { local: string; remote: string; relayed: boolean } | null; ice_servers: string[]; relay_only: boolean };
  }
  const read = async () => (JSON.parse(await headset.getByTestId('report').textContent() ?? '{}') as Report).voice;
  await expect.poll(async () => (await read()).path?.relayed).toBe(false);
  const voice = await read();
  expect(voice.phase).toBe('connected');
  expect(['host', 'srflx', 'prflx']).toContain(voice.path?.local);
  expect(voice.ice_servers).toEqual(['stun:stun.l.google.com:19302']);
  expect(voice.relay_only).toBe(false);
  await phone.close();
  await headset.close();
});

test('the line inside VR says what the person needs to know about the call', () => {
  const status = (changes: Partial<VoiceStatus>): VoiceStatus => ({
    phase: 'connected', problem: null, receiving: true, muted: false, peerMuted: false, path: null, ...changes,
  });
  const note = (changes: Partial<VoiceStatus>) => voiceNote(status(changes), 'the phone', 'press B or Y');
  expect(note({})).toBe('Voice connected');
  expect(note({ peerMuted: true })).toBe('Voice connected · the phone is muted');
  // Being muted matters more than who else is.
  expect(note({ muted: true, peerMuted: true })).toBe('You are muted · press B or Y to unmute');
  expect(note({ phase: 'waiting' })).toBe('Voice · waiting for the phone');
  expect(note({ phase: 'connecting' })).toBe('Voice connecting…');
  expect(note({ phase: 'failed', problem: 'No path.' })).toBe('Voice failed · leave VR to start it again');
  // Voice that was never started says nothing; voice that stopped for a reason does.
  expect(note({ phase: 'off' })).toBeNull();
  expect(note({ phase: 'off', problem: 'The microphone was not allowed.' })).toBe('Voice is off');
  // The page's own line names the path once it is known.
  const relayed = { local: 'relay', remote: 'srflx', relayed: true, protocol: 'udp' };
  expect(voiceLine(status({ path: relayed, muted: true }), 'the phone')).toBe('Voice connected · relayed · you are muted');
});
