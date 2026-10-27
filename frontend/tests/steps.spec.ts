import { expect, test } from '@playwright/test';
import type { RoomEntity } from '../src/protocol';
import { STEP_THRESHOLDS, StepDetector, floorplan, stepFrom, type MotionSample } from '../src/steps';

const G = 9.81;
// The phone held upright and tilted back 40°, as when looking at its screen while walking.
const DOWN = { x: 0, y: -Math.cos(40 * Math.PI / 180), z: -Math.sin(40 * Math.PI / 180) };

/** 60 readings a second of a phone bouncing `bounce` m/s² up and down at `cadence` steps a second. */
function motion(seconds: number, cadence: number, bounce: number, rotationRate = 0): MotionSample[] {
  return Array.from({ length: Math.round(seconds * 60) }, (_, index) => {
    const time = index * 1000 / 60;
    const jitter = 0.15 * Math.sin(index * 12.9898);
    // Reading the accelerometer at rest gives +g opposite to down; walking adds the bounce along it.
    const up = G + bounce * Math.sin(2 * Math.PI * cadence * time / 1000) + jitter;
    return { time, x: -DOWN.x * up + jitter, y: -DOWN.y * up, z: -DOWN.z * up, rotationRate };
  });
}

function countSteps(samples: MotionSample[], threshold?: number): number {
  const detector = new StepDetector(threshold);
  return samples.filter(sample => detector.add(sample)).length;
}

test('a walk is counted step by step with the phone held at an angle', () => {
  expect(countSteps(motion(10, 1.8, 2.5))).toBeGreaterThanOrEqual(17);
  expect(countSteps(motion(10, 1.8, 2.5))).toBeLessThanOrEqual(18);
});

test('holding the phone still, or turning it quickly, takes no steps', () => {
  expect(countSteps(motion(10, 1.8, 0))).toBe(0);
  expect(countSteps(motion(10, 1.8, 2.5, 300))).toBe(0);
});

test('gentle steps need a higher sensitivity', () => {
  expect(countSteps(motion(10, 1.8, 1.0), STEP_THRESHOLDS.normal)).toBe(0);
  expect(countSteps(motion(10, 1.8, 1.0), STEP_THRESHOLDS.high)).toBeGreaterThanOrEqual(17);
});

const IDENTITY = { x: 0, y: 0, z: 0, w: 1 };
const entity = (id: string, kind: 'static' | 'movable', size: RoomEntity['size'], x: number, z: number): RoomEntity => ({
  id, label: id, asset_url: '', node: id, kind, selectable: kind === 'movable', size, position: { x, y: 0, z }, rotation: IDENTITY,
});
// The stand-in room.
const ROOM = floorplan([
  entity('floor', 'static', { width: 4, height: 0.02, depth: 4 }, 0, 0),
  entity('desk', 'static', { width: 1.2, height: 0.75, depth: 0.6 }, 0, -1.2),
  entity('cabinet', 'static', { width: 0.8, height: 1.2, depth: 0.4 }, 1.4, -1.2),
  entity('box', 'movable', { width: 0.2, height: 0.2, depth: 0.2 }, -0.5, -0.4),
]);

test('the floor bounds walking and the furniture blocks it, but the movable box does not', () => {
  expect(ROOM.floor).toEqual({ minX: -2, maxX: 2, minZ: -2, maxZ: 2 });
  expect(ROOM.obstacles).toHaveLength(2);
});

test('a step moves toward where the phone faces, and slides along or stops at furniture and walls', () => {
  const start = { x: 0, y: 1.5, z: 1.6 };
  const forward = stepFrom(start, 0, 0.6, ROOM);
  expect(forward.x).toBeCloseTo(0, 9);
  expect(forward.z).toBeCloseTo(1.0, 9);
  const left = stepFrom(start, Math.PI / 2, 0.6, ROOM);
  expect(left.x).toBeCloseTo(-0.6, 9);
  expect(left.z).toBeCloseTo(1.6, 9);
  // Just in front of the desk: straight ahead stays put, and diagonally slides along its front.
  const atDesk = { x: 0, y: 1.5, z: -0.5 };
  expect(stepFrom(atDesk, 0, 0.6, ROOM)).toMatchObject({ x: 0, z: -0.5 });
  const slid = stepFrom(atDesk, Math.PI / 4, 0.6, ROOM);
  expect(slid.x).toBeLessThan(-0.4);
  expect(slid.z).toBeCloseTo(-0.5, 9);
  // The floor's back edge stops a step out of the room.
  const back = stepFrom(start, Math.PI, 0.6, ROOM);
  expect(back.z).toBeCloseTo(1.6, 9);
});

test('a person starting off the floor still walks, onto it, and the floor holds them once there', () => {
  // The hallway room's floor ends at z = -1.2, but the phone starts at z = 1.6 (27 October 2026):
  // every step was refused, and the view never moved.
  const hallway = { floor: { minX: -7.2, maxX: 0.3, minZ: -6.4, maxZ: -1.2 }, obstacles: [] };
  let at = { x: 0, y: 1.5, z: 1.6 };
  for (let step = 0; step < 6; step++) at = stepFrom(at, 0, 0.6, hallway);
  expect(at.z).toBeCloseTo(-2.0, 9);
  // Back toward the start, the floor's edge now holds.
  const back = stepFrom({ x: -1, y: 1.5, z: -1.5 }, Math.PI, 0.6, hallway);
  expect(back.z).toBeCloseTo(-1.5, 9);
});
