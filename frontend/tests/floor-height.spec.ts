import { expect, test } from '@playwright/test';
import * as THREE from 'three';
import {
  floorHeight, frameDepth, fromFloat16, gravityInCamera, modelCanvas, placeFrame, toFloat16, type DepthMap,
} from '../src/floor-height';
import { cameraFromDevice } from '../src/phone-view';

type Vec3 = [number, number, number];
const dot = (a: Vec3, b: Vec3) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
const WIDTH = 60;
const HEIGHT = 80;
const INTRINSICS = { fx: 50, fy: 50, cx: WIDTH / 2, cy: HEIGHT / 2 };

/** A surface the synthetic camera can see: a plane `distance` meters away along `normal`, facing the camera. */
interface Surface { normal: Vec3; distance: number; covers?: (u: number, v: number) => boolean }

/**
 * The depth and normals a camera pitched down by `pitch` radians sees, in the camera's image frame
 * (x right, y down, z forward), with `down` the direction of gravity in that frame.
 */
function render(pitch: number, surfaces: Surface[]): { map: DepthMap; down: Vec3 } {
  const down: Vec3 = [0, Math.cos(pitch), Math.sin(pitch)];
  const depth = new Float32Array(WIDTH * HEIGHT);
  const normals = new Float32Array(WIDTH * HEIGHT * 3);
  for (let v = 0; v < HEIGHT; v++) {
    for (let u = 0; u < WIDTH; u++) {
      const ray: Vec3 = [(u - INTRINSICS.cx) / INTRINSICS.fx, (v - INTRINSICS.cy) / INTRINSICS.fy, 1];
      let nearest = Infinity;
      let facing: Vec3 = [0, 0, 0];
      for (const surface of surfaces) {
        if (surface.covers && !surface.covers(u, v)) continue;
        const along = dot(ray, surface.normal);
        // The plane is where a point's offset along `normal` is `distance`; depth is the ray's z.
        const t = along > 0 ? surface.distance / along : Infinity;
        if (t < nearest) {
          nearest = t;
          facing = [-surface.normal[0], -surface.normal[1], -surface.normal[2]];
        }
      }
      const index = v * WIDTH + u;
      depth[index] = Number.isFinite(nearest) ? nearest : 0;
      normals.set(facing, index * 3);
    }
  }
  return { map: { width: WIDTH, height: HEIGHT, depth, normals, ...INTRINSICS }, down };
}

test('a camera 1.5 m above an open floor measures 1.5 m', () => {
  const pitch = 25 * Math.PI / 180;
  const { map, down } = render(pitch, [{ normal: [0, Math.cos(pitch), Math.sin(pitch)], distance: 1.5 }]);
  const result = floorHeight(map, down);
  expect(result.kind).toBe('measured');
  if (result.kind === 'measured') expect(result.height).toBeCloseTo(1.5, 2);
});

test('a desk top filling most of the view is not taken for the floor', () => {
  const pitch = 40 * Math.PI / 180;
  const level: Vec3 = [0, Math.cos(pitch), Math.sin(pitch)];
  const { map, down } = render(pitch, [
    { normal: level, distance: 1.5 },
    // A 0.75 m desk top, covering the middle of the picture.
    { normal: level, distance: 0.75, covers: (u, v) => u > 2 && u < 58 && v > 4 && v < 70 },
  ]);
  const result = floorHeight(map, down);
  expect(result.kind).toBe('measured');
  if (result.kind === 'measured') expect(result.height).toBeCloseTo(1.5, 2);
});

test('with only a sliver of floor in view, it asks for more floor instead of guessing', () => {
  const { map, down } = render(0, [
    // A wall 2.5 m ahead, and the floor only in the bottom two rows, 2.5 % of the picture.
    { normal: [0, 0, 1], distance: 2.5 },
    { normal: [0, 1, 0], distance: 1.5, covers: (_u, v) => v >= HEIGHT - 2 },
  ]);
  expect(floorHeight(map, down)).toEqual({ kind: 'none', reason: 'Too little floor in view. Tilt the phone down.' });
});

test('gravity a few degrees off still measures the floor, from the floor plane itself', () => {
  const pitch = 20 * Math.PI / 180;
  const { map, down } = render(pitch, [{ normal: [0, Math.cos(pitch), Math.sin(pitch)], distance: 1.5 }]);
  // The phone's sensor reports gravity rolled 4° to the side of the truth.
  const roll = 4 * Math.PI / 180;
  const reported: Vec3 = [Math.sin(roll) * down[1], Math.cos(roll) * down[1], down[2]];
  const result = floorHeight(map, reported);
  expect(result.kind).toBe('measured');
  if (result.kind === 'measured') expect(result.height).toBeCloseTo(1.5, 2);
});

