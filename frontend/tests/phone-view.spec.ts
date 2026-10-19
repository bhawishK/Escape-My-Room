import { expect, test } from '@playwright/test';
import * as THREE from 'three';
import { cameraFromDevice, headingOf } from '../src/phone-view';

const degrees = (radians: number) => radians * 180 / Math.PI;

test('an upright phone looks straight ahead, and turning it left turns the view left', () => {
  // beta 90: held upright, screen toward the person, back camera facing ahead.
  const ahead = cameraFromDevice(0, 90, 0, 0);
  expect(ahead.angleTo(ahead.clone().identity())).toBeLessThan(1e-9);
  expect(degrees(headingOf(cameraFromDevice(30, 90, 0, 0)))).toBeCloseTo(30, 6);
  expect(degrees(headingOf(cameraFromDevice(-45, 90, 0, 0)))).toBeCloseTo(-45, 6);
});

test('tilting the phone up or down does not change the heading', () => {
  for (const beta of [60, 75, 105, 120]) {
    expect(degrees(headingOf(cameraFromDevice(20, beta, 0, 0)))).toBeCloseTo(20, 6);
  }
});

test('a phone turned to landscape still looks ahead', () => {
  // Upright, then a quarter turn about the screen's normal, which this frame calls Y. The screen
  // reports the same quarter turn, so the view must match the upright one.
  const turned = new THREE.Quaternion().setFromEuler(new THREE.Euler(Math.PI / 2, 0, 0, 'YXZ'))
    .multiply(new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 1, 0), Math.PI / 2));
  const euler = new THREE.Euler().setFromQuaternion(turned, 'YXZ');
  const landscape = cameraFromDevice(degrees(euler.y), degrees(euler.x), -degrees(euler.z), 90);
  expect(landscape.angleTo(cameraFromDevice(0, 90, 0, 0))).toBeLessThan(1e-6);
});
