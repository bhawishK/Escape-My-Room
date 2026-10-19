/**
 * Writes the printable sheets: one A4 page per tracking marker in the stand-in room's manifest,
 * and the A4 calibration board. Both come from the same OpenCV dictionaries and board definition
 * the tracker detects, so a printed sheet always matches what the phone looks for.
 */
import cvModule from '@techstark/opencv-js';
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import type { TrackingMarker } from '../src/protocol';
import { BOARD, createBoard, openCV, type Mat } from '../src/vision';

const MILLIMETERS_PER_METER = 1000;

/** Black areas of a one-channel image as rectangles, `scale` millimeters per pixel. */
function blackRectangles(image: Mat, scale: number, left: number, top: number): string[] {
  const rectangles: string[] = [];
  // Runs that continue unchanged from the row above grow taller instead of starting again.
  let open = new Map<string, { y: number; height: number }>();
  const close = (key: string, run: { y: number; height: number }) => {
    const [x0, x1] = key.split(':').map(Number);
    rectangles.push(`<rect x="${(left + x0 * scale).toFixed(3)}" y="${(top + run.y * scale).toFixed(3)}" ` +
      `width="${((x1 - x0) * scale).toFixed(3)}" height="${(run.height * scale).toFixed(3)}"/>`);
  };
  for (let y = 0; y <= image.rows; y++) {
    const next = new Map<string, { y: number; height: number }>();
    for (let x = 0; y < image.rows && x < image.cols;) {
      if (image.data[y * image.cols + x] >= 128) { x++; continue; }
      const start = x;
      while (x < image.cols && image.data[y * image.cols + x] < 128) x++;
      const key = `${start}:${x}`;
      const run = open.get(key);
      next.set(key, run ? { y: run.y, height: run.height + 1 } : { y, height: 1 });
      open.delete(key);
    }
    for (const [key, run] of open) close(key, run);
    open = next;
  }
  return rectangles;
}

function page(width: number, height: number, body: string[]): string {
  return `<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="${width}mm" height="${height}mm" viewBox="0 0 ${width} ${height}">
<rect width="${width}" height="${height}" fill="#fff"/>
${body.join('\n')}
</svg>
`;
}

function text(x: number, y: number, size: number, content: string): string {
  const escaped = content.replace(/&/g, '&amp;').replace(/</g, '&lt;');
  return `<text x="${x}" y="${y}" font-family="sans-serif" font-size="${size}" text-anchor="middle" fill="#333">${escaped}</text>`;
}

export async function writeSheets(manifest: string, directory: string): Promise<string[]> {
  const { cv } = await openCV(cvModule);
  mkdirSync(directory, { recursive: true });
  const written: string[] = [];
  const markers = (JSON.parse(readFileSync(manifest, 'utf-8')) as { markers?: TrackingMarker[] }).markers ?? [];
  const dictionary = cv.getPredefinedDictionary(cv.DICT_APRILTAG_36h11);
  for (const marker of markers) {
    // One pixel per module: the black border ring and the 6 x 6 code.
    const tag = new cv.Mat();
    dictionary.generateImageMarker(marker.id, 8, tag, 1);
    const side = marker.size * MILLIMETERS_PER_METER;
    const left = (210 - side) / 2;
    const top = 50;
    const { x, y, z } = marker.position;
    const name = `tag36h11-${String(marker.id).padStart(2, '0')}.svg`;
    writeFileSync(join(directory, name), page(210, 297, [
      text(105, 22, 7, `Escape My Room · AprilTag 36h11 · ID ${marker.id} · ${marker.label}`),
      text(105, 34, 4.5, 'Print at 100 % (no scaling). Measure the black square before use.'),
      `<g fill="#000" shape-rendering="crispEdges">${blackRectangles(tag, side / 8, left, top).join('')}</g>`,
      text(105, top + side + 18, 5, `The black square must be ${side.toFixed(0)} mm wide.`),
      text(105, top + side + 28, 4.5, `Room position of its center: x ${x.toFixed(2)} m, y ${y.toFixed(2)} m, z ${z.toFixed(2)} m.`),
      text(105, top + side + 36, 4.5, 'Keep the printed text upright; the tag faces into the room.'),
    ]));
    written.push(name);
    tag.delete();
  }
  dictionary.delete();

  // The board at ten pixels per millimeter, then traced into exact rectangles.
  const { board, dictionary: boardDictionary } = createBoard(cv);
  const width = BOARD.columns * BOARD.squareMeters * MILLIMETERS_PER_METER;
  const height = BOARD.rows * BOARD.squareMeters * MILLIMETERS_PER_METER;
  const image = new cv.Mat();
  board.generateImage(new cv.Size(width * 10, height * 10), image, 0, 1);
  const left = (297 - width) / 2;
  const top = 34;
  writeFileSync(join(directory, 'calibration-board.svg'), page(297, 210, [
    text(148.5, 16, 6, 'Escape My Room · camera calibration board (ChArUco 7 × 5, 5×5 ArUco)'),
    text(148.5, 25, 4.5, 'Print at 100 % and keep the sheet flat, for example taped to a book or board.'),
    `<g fill="#000" shape-rendering="crispEdges">${blackRectangles(image, 0.1, left, top).join('')}</g>`,
    text(148.5, top + height + 14, 4.5,
      `Squares are ${BOARD.squareMeters * MILLIMETERS_PER_METER} mm; the size does not need to be exact for calibration.`),
  ]));
  written.push('calibration-board.svg');
  for (const item of [image, board, boardDictionary]) item.delete();
  return written;
}
