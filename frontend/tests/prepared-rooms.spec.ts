import { expect, test, type Browser } from '@playwright/test';
import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import type { RoomEntity, RoomState } from '../src/protocol';
import { placeEntities } from '../src/room';

// Three's FileLoader reports download progress with the browser's ProgressEvent, which Node lacks.
globalThis.ProgressEvent ??= class extends Event {} as unknown as typeof ProgressEvent;

const rooms = [
  {
    form: 'single glTF', origin: 'http://127.0.0.1:8771', asset: 'room.gltf',
    ready: 'Room version 1 · floor, desk, cabinet, box (movable)',
  },
  {
    form: 'per-entity GLB', origin: 'http://127.0.0.1:8772', asset: 'mug.glb',
    ready: 'Room version 1 · floor, table, mug (movable), book (movable)',
  },
];

async function connectBoth(browser: Browser, origin: string, block?: string) {
  const phone = await browser.newPage({ viewport: { width: 390, height: 844 } });
  const vr = await browser.newPage();
  for (const page of [phone, vr]) {
    if (block) await page.route(`**/assets/prepared-room/${block}`, route => route.fulfill({ body: 'not a model' }));
    await page.goto(origin);
  }
  await phone.getByRole('button', { name: 'Connect phone', exact: true }).click();
  await vr.getByRole('button', { name: 'Connect VR headset', exact: true }).click();
  return [phone, vr];
}

for (const room of rooms) {
  test(`phone and headset load the same ${room.form} room`, async ({ browser }) => {
    const pages = await connectBoth(browser, room.origin);
    for (const page of pages) {
      await expect(page.getByTestId('room-status')).toHaveText(room.ready);
      await expect(page.getByRole('alert')).toBeHidden();
    }
    for (const page of pages) await page.close();
  });

  test(`a corrupt ${room.form} asset is a visible loading failure`, async ({ browser }) => {
    const pages = await connectBoth(browser, room.origin, room.asset);
    for (const page of pages) {
      const failure = `The prepared room asset ${room.asset} could not be loaded.`;
      await expect(page.getByRole('alert')).toHaveText(failure);
      await expect(page.getByTestId('room-status')).toHaveText(failure);
      await expect(page.getByTestId('room-status')).toHaveAttribute('data-available', 'false');
    }
    for (const page of pages) await page.close();
  });

  test(`${room.form} entities are placed once with their asset hierarchy intact`, async () => {
    const description = await (await fetch(`${room.origin}/api/room`)).json() as Omit<RoomState, 'loaded_by'>;
    expect(description).toMatchObject({ units: 'meters', frame: 'y_up_right_handed', quaternion_order: 'xyzw' });
    const loader = new GLTFLoader();
    const urls = [...new Set(description.entities.map(entity => entity.asset_url))];
    const scenes = await Promise.all(urls.map(async url => (
      [url, (await loader.loadAsync(`${room.origin}${url}`)).scene] as const
    )));
    const roots = placeEntities(new Map(scenes), description.entities);
    for (const entity of description.entities) {
      const root = roots.get(entity.id)!;
      root.updateMatrixWorld(true);
      const actual = new THREE.Box3().setFromObject(root, true);
      const expected = expectedBounds(entity);
      for (const corner of ['min', 'max'] as const) {
        for (const axis of ['x', 'y', 'z'] as const) {
          expect(actual[corner][axis], `${entity.id} ${corner}.${axis}`).toBeCloseTo(expected[corner][axis], 5);
        }
      }
    }
  });
}

/** Room-frame bounds of the declared bottom-center box under the manifest placement. */
function expectedBounds(entity: RoomEntity): THREE.Box3 {
  const { width, height, depth } = entity.size;
  const { x, y, z, w } = entity.rotation;
  const rotation = new THREE.Quaternion(x, y, z, w);
  const offset = new THREE.Vector3(entity.position.x, entity.position.y, entity.position.z);
  const bounds = new THREE.Box3();
  for (const cx of [-width / 2, width / 2]) {
    for (const cy of [0, height]) {
      for (const cz of [-depth / 2, depth / 2]) {
        bounds.expandByPoint(new THREE.Vector3(cx, cy, cz).applyQuaternion(rotation).add(offset));
      }
    }
  }
  return bounds;
}
