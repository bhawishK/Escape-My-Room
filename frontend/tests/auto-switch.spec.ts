import { expect, test } from '@playwright/test';
import { AutoSwitchScheduler } from '../src/auto-switch';

const still = { position: { x: 0.3, y: 1.5, z: 1 }, orientation: { x: 0, y: 0, z: 0, w: 1 } };
/** Turned `degrees` to the left about the vertical. */
const turned = (degrees: number) => ({
  position: still.position,
  orientation: { x: 0, y: Math.sin(degrees * Math.PI / 360), z: 0, w: Math.cos(degrees * Math.PI / 360) },
});

/** Feeds frames 50 ms apart from `from` to `to` ms, all tracked, at the pose `at(t)` gives. */
function track(scheduler: AutoSwitchScheduler, from: number, to: number, at: (t: number) => typeof still = () => still): void {
  for (let t = from; t <= to; t += 50) scheduler.observe(t, true, at(t));
}

test('a switch is due only after 3 s of normal tracking and 1 s holding still', () => {
  const scheduler = new AutoSwitchScheduler();
  track(scheduler, 0, 2900);
  expect(scheduler.due(2900, true)).toBe(false);
  track(scheduler, 2950, 3000);
  expect(scheduler.due(3000, true)).toBe(true);
  // Something else busy, such as a carried box, means no switch.
  expect(scheduler.due(3000, false)).toBe(false);
});

test('moving or turning the phone, or losing tracking, holds the switch back', () => {
  const moving = new AutoSwitchScheduler();
  track(moving, 0, 4000, t => ({ ...still, position: { ...still.position, x: t / 4000 } }));
  expect(moving.due(4000, true)).toBe(false);

  const turning = new AutoSwitchScheduler();
  // 40° a second, twice the limit.
  track(turning, 0, 4000, t => turned(40 * t / 1000));
  expect(turning.due(4000, true)).toBe(false);

  const tilting = new AutoSwitchScheduler();
  // Tilting down toward the floor at 40° a second, heading unchanged.
  const tilt = (t: number) => -40 * t / 1000 * Math.PI / 360;
  track(tilting, 0, 4000, t => ({ ...still, orientation: { x: Math.sin(tilt(t)), y: 0, z: 0, w: Math.cos(tilt(t)) } }));
  expect(tilting.due(4000, true)).toBe(false);

  const lost = new AutoSwitchScheduler();
  track(lost, 0, 3000);
  lost.observe(3050, false, still);
  track(lost, 3100, 5000);
  // Tracking has been normal again for only 1.9 s.
  expect(lost.due(5000, true)).toBe(false);
  track(lost, 5050, 6100);
  expect(lost.due(6100, true)).toBe(true);
});

test('switches come every 15 s until 3 have measured the eyes, then every 60 s', () => {
  const scheduler = new AutoSwitchScheduler();
  let now = 3000;
  track(scheduler, 0, now);
  for (let measured = 1; measured <= 3; measured++) {
    expect(scheduler.due(now, true)).toBe(true);
    scheduler.finished(now + 2500, { worked: true, eyesFound: true });
    track(scheduler, now + 2550, now + 2500 + 14900);
    // Not yet 15 s since the last switch ended.
    expect(scheduler.due(now + 2500 + 14900, true)).toBe(false);
    now += 2500 + 15000;
    track(scheduler, now - 50, now);
    expect(scheduler.due(now, true)).toBe(measured < 3);
  }
  track(scheduler, now + 50, now + 2500 + 60000);
  expect(scheduler.due(now + 2500 + 60000, true)).toBe(true);
});

test('after a switch where tracking did not come back, the next waits 60 s', () => {
  const scheduler = new AutoSwitchScheduler();
  track(scheduler, 0, 3000);
  scheduler.finished(13000, { worked: false, eyesFound: true });
  track(scheduler, 13050, 13000 + 59900);
  expect(scheduler.due(13000 + 59900, true)).toBe(false);
  track(scheduler, 13000 + 59950, 13000 + 60000);
  expect(scheduler.due(13000 + 60000, true)).toBe(true);
});

test('a scale shortens every interval, for tests', () => {
  const scheduler = new AutoSwitchScheduler(0.1);
  track(scheduler, 0, 300);
  expect(scheduler.due(300, true)).toBe(true);
});

test('a gap in observing tracking starts the steady count again', () => {
  const scheduler = new AutoSwitchScheduler();
  track(scheduler, 0, 3000);
  // The room view was closed for a while; tracking is watched again from 10 s.
  track(scheduler, 10000, 11000);
  expect(scheduler.due(11000, true)).toBe(false);
  track(scheduler, 11050, 13000);
  expect(scheduler.due(13000, true)).toBe(true);
});
