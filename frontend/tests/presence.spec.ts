import { expect, test } from '@playwright/test';
import { STANDING_EYE_HEIGHT, alignmentFromPose, roomHeading, roomPoint } from '../src/alignment';

const phone = {
  position: { x: 0.4, y: 1.5, z: 0.25 },
  orientation: { x: 0, y: 0, z: 0, w: 1 },
};
const headset = {
  position: { x: -0.7, y: 1.6, z: 1.1 },
  orientation: { x: 0, y: Math.sin(0.25), z: 0, w: Math.cos(0.25) },
};

test('two confirmed devices stand at the floor center facing the desk', () => {
  for (const pose of [phone, headset]) {
    const alignment = alignmentFromPose(pose.position, pose.orientation);
    const room = roomPoint(alignment, pose.position);
    expect(room.x).toBeCloseTo(0, 8);
    expect(room.z).toBeCloseTo(0, 8);
    expect(room.y).toBeCloseTo(STANDING_EYE_HEIGHT, 8);
    expect(roomHeading(alignment, pose.orientation)).toBeCloseTo(0, 8);
  }
});

test('turning left after alignment reports a positive heading', () => {
  const alignment = alignmentFromPose(headset.position, headset.orientation);
  const turned = { x: 0, y: Math.sin(0.4), z: 0, w: Math.cos(0.4) };
  expect(roomHeading(alignment, turned)).toBeCloseTo(0.3, 6);
  expect(roomPoint(alignment, headset.position).x).toBeCloseTo(0, 8);
});

test('the headset sees the room from the phone user’s 1.5 m eye height, floor at its feet', () => {
  // In the `local` space the head starts near y = 0, which used to put the room's floor at eye level.
  const atStart = { position: { x: 0.2, y: 0.03, z: -0.1 }, orientation: headset.orientation };
  const alignment = alignmentFromPose(atStart.position, atStart.orientation);
  expect(roomPoint(alignment, atStart.position).y).toBeCloseTo(1.5, 8);
  // The floor is 1.5 m under the head, and crouching still lowers the view.
  expect(roomPoint(alignment, { ...atStart.position, y: 0.03 - 1.5 }).y).toBeCloseTo(0, 8);
  expect(roomPoint(alignment, { ...atStart.position, y: 0.03 - 0.6 }).y).toBeCloseTo(0.9, 8);
});

test('on the headset\'s real floor (local-floor), the room\'s floor is put on it and the head keeps its height', () => {
  // #207: y = 0 is the real floor, so a 1.72 m tall person's eyes stay 1.72 m up, and sitting, 1.2 m.
  const standing = { position: { x: 0.2, y: 1.72, z: -0.1 }, orientation: headset.orientation };
  const alignment = alignmentFromPose(standing.position, standing.orientation, true);
  expect(roomPoint(alignment, standing.position).y).toBeCloseTo(1.72, 8);
  expect(roomPoint(alignment, { ...standing.position, y: 0 }).y).toBeCloseTo(0, 8);
  expect(roomPoint(alignment, { ...standing.position, y: 1.2 }).y).toBeCloseTo(1.2, 8);
  // It still lines up across the floor and facing, as before.
  expect(roomPoint(alignment, standing.position).x).toBeCloseTo(0, 8);
  expect(roomHeading(alignment, standing.orientation)).toBeCloseTo(0, 8);
});
