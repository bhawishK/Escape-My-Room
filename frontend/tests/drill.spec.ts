import { expect, test } from '@playwright/test';
import type { SessionHazard } from '../src/hazard-playback';
import type { RoomEntity } from '../src/protocol';
import { drillLine, drillPlaying, objectAt, type DrillState } from '../src/quest/drill';

// The headset's drill (#234): what a fingertip touches, and what the Drill page says.

const entity = (id: string, label: string, at: [number, number], size: [number, number, number], yaw = 0): RoomEntity => ({
  id, label, asset_url: '/a.glb', node: id, kind: 'static', selectable: false,
  position: { x: at[0], y: 0, z: at[1] },
  rotation: { x: 0, y: Math.sin(yaw / 2), z: 0, w: Math.cos(yaw / 2) },
  size: { width: size[0], height: size[1], depth: size[2] },
});

const BED = entity('layout_bed_2', 'Bed', [0, -1], [2, 0.5, 1]);
const LAMP = entity('lamp', 'Lamp', [0.8, -1.2], [0.2, 1.2, 0.2]);
const FLOOR = entity('floor', 'Floor', [0, 0], [4, 0.02, 4]);
const ROOM = [FLOOR, BED, LAMP];

test('a fingertip in an object\'s box touches it; on the floor or in the air, nothing', () => {
  expect(objectAt(ROOM, { x: 0.5, y: 0.3, z: -1.2 })?.id).toBe('layout_bed_2');
  // Just above its top, within the margin, still the bed.
  expect(objectAt(ROOM, { x: 0, y: 0.53, z: -1 })?.id).toBe('layout_bed_2');
  expect(objectAt(ROOM, { x: 0, y: 1.5, z: -1 })).toBeNull();
  expect(objectAt(ROOM, { x: 1.8, y: 0.01, z: 1.8 })).toBeNull();
});

test('where two boxes overlap, the smaller object is the one touched', () => {
  expect(objectAt(ROOM, { x: 0.8, y: 0.3, z: -1.2 })?.id).toBe('lamp');
});

test('a turned object is touched along its turned length', () => {
  const turned = entity('sofa', 'Sofa', [2, 2], [2, 0.8, 0.8], Math.PI / 2);
  // Turned a quarter, its 2 m length runs along z.
  expect(objectAt([turned], { x: 2, y: 0.4, z: 2.9 })?.id).toBe('sofa');
  expect(objectAt([turned], { x: 2.9, y: 0.4, z: 2 })).toBeNull();
});

const HAZARD = { id: 'hazard_3', playing: false } as SessionHazard;
const drill = (state: DrillState['state'], extra: Partial<DrillState> = {}): DrillState => ({
  entity: 'layout_bed_2', hazard: 'catches fire', state, job: null, hazard_id: null, error: null, ...extra,
});

test('the Drill page says what to do, the plan, and how far along it is', () => {
  expect(drillLine(null, ROOM, [], false, null)).toBe('Choose an object for the drill');
  expect(drillLine(null, ROOM, [], true, null)).toBe('Touch an object to set it on fire');
  expect(drillLine(drill('preparing', { job: 'j1' }), ROOM, [], false, 'image_ready'))
    .toBe('Bed catches fire · picture done, making the video…');
  expect(drillLine(drill('ready', { hazard_id: 'hazard_3' }), ROOM, [HAZARD], false, null))
    .toBe('Bed catches fire · ready, pinch Start');
  expect(drillLine(drill('ready', { hazard_id: 'hazard_3' }), ROOM, [{ ...HAZARD, playing: true }], false, null))
    .toBe('Bed catches fire · running, Stop to end');
  expect(drillLine(drill('failed', { error: 'The generator took too long.' }), ROOM, [], false, null))
    .toBe('Couldn\'t prepare: The generator took too long.');
});

test('the drill is playing only while its own fire plays', () => {
  const ready = drill('ready', { hazard_id: 'hazard_3' });
  expect(drillPlaying(ready, [HAZARD])).toBe(false);
  expect(drillPlaying(ready, [{ ...HAZARD, playing: true }])).toBe(true);
  expect(drillPlaying(ready, [{ ...HAZARD, id: 'hazard_9', playing: true }])).toBe(false);
  expect(drillPlaying(null, [{ ...HAZARD, playing: true }])).toBe(false);
});
