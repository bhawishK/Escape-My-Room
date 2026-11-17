import { expect, test } from '@playwright/test';
import { PieceResize, isTap, sizeLabel } from '../src/quest/piece-resize';
import * as THREE from 'three';
import type { Position, RoomEntity } from '../src/protocol';
import { placeEntities } from '../src/room';

// #202: choosing Move or Resize for a placed piece, and resizing it with two hands.

function close(actual: Position, expected: Position): void {
  expect(actual.x).toBeCloseTo(expected.x, 5);
  expect(actual.y).toBeCloseTo(expected.y, 5);
  expect(actual.z).toBeCloseTo(expected.z, 5);
}

const HERE = { x: 0, y: 1, z: -0.4 };

test('a quick pinch that hardly moves is a tap; a long or travelling one is not', () => {
  expect(isTap(1000, HERE, 1250, { x: 0.01, y: 1, z: -0.4 })).toBe(true);
  expect(isTap(1000, HERE, 1500, HERE)).toBe(false);
  expect(isTap(1000, HERE, 1200, { x: 0.06, y: 1, z: -0.4 })).toBe(false);
});

test('in resize mode, hands pulled apart grow the piece and pulled together shrink it', () => {
  const resize = new PieceResize();
  resize.begin('furniture_1', 1);
  expect(resize.update([{ x: -0.1, y: 1, z: -0.4 }, { x: 0.1, y: 1, z: -0.4 }])).toEqual({ phase: 'resizing', scale: 1 });
  expect(resize.update([{ x: -0.2, y: 1, z: -0.4 }, { x: 0.2, y: 1, z: -0.4 }]).scale).toBeCloseTo(2);
  expect(resize.update([{ x: -0.05, y: 1, z: -0.4 }, { x: 0.05, y: 1, z: -0.4 }]).scale).toBeCloseTo(0.5);
});

test('a resize starts from the piece\'s own scale and stays within a quarter and three times', () => {
  const resize = new PieceResize();
  resize.begin('furniture_1', 1.5);
  resize.update([{ x: -0.1, y: 1, z: -0.4 }, { x: 0.1, y: 1, z: -0.4 }]);
  expect(resize.update([{ x: -0.2, y: 1, z: -0.4 }, { x: 0.2, y: 1, z: -0.4 }]).scale).toBeCloseTo(3);
  expect(resize.update([{ x: -0.5, y: 1, z: -0.4 }, { x: 0.5, y: 1, z: -0.4 }]).scale).toBeCloseTo(3);
  expect(resize.update([{ x: -0.001, y: 1, z: -0.4 }, { x: 0.001, y: 1, z: -0.4 }]).scale).toBeCloseTo(0.25);
});

test('letting go of either hand ends the resize with its last scale, and resize mode with it', () => {
  const resize = new PieceResize();
  resize.begin('furniture_1', 1);
  // Before both hands pinch, it waits.
  expect(resize.update([{ x: 0, y: 1, z: -0.4 }])).toEqual({ phase: 'waiting', scale: 1 });
  resize.update([{ x: -0.1, y: 1, z: -0.4 }, { x: 0.1, y: 1, z: -0.4 }]);
  resize.update([{ x: -0.15, y: 1, z: -0.4 }, { x: 0.15, y: 1, z: -0.4 }]);
  const ended = resize.update([{ x: -0.15, y: 1, z: -0.4 }]);
  expect(ended.phase).toBe('done');
  expect(ended.scale).toBeCloseTo(1.5);
  expect(resize.piece).toBeNull();
});

test('hands that start too close together don\'t start a resize', () => {
  const resize = new PieceResize();
  resize.begin('furniture_1', 1);
  expect(resize.update([{ x: 0, y: 1, z: -0.4 }, { x: 0.01, y: 1, z: -0.4 }]).phase).toBe('waiting');
});

test('the size label gives the true size in metres at the new scale', () => {
  expect(sizeLabel({ width: 1.4, height: 0.75, depth: 0.8 }, 2)).toBe('2.80 × 1.60 × 1.50 m');
});

test('both pages draw a resized piece at its scale, grown up from where it stands', () => {
  // A 1 m cube whose bottom face is at its origin, as a catalogue piece's is.
  const geometry = new THREE.BoxGeometry(1, 1, 1);
  geometry.translate(0, 0.5, 0);
  const asset = new THREE.Group();
  asset.add(Object.assign(new THREE.Mesh(geometry), { name: 'cube' }));
  const entity: RoomEntity = {
    id: 'furniture_1', label: 'Cube', asset_url: '/cube.glb', node: 'cube', kind: 'movable', selectable: true,
    position: { x: 1, y: 0, z: -1 }, rotation: { x: 0, y: 0, z: 0, w: 1 },
    size: { width: 2, height: 2, depth: 2 }, furniture: 'cube', scale: 2,
  };
  const root = placeEntities(new Map([['/cube.glb', asset]]), [entity]).get('furniture_1')!;
  root.updateMatrixWorld(true);
  const box = new THREE.Box3().setFromObject(root);

  close(box.min, { x: 0, y: 0, z: -2 });
  close(box.max, { x: 2, y: 2, z: 0 });
});
