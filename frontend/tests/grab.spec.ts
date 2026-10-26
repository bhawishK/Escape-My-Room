import { expect, test } from '@playwright/test';
import { grabbedPosition, offsetOf, targetAlongRay } from '../src/grab';
import type { RoomEntity } from '../src/protocol';

const identity = { x: 0, y: 0, z: 0, w: 1 };
const boxAt = { x: -0.5, y: 0, z: -0.4 };

function entity(id: string, kind: 'movable' | 'static', position: { x: number; y: number; z: number }): RoomEntity {
  return {
    id, label: id, asset_url: '', node: id, kind, selectable: kind === 'movable',
    position, rotation: identity,
    size: { width: 0.2, height: 0.2, depth: 0.2 },
  };
}

test('a grab keeps the box on the grip instead of jumping to it', () => {
  const grip = { x: -0.7, y: 0.2, z: -0.4 };
  const offset = offsetOf(grip, identity, boxAt);
  expect(grabbedPosition(grip, identity, offset)).toEqual(boxAt);
  const moved = { x: -0.4, y: 0.5, z: -0.1 };
  const placed = grabbedPosition(moved, identity, offset);
  expect(placed.x).toBeCloseTo(boxAt.x + 0.3, 8);
  expect(placed.y).toBeCloseTo(boxAt.y + 0.3, 8);
  expect(placed.z).toBeCloseTo(boxAt.z + 0.3, 8);
});

test('the pointing ray grabs the box it hits and ignores the furniture', () => {
  const entities = [entity('desk', 'static', { x: 0, y: 0, z: -1 }), entity('box', 'movable', boxAt)];
  expect(targetAlongRay({ x: -0.5, y: 0.1, z: 1 }, { x: 0, y: 0, z: -1 }, entities)).toBe('box');
  expect(targetAlongRay({ x: 2, y: 0.1, z: 1 }, { x: 0, y: 0, z: -1 }, entities)).toBeNull();
});
