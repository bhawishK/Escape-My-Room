import { expect, test } from '@playwright/test';
import {
  Dwell, FIST_COOLDOWN_MS, FIST_HOLD_MS, GestureGate, HeadNods, RAISED_BELOW_HEAD_METRES,
  fistHeldUp, handPose, raised, unmuteHint, type FistHand, type HandJoints,
} from '../src/quest/gestures';
import { voiceNote, type VoiceStatus } from '../src/voice';

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

test('only the index finger straight is pointing', () => {
  expect(handPose(hand(['index']))).toBe('point');
  // Index and middle together is neither pointing nor an open palm.
  expect(handPose(hand(['index', 'middle']))).toBe('none');
});

test('all four fingers curled is a fist (#176)', () => {
  expect(handPose(hand([]))).toBe('fist');
});

test('a half-closed hand is not a fist', () => {
  // Any finger still straight, whichever it is.
  for (const finger of FINGERS) expect(handPose(hand([finger]))).not.toBe('fist');
  expect(handPose(hand(['middle', 'ring']))).toBe('none');
  expect(handPose(hand(['ring', 'pinky']))).toBe('none');
  expect(handPose(hand(FINGERS))).toBe('open-palm');
});

test('a pinch wins over a fist', () => {
  // The thumb tip 1 cm from the curled index tip.
  expect(handPose(hand([], { x: -0.025, y: -0.02, z: -0.05 }))).toBe('pinch');
});

test('a curled hand with a finger the frame did not see is not a fist', () => {
  for (const joint of ['pinky-finger-tip', 'index-finger-phalanx-proximal', 'wrist'] as const) {
    const joints = hand([]);
    delete joints[joint];
    expect(handPose(joints)).toBe('none');
  }
});

test('a hand is held up when its wrist is at chest height or above, not at the side', () => {
  const head = { x: 0, y: 1.6, z: 0 };
  const wristAt = (y: number) => ({ x: 0.2, y, z: -0.3 });
  // In front of the face, at the shoulder, and at the chest.
  for (const y of [1.7, 1.45, 1.2]) expect(raised(wristAt(y), head)).toBe(true);
  // Exactly at the limit counts; just under it does not.
  expect(raised(wristAt(1.6 - RAISED_BELOW_HEAD_METRES), head)).toBe(true);
  expect(raised(wristAt(1.6 - RAISED_BELOW_HEAD_METRES - 0.01), head)).toBe(false);
  // Hanging at the side, about 0.8 m below the head.
  expect(raised(wristAt(0.8), head)).toBe(false);
  // It follows the head: sitting down lowers the limit with it.
  expect(raised(wristAt(0.8), { x: 0, y: 1.1, z: 0 })).toBe(true);
});

