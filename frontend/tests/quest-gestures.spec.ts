import { expect, test } from '@playwright/test';
import { Dwell, GestureGate, HeadNods, handPose, type HandJoints } from '../src/quest/gestures';

// Hand and head gestures on the headset page (#156), from WebXR joint positions in metres.

type Finger = 'index' | 'middle' | 'ring' | 'pinky';
const FINGERS: Finger[] = ['index', 'middle', 'ring', 'pinky'];
/** Each finger's sideways offset from the middle of the hand, in metres. */
const SIDE: Record<Finger, number> = { index: -0.025, middle: -0.005, ring: 0.015, pinky: 0.032 };

/**
 * A right hand, palm down, with the wrist at the origin and the fingers pointing forward (-z).
 * An extended finger runs straight on from its knuckle 9 cm ahead of the wrist; a curled one
 * folds back under the palm, its tip about 5 cm ahead of the wrist.
 */
function hand(extended: Finger[], thumbTip = { x: -0.07, y: 0, z: -0.06 }): HandJoints {
  const joints: HandJoints = { wrist: { x: 0, y: 0, z: 0 }, 'thumb-tip': thumbTip };
  for (const finger of FINGERS) {
    const x = SIDE[finger];
    const name = finger === 'pinky' ? 'pinky-finger' : `${finger}-finger`;
    joints[`${name}-phalanx-proximal` as keyof HandJoints] = { x, y: 0, z: -0.09 };
    joints[`${name}-tip` as keyof HandJoints] = extended.includes(finger)
      ? { x, y: 0, z: -0.17 }
      : { x, y: -0.03, z: -0.05 };
  }
  return joints;
}

test('a flat hand with the thumb away is an open palm', () => {
  expect(handPose(hand(FINGERS))).toBe('open-palm');
});

test('only the index finger straight is pointing; a fist is no pose', () => {
  expect(handPose(hand(['index']))).toBe('point');
  expect(handPose(hand([]))).toBe('none');
  // Index and middle together is neither pointing nor an open palm.
  expect(handPose(hand(['index', 'middle']))).toBe('none');
});

test('the thumb tip on the index tip is a pinch, whatever the other fingers do', () => {
  // 1 cm apart: touching.
  expect(handPose(hand(FINGERS, { x: -0.025, y: 0.01, z: -0.17 }))).toBe('pinch');
  expect(handPose(hand(['index'], { x: -0.025, y: 0.01, z: -0.17 }))).toBe('pinch');
  // 4 cm apart is not a pinch yet.
  expect(handPose(hand(FINGERS, { x: -0.025, y: 0.04, z: -0.17 }))).toBe('open-palm');
});

test('a hand the frame did not fully see is no pose', () => {
  const joints = hand(FINGERS);
  delete joints['ring-finger-tip'];
  expect(handPose(joints)).toBe('none');
  expect(handPose({})).toBe('none');
});

/** What the gate lets through for each frame's pose, one frame every `stepMs`. */
function run(gate: GestureGate<string>, poses: string[], stepMs = 100, from = 0): (string | null)[] {
  return poses.map((pose, frame) => gate.update(pose, from + frame * stepMs));
}

test('a pose fires once it is held long enough, and only once while held', () => {
  const gate = new GestureGate({ holdMs: 300, cooldownMs: 1000 });
  // Frames at 0, 100, 200, 300 ms: held 300 ms on the fourth frame.
  expect(run(gate, ['point', 'point', 'point', 'point', 'point', 'point'])).toEqual(
    [null, null, null, 'point', null, null]);
});

test('a pose broken off before its hold time does not fire', () => {
  const gate = new GestureGate({ holdMs: 300, cooldownMs: 1000 });
  expect(run(gate, ['point', 'point', 'none', 'point', 'point', 'none'])).toEqual(
    [null, null, null, null, null, null]);
});

