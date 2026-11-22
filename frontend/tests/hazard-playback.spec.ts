import { expect, test } from '@playwright/test';
import { ServerClock, frameAt, frameUrl, hideBox, type SessionHazard } from '../src/hazard-playback';
import type { RoomEntity } from '../src/protocol';

// Playing a hazard's 4D frames (#230): the frame shown when, the server's clock, and the box hidden.

const HAZARD: SessionHazard = {
  id: 'hazard_1',
  asset: 'hz_0123abcd',
  hazard: 'catches fire',
  frames: 40,
  frames_per_second: 16,
  frame_url: '/api/hazards/hz_0123abcd/frames/{n}.spz',
  seconds: 2.5,
  loops: false,
  placement: { position: [0.1, 0, -0.5], turn: 0, scale: 2, hide: 'bed' },
  hide: 'bed',
  playing: true,
  started_at: 10_000,
};

test('stopped or not yet started, the first frame shows: the object not yet burning', () => {
  expect(frameAt({ ...HAZARD, playing: false, started_at: null }, 20_000)).toBe(0);
  expect(frameAt(HAZARD, 9_999)).toBe(0);
});

test('started, it plays at its frame rate: 16 frames a second', () => {
  expect(frameAt(HAZARD, 10_000)).toBe(0);
  expect(frameAt(HAZARD, 10_500)).toBe(8);
  expect(frameAt(HAZARD, 12_400)).toBe(38);
});

test('after its end it keeps burning by playing its last second over and over', () => {
  // 40 frames end at 2.5 s; the last second is frames 24 to 39.
  expect(frameAt(HAZARD, 12_500)).toBe(24);
  expect(frameAt(HAZARD, 13_437)).toBe(38);
  expect(frameAt(HAZARD, 13_500)).toBe(24);
  for (let ms = 12_500; ms < 30_000; ms += 37) {
    const frame = frameAt(HAZARD, ms);
    expect(frame).toBeGreaterThanOrEqual(24);
    expect(frame).toBeLessThan(40);
  }
});

test('a hazard that loops starts again from its first frame', () => {
  expect(frameAt({ ...HAZARD, loops: true }, 12_500)).toBe(0);
  expect(frameAt({ ...HAZARD, loops: true }, 13_000)).toBe(8);
});

test('the server clock is the sample with the least delay', () => {
  const clock = new ServerClock();
  expect(clock.known).toBe(false);
  // The server is 5 s ahead; states arrive 80, 20 and 200 ms after they were made.
  clock.sample(105_000, 100_080);
  clock.sample(106_000, 101_020);
  clock.sample(107_000, 102_200);
  expect(clock.known).toBe(true);
  expect(clock.now(103_000)).toBe(108_000 - 20);
});

test('two devices with different clocks and delays show the same frame at the same moment', () => {
  const headset = new ServerClock();
  const phone = new ServerClock();
  // The same real moment: the server reads 50 000; the headset 49 000; the phone 61 000.
  headset.sample(50_000, 49_000 + 15);
  phone.sample(50_000, 61_000 + 15);
  const atStart = (clock: ServerClock, local: number) => frameAt({ ...HAZARD, started_at: 50_500 }, clock.now(local));
  expect(atStart(headset, 49_000 + 1_000)).toBe(atStart(phone, 61_000 + 1_000));
});

test('frame addresses fill in the number', () => {
  expect(frameUrl(HAZARD, 7)).toBe('/api/hazards/hz_0123abcd/frames/7.spz');
});

test('the hidden box is the object\'s, a little bigger, centred halfway up, turned with it', () => {
  const bed: RoomEntity = {
    id: 'bed', label: 'Bed', asset_url: '/a.glb', node: 'bed', kind: 'static', selectable: false,
    position: { x: 1, y: 0, z: -2 },
    rotation: { x: 0, y: Math.sin(Math.PI / 4), z: 0, w: Math.cos(Math.PI / 4) },
    size: { width: 2, height: 0.5, depth: 1 },
  };
  const box = hideBox([bed], 'bed');
  expect(box).not.toBeNull();
  expect(box!.centre).toEqual({ x: 1, y: 0.25, z: -2 });
  expect(box!.yaw).toBeCloseTo(Math.PI / 2, 9);
  expect(box!.half.x).toBeCloseTo(1.1, 9);
  expect(box!.half.y).toBeCloseTo(0.275, 9);
  expect(box!.half.z).toBeCloseTo(0.55, 9);
  expect(hideBox([bed], 'sofa')).toBeNull();
  expect(hideBox([bed], null)).toBeNull();
});