test('a hand is not held up when its wrist or the head was not seen', () => {
  expect(raised(undefined, { x: 0, y: 1.6, z: 0 })).toBe(false);
  expect(raised({ x: 0, y: 1.6, z: 0 }, null)).toBe(false);
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

test('looking quickly from one thing to another and back is not a shake', () => {
  // Left, then over to the right, then to something ahead: quick, but somewhere new each time.
  const scan: [number, number][] = [[0, 0]];
  for (const [from, to] of [[0, 40], [40, -30], [-30, 10], [10, -45]] as const) {
    for (let step = 1; step <= 5; step++) scan.push([from + (to - from) * step / 5, 0]);
  }
  expect(watch(new HeadNods(), scan).filter(Boolean)).toEqual([]);
});

test('turning the head slowly back and forth, as when looking at a dollhouse, is not a shake', () => {
  // The same swings as a shake, but each over 700 ms.
  const slow: [number, number][] = [[0, 0]];
  for (let swing = 0; swing < 6; swing++) {
    const [from, to] = swing % 2 === 0 ? [0, -20] : [-20, 0];
    for (let step = 1; step <= 14; step++) slow.push([from + (to - from) * step / 14, 0]);
  }
  expect(watch(new HeadNods(), slow).filter(Boolean)).toEqual([]);
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

test('a shake while facing backwards is still no, not a jump all the way round', () => {
  // Facing 180°: the turn angle wraps from +180° to -180° within each swing.
  const backwards = swinging('yaw', 15, 4).map(([yaw, pitch]): [number, number] => [180 + 7.5 + yaw, pitch]);
  expect(watch(new HeadNods(), backwards).filter(Boolean)).toEqual(['no']);
  // Turning slowly across 180°, one way only, is neither.
  const across: [number, number][] = Array.from({ length: 20 }, (_, frame) => [170 + frame, 0]);
  expect(watch(new HeadNods(), across).filter(Boolean)).toEqual([]);
});

// The mute gesture (#175): a fist, held up, held for a moment.

const HEAD = { x: 0, y: 1.6, z: 0 };
const UP = { x: 0.2, y: 1.4, z: -0.3 };
const AT_SIDE = { x: 0.25, y: 0.8, z: 0 };
const fistHand = (changes: Partial<FistHand> = {}): FistHand => ({ pose: 'fist', wrist: UP, busy: false, ...changes });

test('a fist held up by a free hand is the mute gesture', () => {
  expect(fistHeldUp([fistHand()], HEAD)).toBe(true);
  // Either hand will do, whatever the other is doing.
  expect(fistHeldUp([fistHand({ pose: 'open-palm' }), fistHand()], HEAD)).toBe(true);
});

test('a fist at the side, a busy hand, and other poses are not the mute gesture', () => {
  expect(fistHeldUp([fistHand({ wrist: AT_SIDE })], HEAD)).toBe(false);
  // Pinching, or carrying an object.
  expect(fistHeldUp([fistHand({ busy: true })], HEAD)).toBe(false);
  for (const pose of ['open-palm', 'point', 'pinch', 'none'] as const) {
    expect(fistHeldUp([fistHand({ pose })], HEAD)).toBe(false);
  }
  // A controller has no wrist, and a lost head gives nothing to measure against.
  expect(fistHeldUp([fistHand({ wrist: null })], HEAD)).toBe(false);
  expect(fistHeldUp([fistHand()], null)).toBe(false);
  expect(fistHeldUp([], HEAD)).toBe(false);
});

/** Whether the fist gate mutes on each frame, 100 ms apart, for the frames a fist is held up. */
function fistFrames(gate: GestureGate<'fist'>, held: boolean[], from = 0): boolean[] {
  return held.map((fist, frame) => gate.update(fist ? 'fist' : 'none', from + frame * 100) !== null);
}

test('a fist mutes once it has been held 0.8 s, and only once however long it is held', () => {
  const gate = new GestureGate<'fist'>({ holdMs: FIST_HOLD_MS, cooldownMs: FIST_COOLDOWN_MS });
  // Frames at 0 to 2000 ms: the ninth, at 800 ms, is the only one that toggles.
  const fired = fistFrames(gate, Array<boolean>(21).fill(true));
  expect(fired.indexOf(true)).toBe(8);
  expect(fired.filter(Boolean)).toHaveLength(1);
});

test('a fist shorter than the hold, or one that wavers, does not mute', () => {
  const gate = new GestureGate<'fist'>({ holdMs: FIST_HOLD_MS, cooldownMs: FIST_COOLDOWN_MS });
  expect(fistFrames(gate, [true, true, true, true, true, false, false])).not.toContain(true);
  // Broken off for one frame at 500 ms: the hold starts over, and 700 ms more is not enough.
  expect(fistFrames(gate, [true, true, true, true, true, false, true, true, true, true, true, true, true, false], 2000)).not.toContain(true);
});

test('a second fist unmutes only after the hand is let go and the cool-down has passed', () => {
  const gate = new GestureGate<'fist'>({ holdMs: FIST_HOLD_MS, cooldownMs: FIST_COOLDOWN_MS });
  const held = Array<boolean>(9).fill(true);
  // Mutes at 800 ms.
  expect(fistFrames(gate, held).filter(Boolean)).toHaveLength(1);
  // Let go at 900 ms, and a new fist from 1000 ms: held 0.8 s at 1800 ms, but the cool-down
  // runs to 2300 ms, so it toggles on the frame at 2300 ms.
  expect(gate.update('none', 900)).toBeNull();
  const again = fistFrames(gate, Array<boolean>(16).fill(true), 1000);
  expect(again.indexOf(true)).toBe(13);
  expect(again.filter(Boolean)).toHaveLength(1);
});

test('the line in the headset names the fist with hands, and B or Y with controllers', () => {
  const muted: VoiceStatus = { phase: 'connected', problem: null, receiving: true, muted: true, peerMuted: false, path: null };
  expect(voiceNote(muted, 'the phone', unmuteHint('hands'))).toBe('You are muted · hold up a fist to unmute');
  expect(voiceNote(muted, 'the phone', unmuteHint('controllers'))).toBe('You are muted · press B or Y to unmute');
  // Before any hand or controller is seen, hands are assumed: the page is moving to them.
  expect(unmuteHint('none')).toBe('hold up a fist');
});
