import { expect, test } from '@playwright/test';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { FilmingCoach, MEASURE_HEIGHT, MEASURE_WIDTH, measure, type Gray } from '../src/filming-coach';

// #100: the filming coach's checks, on recorded frames. The clips are 2 s of room 10's own video,
// sampled as the page samples it (7 a second, 90 x 160 grey): a steady view of the door and bed, its
// fastest sweep (across the wardrobe), and a close-up of the plain door. Room 10 was filmed slowly
// enough that even its fastest sweep stays under the limit, so the sweep is also played at twice
// its speed, every other frame, as a too-fast one.

const SAMPLE_MS = 1000 / 7;

function clip(name: string): Gray[] {
  const data = readFileSync(fileURLToPath(new URL(`fixtures/coach/${name}.gray`, import.meta.url)));
  const size = MEASURE_WIDTH * MEASURE_HEIGHT;
  return Array.from({ length: data.length / size }, (_, i) => ({
    width: MEASURE_WIDTH, height: MEASURE_HEIGHT, data: new Uint8Array(data.subarray(i * size, (i + 1) * size)),
  }));
}

function darker(frames: Gray[], factor: number): Gray[] {
  return frames.map(frame => ({ ...frame, data: frame.data.map(value => Math.round(value * factor)) }));
}

/** A box blur `radius` pixels each way: what a shaken or unfocused camera records. */
function blurred(frames: Gray[], radius: number): Gray[] {
  return frames.map(({ width, height, data }) => {
    const out = new Uint8Array(data.length);
    for (let y = 0; y < height; y += 1) {
      for (let x = 0; x < width; x += 1) {
        let sum = 0;
        let count = 0;
        for (let dy = -radius; dy <= radius; dy += 1) {
          for (let dx = -radius; dx <= radius; dx += 1) {
            const sx = x + dx;
            const sy = y + dy;
            if (sx < 0 || sy < 0 || sx >= width || sy >= height) continue;
            sum += data[sy * width + sx];
            count += 1;
          }
        }
        out[y * width + x] = Math.round(sum / count);
      }
    }
    return { width, height, data: out };
  });
}

/** Feeds frames to a coach from `start` ms and returns each prompt shown, with when. */
function film(frames: Gray[], coach = new FilmingCoach(), start = 0): { at: number; text: string | null }[] {
  const shown: { at: number; text: string | null }[] = [];
  let previous: Gray | null = null;
  frames.forEach((frame, index) => {
    const at = start + index * SAMPLE_MS;
    coach.add(measure(frame, previous), at);
    previous = frame;
    shown.push({ at, text: coach.prompt(at)?.text ?? null });
  });
  return shown;
}

/** The sweep at twice its speed. */
const tooFast = () => clip('fast').filter((_, index) => index % 2 === 0);

const texts = (shown: { text: string | null }[]) => [...new Set(shown.map(s => s.text).filter(Boolean))];

test('steady filming gets no prompt', () => {
  expect(texts(film(clip('steady')))).toEqual([]);
});

test('a sweep too fast is told to slow down, measured by how far the picture moves', () => {
  const speeds = (frames: Gray[]) => frames.slice(1).map((frame, i) => measure(frame, frames[i]).shift * 7);
  // Frame widths a second: steady filming, the room's own fastest sweep, and that sweep doubled.
  expect(Math.max(...speeds(clip('steady')))).toBeLessThan(0.3);
  expect(Math.min(...speeds(tooFast()))).toBeGreaterThan(0.6);
  expect(texts(film(clip('fast')))).toEqual([]);
  expect(texts(film(tooFast()))).toEqual(['Slow down']);
});

test('a close-up of a plain surface is told to step back', () => {
  expect(texts(film(clip('plain')))).toEqual(['Step back to show more of the room']);
});

test('a dark room is told to turn the lights on', () => {
  expect(texts(film(darker(clip('steady'), 0.25)))).toEqual(['Too dark: turn the lights on']);
});

test('a picture that turns blurred is told to hold steady', () => {
  const steady = clip('steady');
  const frames = [...steady, ...blurred(steady, 3)];
  const shown = film(frames);
  expect(texts(shown.slice(0, steady.length))).toEqual([]);
  expect(texts(shown)).toEqual(['Hold steady: the picture is blurred']);
});

test('one prompt at a time: darkness comes before speed', () => {
  const shown = film(darker(tooFast(), 0.25));
  expect(texts(shown)).toEqual(['Too dark: turn the lights on']);
});

test('a prompt stays up long enough to read, then goes once the problem has', () => {
  const coach = new FilmingCoach();
  const fast = film([...tooFast(), ...tooFast()], coach);
  const first = fast.find(s => s.text === 'Slow down')!;
  const after = film(clip('steady'), coach, fast[fast.length - 1].at + SAMPLE_MS);
  const cleared = after.find(s => s.text === null)!;
  expect(cleared.at - first.at).toBeGreaterThanOrEqual(1500);
  expect(after[after.length - 1].text).toBeNull();
});
