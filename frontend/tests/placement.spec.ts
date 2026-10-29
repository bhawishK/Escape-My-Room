import { expect, test } from '@playwright/test';
import { placementError, placementTarget } from '../src/placement';

test('a box on the target is inside, and one past the region has a metre error', () => {
  const desk = placementTarget('desk');
  expect(desk).not.toBeNull();
  expect(placementError({ x: 0, y: 0, z: -0.8 }, desk!).inside).toBe(true);
  expect(placementError({ x: 0.4, y: 0.15, z: -0.95 }, desk!).metres).toBe(0);
  const missed = placementError({ x: 0, y: 0, z: -0.5 }, desk!);
  expect(missed.inside).toBe(false);
  expect(missed.metres).toBeCloseTo(0.15);
});

test('the cabinet and floor targets are the spots in front of the furniture', () => {
  expect(placementTarget('cabinet')?.point).toEqual({ x: 1.4, y: 0, z: -0.9 });
  expect(placementTarget('floor')?.point).toEqual({ x: 0, y: 0, z: 0.8 });
  expect(placementTarget('missing')).toBeNull();
});
