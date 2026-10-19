import { expect, test } from '@playwright/test';
import { faceFeatures, fitMapping, predict, type FaceFeatures, type Landmark } from '../src/gaze';

/** A face mesh with every point at the image center, then each eye laid out level and open. */
function face(irisShift: { x: number; y: number }): Landmark[] {
  const points: Landmark[] = Array.from({ length: 478 }, () => ({ x: 0.5, y: 0.5, z: 0 }));
  for (const [left, right, upper, lower, iris, center] of [[33, 133, 159, 145, 468, 0.4], [362, 263, 386, 374, 473, 0.6]]) {
    points[left] = { x: center - 0.05, y: 0.5, z: 0 };
    points[right] = { x: center + 0.05, y: 0.5, z: 0 };
    points[upper] = { x: center, y: 0.48, z: 0 };
    points[lower] = { x: center, y: 0.52, z: 0 };
    points[iris] = { x: center + irisShift.x, y: 0.5 + irisShift.y, z: 0 };
  }
  return points;
}
const STRAIGHT = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, -40, 1];

test('iris offsets are measured in eye widths, and need the iris points', () => {
  const centered = faceFeatures(face({ x: 0, y: 0 }), STRAIGHT, 1)!;
  expect(centered.eyeX).toBeCloseTo(0, 9);
  expect(centered.eyeY).toBeCloseTo(0, 9);
  const shifted = faceFeatures(face({ x: 0.01, y: -0.02 }), STRAIGHT, 1)!;
  expect(shifted.eyeX).toBeCloseTo(0.1, 9);
  expect(shifted.eyeY).toBeCloseTo(-0.2, 9);
  // A wider video stretches across offsets and eye widths alike, so the result holds.
  expect(faceFeatures(face({ x: 0.01, y: 0 }), STRAIGHT, 4 / 3)!.eyeX).toBeCloseTo(0.1, 9);
  expect(faceFeatures(face({ x: 0, y: 0 }).slice(0, 468), STRAIGHT, 1)).toBeNull();
});

test('the head direction and offset come from the transformation matrix', () => {
  const turned = [...STRAIGHT];
  turned[8] = 0.2;
  turned[9] = -0.1;
  turned[12] = 3;
  turned[13] = -2;
  expect(faceFeatures(face({ x: 0, y: 0 }), turned, 1)).toMatchObject({ headX: 0.2, headY: -0.1, offsetX: 3, offsetY: -2 });
});

/** Features spread like a person looking around a screen, with a little of each input. */
function sample(index: number): FaceFeatures {
  const wave = (k: number) => Math.sin(index * 1.7 + k * 2.3);
  return { headX: 0.15 * wave(1), headY: 0.1 * wave(2), offsetX: 2 * wave(3), offsetY: 2 * wave(4), eyeX: 0.08 * wave(5), eyeY: 0.05 * wave(6) };
}
const truth = (f: FaceFeatures) => ({ x: 0.5 + 2 * f.headX + 3 * f.eyeX, y: 0.5 - 2.5 * f.headY + 4 * f.eyeY });

test('a calibrated eye cursor reproduces a linear gaze mapping on new points', () => {
  const samples = Array.from({ length: 9 }, (_, index) => ({ features: sample(index), target: truth(sample(index)) }));
  const mapping = fitMapping(samples, 'eyes', 1e-6);
  for (let index = 20; index < 25; index++) {
    const point = predict(mapping, sample(index));
    expect(point.x).toBeCloseTo(truth(sample(index)).x, 3);
    expect(point.y).toBeCloseTo(truth(sample(index)).y, 3);
  }
});

test('regularization keeps imprecise calibration taps from bending the cursor', () => {
  // A person never looks exactly at each dot, and the head offset only jitters by a millimeter.
  const jitter = (index: number, k: number) => Math.sin(index * 12.9898 + k * 78.233);
  const steady = (index: number) => ({ ...sample(index), offsetX: 0.1 * jitter(index, 3), offsetY: 0.1 * jitter(index, 4) });
  const samples = Array.from({ length: 9 }, (_, index) => {
    const goal = truth(steady(index));
    return { features: steady(index), target: { x: goal.x + 0.03 * jitter(index, 7), y: goal.y + 0.03 * jitter(index, 8) } };
  });
  const error = (ridge?: number) => {
    const mapping = fitMapping(samples, 'eyes', ridge);
    let total = 0;
    for (let index = 20; index < 30; index++) {
      const point = predict(mapping, steady(index));
      total += Math.hypot(point.x - truth(steady(index)).x, point.y - truth(steady(index)).y);
    }
    return total / 10;
  };
  expect(error()).toBeLessThan(0.8 * error(1e-6));
});

test('the head cursor ignores the eyes, and an input that never varied does not break the fit', () => {
  const still = (index: number) => ({ ...sample(index), offsetX: 1.5 });
  const samples = Array.from({ length: 9 }, (_, index) => ({ features: still(index), target: truth(still(index)) }));
  const mapping = fitMapping(samples, 'head');
  const looked = predict(mapping, { ...still(3), eyeX: 0.5 });
  expect(looked).toEqual(predict(mapping, still(3)));
  expect(Number.isFinite(looked.x) && Number.isFinite(looked.y)).toBe(true);
});