test('after firing, the pose must be let go and the cool-down pass before it fires again', () => {
  const gate = new GestureGate({ holdMs: 200, cooldownMs: 1000 });
  // Fires at 200 ms, let go at 300 ms, held again from 400 ms: too soon until 1200 ms.
  expect(run(gate, ['open-palm', 'open-palm', 'open-palm', 'none', 'open-palm', 'open-palm', 'open-palm'])).toEqual(
    [null, null, 'open-palm', null, null, null, null]);
  expect(gate.update('open-palm', 1300)).toBe('open-palm');
});

/** A head turned `yawDeg` left, then tilted `pitchDeg` up (negative looks down). */
function head(yawDeg: number, pitchDeg: number) {
  const [y, p] = [yawDeg * Math.PI / 360, pitchDeg * Math.PI / 360];
  // The turn about the vertical, then the tilt about the head's own sideways axis.
  return { x: Math.cos(y) * Math.sin(p), y: Math.sin(y) * Math.cos(p), z: -Math.sin(y) * Math.sin(p), w: Math.cos(y) * Math.cos(p) };
}

/** What the nods report for each head pose, one every 50 ms. */
function watch(nods: HeadNods, poses: [number, number][]): (string | null)[] {
  return poses.map(([yaw, pitch], frame) => nods.update(head(yaw, pitch), frame * 50));
}

/** `swings` moves of `degrees` back and forth from level, four frames each way. */
function swinging(axis: 'yaw' | 'pitch', degrees: number, swings: number): [number, number][] {
  const out: [number, number][] = [[0, 0]];
  for (let swing = 0; swing < swings; swing++) {
    const to = swing % 2 === 0 ? -degrees : 0;
    const from = swing % 2 === 0 ? 0 : -degrees;
    for (let step = 1; step <= 4; step++) {
      const angle = from + (to - from) * step / 4;
      out.push(axis === 'yaw' ? [angle, 0] : [0, angle]);
    }
  }
  return out;
}

test('nodding down and up twice is yes, reported once', () => {
  const said = watch(new HeadNods(), swinging('pitch', 15, 4));
  expect(said.filter(Boolean)).toEqual(['yes']);
});

test('shaking the head side to side twice is no', () => {
  const said = watch(new HeadNods(), swinging('yaw', 15, 4));
  expect(said.filter(Boolean)).toEqual(['no']);
});

test('looking down once, or looking around, is neither', () => {
  expect(watch(new HeadNods(), swinging('pitch', 30, 2)).filter(Boolean)).toEqual([]);
  // A slow look to the left and back, over two seconds.
  const around: [number, number][] = Array.from({ length: 40 }, (_, frame) => [60 * Math.sin(Math.PI * frame / 39), 0]);
  expect(watch(new HeadNods(), around).filter(Boolean)).toEqual([]);
  // Small wobbles are not nods.
  expect(watch(new HeadNods(), swinging('pitch', 4, 6)).filter(Boolean)).toEqual([]);
});

test('resting the gaze on one object fills a dwell and starts it once', () => {
  const dwell = new Dwell(1500);
  expect(dwell.update('clock', 0)).toEqual({ target: 'clock', progress: 0, started: false });
  expect(dwell.update('clock', 750)).toEqual({ target: 'clock', progress: 0.5, started: false });
  expect(dwell.update('clock', 1500)).toEqual({ target: 'clock', progress: 1, started: true });
  // Still looking: already started, so not again.
  expect(dwell.update('clock', 2500)).toEqual({ target: 'clock', progress: 1, started: false });
});

test('looking elsewhere or at nothing starts the dwell over', () => {
  const dwell = new Dwell(1000);
  dwell.update('clock', 0);
  expect(dwell.update('piano', 800)).toEqual({ target: 'piano', progress: 0, started: false });
  expect(dwell.update(null, 900)).toEqual({ target: null, progress: 0, started: false });
  dwell.update('clock', 1000);
  expect(dwell.update('clock', 2000).started).toBe(true);
});
