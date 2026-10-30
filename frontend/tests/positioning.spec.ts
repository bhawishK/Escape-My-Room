import { type Browser, type Page, expect, test } from '@playwright/test';
import { FixFusion, focalLength } from '../src/positioning';
import type { RoomPose } from '../src/phone-view';
import { INITIALIZING, closeMap, engineCalls, engineFrame, useFakeEngine } from './fixtures/fake-engine';

// Visual positioning (#133): the phone sends 8th Wall's camera frames to Python, and the fixes
// line 8th Wall's world up with the room.

const LEVEL = { x: 0, y: 0, z: 0, w: 1 };
/** Turned `degrees` to the left about the vertical. */
const turned = (degrees: number) => {
  const half = degrees * Math.PI / 360;
  return { x: 0, y: Math.sin(half), z: 0, w: Math.cos(half) };
};
const pose = (x: number, y: number, z: number, orientation = LEVEL): RoomPose => ({ position: { x, y, z }, orientation });

/** Where 8th Wall's `engine` pose is in a room turned `yaw` degrees left, `scale` larger and moved. */
function inRoom(engine: RoomPose, yaw: number, scale: number, shift: { x: number; y: number; z: number }): RoomPose {
  const [c, s] = [Math.cos(yaw * Math.PI / 180), Math.sin(yaw * Math.PI / 180)];
  const { x, y, z } = engine.position;
  return pose(shift.x + scale * (c * x + s * z), shift.y + scale * y, shift.z + scale * (-s * x + c * z), turned(yaw));
}

function expectNear(actual: RoomPose | null, expected: RoomPose, metres = 0.01): void {
  expect(actual).not.toBeNull();
  for (const axis of ['x', 'y', 'z'] as const) expect(Math.abs(actual!.position[axis] - expected.position[axis])).toBeLessThan(metres);
}

test('the frame’s focal length comes from the side the canvas shows whole', () => {
  // A portrait canvas narrower than the 480 x 640 frame shows all of its height: f = P11 x 640 / 2.
  expect(focalLength([3, 0, 0, 0, 0, 1.5, 0, 0], 480, 640)).toBe(480);
  // A wide canvas shows all of the frame's width.
  expect(focalLength([1, 0, 0, 0, 0, 2, 0, 0], 480, 640)).toBe(240);
  expect(focalLength([0, 0, 0, 0, 0, 0, 0, 0], 480, 640)).toBeNull();
});

test('the first fix lines 8th Wall’s world up with the room: its turn and place', () => {
  const fusion = new FixFusion();
  const engine = pose(0.3, 1.5, 1.2);
  const room = pose(2, 1.4, -1, turned(90));

  expect(fusion.add(engine, room, 1, 0)).toEqual({ accepted: true, replaced: false });

  expectNear(fusion.toRoom(engine, 0), room);
  // A metre forward in 8th Wall (-z) is a metre forward in the room, which faces -x there.
  expectNear(fusion.toRoom(pose(0.3, 1.5, 0.2), 0), pose(1, 1.4, -1));
});

test('once the fixes spread, the scale comes from them', () => {
  const fusion = new FixFusion();
  const shift = { x: 1, y: 0.2, z: -2 };
  for (let i = 0; i < 5; i++) {
    const engine = pose(0.5 * i, 1.2, -0.3 * i);
    fusion.add(engine, inRoom(engine, 30, 1.25, shift), 1, i * 1000);
  }

  const lineUp = fusion.lineUp!;
  expect(lineUp.scale).toBeCloseTo(1.25, 3);
  expect(lineUp.yaw).toBeCloseTo(Math.PI / 6, 3);
  const elsewhere = pose(-1, 1.3, 2);
  expectNear(fusion.toRoom(elsewhere, 10_000), inRoom(elsewhere, 30, 1.25, shift));
});

test('a fix that disagrees is rejected, and three that agree with each other replace the line-up', () => {
  const fusion = new FixFusion();
  fusion.add(pose(0, 1.5, 0), pose(0, 1.5, 0), 1, 0);

  // Two metres off, as a match on the wrong copy of a repeated pattern can be.
  const wrong = fusion.add(pose(0.1, 1.5, 0), pose(2.1, 1.5, 0), 1, 1000);
  expect(wrong).toEqual({ accepted: false, reason: '2.00 m from where tracking has the phone' });
  expect(fusion.add(pose(0.2, 1.5, 0), pose(2.2, 1.5, 0), 1, 2000).accepted).toBe(false);
  // The third in a row that agrees with the other two: 8th Wall had drifted, the fixes are right.
  expect(fusion.add(pose(0.3, 1.5, 0), pose(2.3, 1.5, 0), 1, 3000)).toEqual({ accepted: true, replaced: true });
  expectNear(fusion.toRoom(pose(0.3, 1.5, 0), 4000), pose(2.3, 1.5, 0));
});

test('a new line-up is blended in, so the view does not jump', () => {
  const fusion = new FixFusion();
  fusion.add(pose(0, 1.5, 0), pose(0, 1.5, 0), 1, 0);
  // 30 cm on: within what still agrees, so the line-up moves to the middle of the two fixes.
  fusion.add(pose(0, 1.5, 0), pose(0.3, 1.5, 0), 1, 1000);
  const engine = pose(0, 1.5, 0);

  expectNear(fusion.toRoom(engine, 1000), pose(0, 1.5, 0));
  expectNear(fusion.toRoom(engine, 1250), pose(0.075, 1.5, 0));
  expectNear(fusion.toRoom(engine, 1500), pose(0.15, 1.5, 0));
});

