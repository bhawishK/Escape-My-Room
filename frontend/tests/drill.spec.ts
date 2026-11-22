import { expect, test } from '@playwright/test';
import type { SessionHazard } from '../src/hazard-playback';
import type { RoomEntity } from '../src/protocol';
import { drillLine, drillObjects, drillPlaying, type DrillState } from '../src/quest/drill';

// The headset's drill (#234): which objects the Drill menu offers, and what it says.

const entity = (id: string, label: string): RoomEntity => ({
  id, label, asset_url: '/a.glb', node: id, kind: 'static', selectable: false,
  position: { x: 0, y: 0, z: 0 }, rotation: { x: 0, y: 0, z: 0, w: 1 },
  size: { width: 1, height: 1, depth: 1 },
});

const BED = entity('layout_bed_2', 'Bed');
const DESK = entity('layout_desk_1', 'Desk');
const ROOM = [entity('floor', 'Floor'), BED, entity('wall_left', 'Wall'), DESK];

test('the Drill menu offers the room\'s objects, not its floor or walls, in the room\'s order', () => {
  expect(drillObjects(ROOM).map(object => object.id)).toEqual(['layout_bed_2', 'layout_desk_1']);
});

const HAZARD = { id: 'hazard_3', playing: false } as SessionHazard;
const drill = (state: DrillState['state'], extra: Partial<DrillState> = {}): DrillState => ({
  entity: 'layout_bed_2', hazard: 'catches fire', state, job: null, hazard_id: null, error: null, ...extra,
});

test('the Drill page says what to do, the plan, and how far along it is', () => {
  expect(drillLine(null, ROOM, [], null, null)).toBe('Choose an object, then pinch Prepare');
  expect(drillLine(null, ROOM, [], 'layout_desk_1', null)).toBe('Desk · pinch Prepare');
  expect(drillLine(drill('preparing', { job: 'j1' }), ROOM, [], 'layout_bed_2', 'image_ready'))
    .toBe('Bed catches fire · picture done, making the video…');
  expect(drillLine(drill('ready', { hazard_id: 'hazard_3' }), ROOM, [HAZARD], 'layout_bed_2', null))
    .toBe('Bed catches fire · ready, pinch Start');
  expect(drillLine(drill('ready', { hazard_id: 'hazard_3' }), ROOM, [{ ...HAZARD, playing: true }], null, null))
    .toBe('Bed catches fire · running, Stop to end');
  expect(drillLine(drill('failed', { error: 'The generator took too long.' }), ROOM, [], null, null))
    .toBe('Couldn\'t prepare: The generator took too long.');
});

test('choosing another object than the drill\'s says Prepare would move the drill to it', () => {
  expect(drillLine(drill('ready', { hazard_id: 'hazard_3' }), ROOM, [HAZARD], 'layout_desk_1', null))
    .toBe('Desk · pinch Prepare');
});

test('the drill is playing only while its own fire plays', () => {
  const ready = drill('ready', { hazard_id: 'hazard_3' });
  expect(drillPlaying(ready, [HAZARD])).toBe(false);
  expect(drillPlaying(ready, [{ ...HAZARD, playing: true }])).toBe(true);
  expect(drillPlaying(ready, [{ ...HAZARD, id: 'hazard_9', playing: true }])).toBe(false);
  expect(drillPlaying(null, [{ ...HAZARD, playing: true }])).toBe(false);
});
