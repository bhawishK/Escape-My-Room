import { expect, test, type Page } from '@playwright/test';
import { mkdirSync, rmSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { gzipSync } from 'node:zlib';

// Hazards on the headset page (#230): a finished hazard the headset adds plays its frames on the
// server's clock and hides the real object, in the splat room, with Spark.

const ORIGIN = 'http://127.0.0.1:8774';
const ASSET = 'hz_00c0ffee';
const FRAMES = 24;

/** A small SPZ (version 2) frame: an orange block of splats, a little taller each frame. */
function spzFrame(n: number): Buffer {
  const points: [number, number, number][] = [];
  for (let x = -0.1; x <= 0.1; x += 0.04) for (let y = 0; y <= 0.1 + n * 0.005; y += 0.04) for (let z = -0.1; z <= 0.1; z += 0.04) points.push([x, y, z]);
  const count = points.length;
  const header = Buffer.alloc(16);
  header.writeUInt32LE(0x5053474e, 0);
  header.writeUInt32LE(2, 4);
  header.writeUInt32LE(count, 8);
  header.writeUInt8(0, 12); // no spherical harmonics beyond colour
  header.writeUInt8(12, 13); // fractional bits
  const positions = Buffer.alloc(count * 9);
  points.forEach((point, i) => point.forEach((value, axis) => {
    const fixed = Math.round(value * 4096) & 0xffffff;
    positions.writeUIntLE(fixed, i * 9 + axis * 3, 3);
  }));
  const alphas = Buffer.alloc(count, 240);
  const colours = Buffer.alloc(count * 3);
  for (let i = 0; i < count; i++) colours.set([230, 140, 60], i * 3);
  const scales = Buffer.alloc(count * 3, Math.round((Math.log(0.02) + 10) * 16));
  const rotations = Buffer.alloc(count * 3, 128);
  return gzipSync(Buffer.concat([header, positions, alphas, colours, scales, rotations]));
}

/** A finished hazard kept where the splat room's server keeps them, on its box. */
function keepHazard(): void {
  const kept = join(process.env.ESCAPE_ROOM_TEST_DATA!, '8774', 'hazards', 'hazards', ASSET);
  rmSync(kept, { recursive: true, force: true });
  mkdirSync(join(kept, 'frames'), { recursive: true });
  for (let n = 0; n < FRAMES; n++) writeFileSync(join(kept, 'frames', `${String(n).padStart(3, '0')}.spz`), spzFrame(n));
  writeFileSync(join(kept, 'hazard.json'), JSON.stringify({
    id: ASSET,
    target: { entity: 'box' },
    hazard: 'catches fire',
    frames: FRAMES,
    frames_per_second: 16,
    frame_url: `/api/hazards/${ASSET}/frames/{n}.spz`,
    check: [0.7, 0.7, 0.7],
    size_bytes: 1000,
    placement: { position: [0, 0, 0], turn: 0.3, scale: 1.5, hide: 'box' },
    seconds: FRAMES / 16,
    loops: false,
  }));
}

/** Opens the headset page on the splat room; its socket is passed through, and the test can speak on it. */
async function headset(page: Page): Promise<(message: object) => void> {
  let speak: ((message: object) => void) | null = null;
  await page.routeWebSocket(/\/api\/ws/, socket => {
    const server = socket.connectToServer();
    speak = message => server.send(JSON.stringify(message));
  });
  await page.goto(`${ORIGIN}/quest/`);
  await page.getByRole('button', { name: 'Connect headset', exact: true }).click();
  await expect(page.getByTestId('connection')).toHaveText('Connected · VR headset');
  await expect(page.getByTestId('room-status')).toHaveText(/^Room ready/, { timeout: 30_000 });
  return message => speak!(message);
}

test('a hazard added by the headset loads, hides its object, plays on start and goes when removed', async ({ page }) => {
  test.setTimeout(90_000);
  keepHazard();
  const errors: string[] = [];
  page.on('console', message => { if (message.type() === 'error') errors.push(message.text()); });
  const send = await headset(page);
  const scene = page.getByTestId('quest-scene');

  send({ type: 'add_hazard', room_version: 1, asset: ASSET });
  // Every frame loads before it shows; then its first frame, the object unburnt, takes the box's place.
  await expect(scene).toHaveAttribute('data-hazards', 'hazard_1:ready:0', { timeout: 30_000 });
  await expect(scene).toHaveAttribute('data-hazard-hidden', 'box');

  send({ type: 'start_hazard', room_version: 1, id: 'hazard_1' });
  // It starts 1 s after the asking, on the server's clock, then runs through its frames.
  await expect(scene).toHaveAttribute('data-hazards', /^hazard_1:ready:([1-9]|1\d)$/, { timeout: 5_000 });
  // 24 frames at 16 a second end after 1.5 s; then it keeps burning on its last second (frames 8-23).
  await page.waitForTimeout(3_000);
  const late = Number((await scene.getAttribute('data-hazards'))!.split(':')[2]);
  expect(late).toBeGreaterThanOrEqual(8);

  send({ type: 'stop_hazard', room_version: 1, id: 'hazard_1' });
  await expect(scene).toHaveAttribute('data-hazards', 'hazard_1:ready:0');

  send({ type: 'remove_hazard', room_version: 1, id: 'hazard_1' });
  await expect(scene).toHaveAttribute('data-hazards', '');
  await expect(scene).toHaveAttribute('data-hazard-hidden', '');
  expect(errors.filter(text => text.includes('THREE') || text.includes('hazard'))).toEqual([]);
});