/** A phone with a camera image and the headset, both in the room view. */
async function connect(browser: Browser): Promise<{ phone: Page; vr: Page; version: number }> {
  const phone = await browser.newPage({ viewport: { width: 390, height: 844 } });
  const vr = await browser.newPage();
  await useFakeEngine(phone, { camera: true });
  await vr.goto('/');
  await vr.getByRole('button', { name: 'Connect VR headset', exact: true }).click();
  await phone.goto('/');
  await phone.getByRole('button', { name: 'Connect phone', exact: true }).click();
  await closeMap(phone);
  await expect(phone.locator('#scene')).toHaveAttribute('data-view', 'phone');
  const version = (await (await phone.request.get('/api/room')).json()).room_version as number;
  return { phone, vr, version };
}

/** Answers the phone's frames in turn with `answers`; returns the frames it sent. */
async function answerFrames(page: Page, answers: Record<string, unknown>[]): Promise<{ count: number; forms: string[] }> {
  const sent = { count: 0, forms: [] as string[] };
  await page.route('**/api/localize', route => {
    const answer = answers[Math.min(sent.count, answers.length - 1)];
    sent.count++;
    sent.forms.push(route.request().postData() ?? '');
    return route.fulfill({ json: answer });
  });
  return sent;
}

const located = (version: number, x: number, y: number, z: number, orientation: object) => ({
  located: true, room_version: version, position: { x, y, z }, orientation, inliers: 240, matches: 600, reason: null,
  seconds: { total: 0.15 },
});
const notLocated = (version: number) => ({
  located: false, room_version: version, position: null, orientation: null, inliers: 4, matches: 80,
  reason: 'only 4 matches agree; 30 are needed', seconds: { total: 0.12 },
});

test('a fix puts the phone where the camera sees it is, and 8th Wall moves it from there', async ({ browser }) => {
  const { phone, vr, version } = await connect(browser);
  const sent = await answerFrames(phone, [located(version, 2, 1.4, -1, turned(90))]);

  // The first frame asks for a picture, the next draws it, the third reads it and sends it.
  for (let i = 0; i < 3; i++) await engineFrame(phone, { x: 0, y: 1.6, z: 1.6 });
  await expect.poll(() => sent.count).toBe(1);
  expect(sent.forms[0]).toContain('name="fx"\r\n\r\n480');
  expect(sent.forms[0]).toContain('name="width"\r\n\r\n480');
  expect(sent.forms[0]).toContain('image/jpeg');
  expect((await engineCalls(phone)).framesRead).toBe(1);

  await expect(vr.getByTestId('marker-position')).toHaveText('2.00, 1.40, -1.00 m');
  // A metre forward for 8th Wall is a metre forward in the room, which faces -x where the fix put it.
  await engineFrame(phone, { x: 0, y: 1.6, z: 0.6 });
  await expect(vr.getByTestId('marker-position')).toHaveText('1.00, 1.40, -1.00 m');
  await phone.close();
  await vr.close();
});

test('a fix while 8th Wall is lost places the phone, and its restart carries on from there', async ({ browser }) => {
  const { phone, vr, version } = await connect(browser);
  const sent = await answerFrames(phone, [notLocated(version), located(version, 2, 1.4, -1, turned(90))]);
  for (let i = 0; i < 3; i++) await engineFrame(phone, { x: 0, y: 1.6, z: 1.6 });
  await expect.poll(() => sent.count).toBe(1);

  // Lost on a turn; frames go twice a second while lost.
  await phone.waitForTimeout(600);
  for (let i = 0; i < 3; i++) await engineFrame(phone, { x: 0, y: 1.6, z: 1.6 }, LEVEL, INITIALIZING);
  await expect.poll(() => sent.count).toBe(2);
  // 8th Wall restarts at its starting place facing the desk: lined up with the fix, no tapping.
  await engineFrame(phone, { x: 0, y: 1.5, z: 1.6 });

  await expect(vr.getByTestId('marker-position')).toHaveText('2.00, 1.40, -1.00 m');
  await expect(phone.locator('#phone-map')).not.toHaveClass(/expanded/);
  await phone.close();
  await vr.close();
});

test('a room without a positioning map is asked once, and no more frames are sent', async ({ browser }) => {
  // The test room has no positioning map, so Python refuses.
  const { phone, vr } = await connect(browser);
  const asked: number[] = [];
  phone.on('response', response => {
    if (response.url().endsWith('/api/localize')) asked.push(response.status());
  });

  for (let i = 0; i < 3; i++) await engineFrame(phone, { x: 0, y: 1.6, z: 1.6 });
  await expect.poll(() => asked).toEqual([404]);
  await phone.waitForTimeout(1200);
  for (let i = 0; i < 4; i++) await engineFrame(phone, { x: 0, y: 1.6, z: 1.6 });
  await phone.waitForTimeout(300);

  expect(asked).toEqual([404]);
  // 8th Wall still tracks as before.
  await expect(vr.getByTestId('marker-position')).toHaveText('0.00, 1.60, 1.60 m');
  await phone.close();
  await vr.close();
});