const expectDirection = (actual: readonly number[], expected: readonly number[]) =>
  actual.forEach((value, index) => expect(value).toBeCloseTo(expected[index], 6));

test('gravity points down the picture for an upright phone, and tips forward as it leans back', () => {
  // beta 90: upright, the back camera looking straight ahead.
  expectDirection(gravityInCamera(cameraFromDevice(0, 90, 0, 0)), [0, 1, 0]);
  // beta 60: leaned back 30°, so the back camera looks 30° down and gravity has a forward part.
  expectDirection(gravityInCamera(cameraFromDevice(25, 60, 0, 0)), [0, Math.cos(Math.PI / 6), Math.sin(Math.PI / 6)]);
});

test('gravity still points down the picture with the phone held in landscape', () => {
  // Upright, then a quarter turn about the screen's normal; the screen reports the same quarter turn.
  const turned = new THREE.Quaternion().setFromEuler(new THREE.Euler(Math.PI / 2, 0, 0, 'YXZ'))
    .multiply(new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 1, 0), Math.PI / 2));
  const euler = new THREE.Euler().setFromQuaternion(turned, 'YXZ');
  const degrees = (radians: number) => radians * 180 / Math.PI;
  const landscape = cameraFromDevice(degrees(euler.y), degrees(euler.x), -degrees(euler.z), 90);
  expectDirection(gravityInCamera(landscape), [0, 1, 0]);
});

test('the model canvas is 616 x 1064 turned to the frame, and the frame is centered in it', () => {
  expect(modelCanvas({ width: 720, height: 1280 })).toEqual({ width: 616, height: 1064 });
  expect(modelCanvas({ width: 1280, height: 720 })).toEqual({ width: 1064, height: 616 });
  // 720 x 1280 shrinks by 1064 / 1280 to 598.5 x 1064, rounded, and sits 8 px from the left.
  expect(placeFrame({ width: 720, height: 1280 }, { width: 616, height: 1064 }))
    .toEqual({ scale: 0.83125, width: 599, height: 1064, left: 8, top: 0 });
});

test('half-precision numbers are encoded and decoded as IEEE 754 binary16', () => {
  // 1, 0.5, -2, the largest half (65504), 0, and 123.4, which rounds to the nearest half, 123.375.
  const bits = toFloat16(new Float32Array([1, 0.5, -2, 65504, 0, 123.4]));
  expect(Array.from(bits)).toEqual([0x3c00, 0x3800, 0xc000, 0x7bff, 0x0000, 0x57b6]);
  expect(Array.from(fromFloat16(bits))).toEqual([1, 0.5, -2, 65504, 0, 123.375]);
  // A tiny depth the model can return, below the normal range: 2^-20.
  expect(fromFloat16(new Uint16Array([0x0010]))[0]).toBe(2 ** -20);
});

test('the model output is cropped to the camera frame, in meters, with normals per pixel', () => {
  // An 8 x 4 canvas holding a frame shrunk by half to 4 x 4, 2 px from the left.
  const canvas = { width: 8, height: 4 };
  const placement = { scale: 0.5, width: 4, height: 4, left: 2, top: 0 };
  const depth = new Float32Array(32).fill(100);
  depth[2] = 200;
  const normals = new Float32Array(96);
  // Planar output: all x values, then all y values, then all z values.
  normals[2] = 0.25;
  normals[32 + 2] = -0.5;
  normals[64 + 2] = 0.75;
  // A 30 px focal length in the frame is 15 px on the canvas, where the model's depth is for a
  // 1000 px focal length: 100 there is 100 x 15 / 1000 = 1.5 m.
  const map = frameDepth({ width: 8, height: 4, depth, normals }, canvas, placement, 30);
  expect({ width: map.width, height: map.height, fx: map.fx, fy: map.fy, cx: map.cx, cy: map.cy })
    .toEqual({ width: 4, height: 4, fx: 15, fy: 15, cx: 2, cy: 2 });
  expect(map.depth[0]).toBeCloseTo(3, 9);
  expect(Array.from(map.depth.slice(1))).toEqual(new Array(15).fill(1.5));
  expect(Array.from(map.normals.slice(0, 3))).toEqual([0.25, -0.5, 0.75]);
});
