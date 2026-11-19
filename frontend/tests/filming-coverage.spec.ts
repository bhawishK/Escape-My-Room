import { expect, test } from '@playwright/test';
import { FilmingCoverage, cameraDirection } from '../src/filming-coverage';

// #100: which ways the camera has filmed, from the phone's orientation sensor. Headings run
// clockwise from where the sensor's alpha is 0; pitch is up from level.

function close(actual: number, expected: number): void {
  const difference = ((actual - expected + 540) % 360) - 180;
  expect(Math.abs(difference)).toBeLessThan(0.5);
}

test('the back camera of a phone held upright looks level, along alpha', () => {
  const ahead = cameraDirection(0, 90, 0);
  close(ahead.heading, 0);
  expect(ahead.pitch).toBeCloseTo(0, 3);
  // Tipped back 30 degrees from upright, the camera looks 30 degrees down.
  expect(cameraDirection(0, 60, 0).pitch).toBeCloseTo(-30, 3);
  // Turned left (alpha counter-clockwise), the camera's heading goes the other way round.
  close(cameraDirection(90, 90, 0).heading, 270);
  close(cameraDirection(-90, 90, 0).heading, 90);
});

/** Films each heading in `headings` for `seconds` at `pitch`, starting at `start` ms. */
function sweep(coverage: FilmingCoverage, headings: number[], pitch: number, seconds: number, start = 0): number {
  let at = start;
  for (const heading of headings) {
    for (let t = 0; t < seconds * 10; t += 1) {
      coverage.add({ heading, pitch }, at);
      at += 100;
    }
  }
  return at;
}

const range = (from: number, to: number, step = 15) =>
  Array.from({ length: Math.floor((to - from) / step) + 1 }, (_, i) => from + i * step);

test('nothing is asked for while filming has only just started', () => {
  const coverage = new FilmingCoverage();
  const at = sweep(coverage, [0], 0, 5);
  expect(coverage.prompt(0, at)).toBeNull();
});

test('an unfilmed side is named from where the camera faces now', () => {
  const coverage = new FilmingCoverage();
  // Filmed from 0 round to 180 degrees (clockwise), at eye level and down at the floor.
  let at = sweep(coverage, range(0, 180), 0, 1.5);
  at = sweep(coverage, range(0, 180), -40, 1, at);
  // Facing 90, the unfilmed half (180 to 360, centred on 270) is behind.
  expect(coverage.prompt(90, at)?.text).toBe('Turn round: behind you is not filmed yet');
  // Facing 180 it is to the right (clockwise), facing 0 to the left.
  expect(coverage.prompt(180, at)?.text).toBe('Right side not filmed yet');
  expect(coverage.prompt(0, at)?.text).toBe('Left side not filmed yet');
});

test('filming all the way round at eye level but never down asks for the floor', () => {
  const coverage = new FilmingCoverage();
  const at = sweep(coverage, range(0, 345), 0, 1.5);
  expect(coverage.prompt(0, at)?.text).toBe('Show the floor: tilt the phone down as you go');
});

test('all the way round, floor included, there is nothing left to ask for', () => {
  const coverage = new FilmingCoverage();
  let at = sweep(coverage, range(0, 345), 0, 1.5);
  at = sweep(coverage, range(0, 345), -40, 1, at);
  expect(coverage.prompt(123, at)).toBeNull();
  // Twelve headings at three heights: eye level and floor filmed all round, the ceiling not.
  expect(coverage.cells().filter(cell => cell.filmed)).toHaveLength(24);
});
