import { expect, test, type Page } from '@playwright/test';
import { mkdtempSync, readFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { writeSheets } from '../scripts/markers';
import { BoardCalibrator, MarkerLocator, type Frame } from '../src/vision';
import { loadOpenCV } from './synthetic';

const DOCS = join(import.meta.dirname, '..', '..', 'docs', 'markers');
const MANIFEST = join(import.meta.dirname, '..', '..', 'assets', 'prepared-room', 'manifest.json');

/** The sheet as the browser draws it, flat on, `pixelsPerMm` pixels per millimeter. */
async function rasterize(page: Page, name: string, pixelsPerMm: number): Promise<Frame> {
  const svg = readFileSync(join(DOCS, name), 'utf-8');
  return page.evaluate(async ({ svg, pixelsPerMm }) => {
    const image = new Image();
    image.src = `data:image/svg+xml;base64,${btoa(unescape(encodeURIComponent(svg)))}`;
    await image.decode();
    const width = Math.round(Number.parseFloat(svg.match(/width="([\d.]+)mm"/)![1]) * pixelsPerMm);
    const height = Math.round(Number.parseFloat(svg.match(/height="([\d.]+)mm"/)![1]) * pixelsPerMm);
    const canvas = Object.assign(document.createElement('canvas'), { width, height });
    const context = canvas.getContext('2d')!;
    context.drawImage(image, 0, 0, width, height);
    return { width, height, rgba: Array.from(context.getImageData(0, 0, width, height).data) };
  }, { svg, pixelsPerMm }).then(frame => ({ ...frame, rgba: new Uint8ClampedArray(frame.rgba) }));
}

test('the committed sheets are what the generator writes', async () => {
  const directory = mkdtempSync(join(tmpdir(), 'escape-my-room-sheets-'));
  for (const name of await writeSheets(MANIFEST, directory)) {
    const committed = readFileSync(join(DOCS, name), 'utf-8');
    expect(readFileSync(join(directory, name), 'utf-8'), `${name} is stale; run npm run markers`).toBe(committed);
  }
});

test('the printed desk tag reads as tag 0, upright, at its printed size', async ({ page }) => {
  const { cv } = await loadOpenCV();
  const frame = await rasterize(page, 'tag36h11-00.svg', 3);
  // Seen flat on from 1 m by a camera centered on the tag: 150 mm then spans 150 · f / 1000 pixels.
  const f = 3000;
  const marker = { id: 0, label: 'Desk front', size: 0.15, position: { x: 0, y: 0, z: 0 }, rotation: { x: 0, y: 0, z: 0, w: 1 } };
  const center = { x: 105 * 3 - 0.5, y: (50 + 75) * 3 - 0.5 };
  const intrinsics = {
    width: frame.width, height: frame.height, fx: f, fy: f, cx: center.x, cy: center.y, distortion: [0, 0, 0, 0, 0],
  };
  const located = new MarkerLocator(cv).locate(frame, intrinsics, [marker]);
  if (located.kind !== 'tracked') throw new Error(located.reason);
  // Upright and centered means the camera sits 1 m straight out from the tag's face.
  const { x, y, z } = located.pose.position;
  expect(Math.hypot(x, y, z - 1)).toBeLessThan(0.005);
});

test('the printed calibration board shows all of its inner corners', async ({ page }) => {
  const { cv } = await loadOpenCV();
  const frame = await rasterize(page, 'calibration-board.svg', 3);
  expect(new BoardCalibrator(cv).addView(frame)).toEqual({ corners: 24, kept: true });
});
