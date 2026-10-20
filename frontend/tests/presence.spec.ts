import { expect, test } from '@playwright/test';
import { alignmentFromPose, roomHeading, roomPoint } from '../src/alignment';

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
    expect(room.y).toBeCloseTo(pose.position.y, 8);
    expect(roomHeading(alignment, pose.orientation)).toBeCloseTo(0, 8);
  }
});

test('turning left after alignment reports a positive heading', () => {
  const alignment = alignmentFromPose(headset.position, headset.orientation);
  const turned = { x: 0, y: Math.sin(0.4), z: 0, w: Math.cos(0.4) };
  expect(roomHeading(alignment, turned)).toBeCloseTo(0.3, 6);
  expect(roomPoint(alignment, headset.position).x).toBeCloseTo(0, 8);
});
