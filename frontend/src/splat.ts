// Spike #92: view a room splat trained from a video, to judge its look, scale and frame rate on
// the phone, the Quest and the desktop. Throwaway: nothing else imports this page.
import './style.css';
import './splat.css';
import * as THREE from 'three';
import { SparkControls, SparkRenderer, SparkXr, SplatMesh } from '@sparkjsdev/spark';

const EYE_HEIGHT = 1.4;
const TAP_PIXELS = 8;

function element<T extends HTMLElement>(id: string): T {
  return document.getElementById(id) as T;
}

const status = element<HTMLParagraphElement>('splat-status');
const measureButton = element<HTMLButtonElement>('measure');
const gridButton = element<HTMLButtonElement>('grid');
const measureResult = element<HTMLParagraphElement>('measure-result');
const scaleForm = element<HTMLFormElement>('scale-form');
const realLength = element<HTMLInputElement>('real-length');
const scaleNote = element<HTMLParagraphElement>('scale-note');

const renderer = new THREE.WebGLRenderer({ antialias: false });
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
renderer.setSize(window.innerWidth, window.innerHeight);
element('splat-view').append(renderer.domElement);

const scene = new THREE.Scene();
scene.background = new THREE.Color(0x1d1d1f);
const camera = new THREE.PerspectiveCamera(70, window.innerWidth / window.innerHeight, 0.05, 200);
camera.position.set(0, EYE_HEIGHT, 0);
// The rig stands on the room's floor at its origin; controls and VR thumbsticks move the rig.
const rig = new THREE.Group();
rig.add(camera);
scene.add(rig);
scene.add(new SparkRenderer({ renderer }));

const grid = new THREE.GridHelper(10, 20, 0xff9500, 0xaeaeb2);
grid.position.y = 0.002;
scene.add(grid);

const controls = new SparkControls({ canvas: renderer.domElement });
const xr = new SparkXr({
  renderer,
  mode: 'vr',
  referenceSpaceType: 'local-floor',
  // Turn and walk on the floor only, so the room stays level.
  controllers: { moveDirection: true, getRotate: pads => new THREE.Vector3(pads.right?.axes[2] ?? 0, 0, 0) },
});

window.addEventListener('resize', () => {
  camera.aspect = window.innerWidth / window.innerHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(window.innerWidth, window.innerHeight);
});

// Scale ----------------------------------------------------------------------------------------
// The notebook scales the room by assuming the phone was held 1.4 m up. Measuring a known
// length here corrects that; the correction is remembered per file in this browser.

let source = new URLSearchParams(window.location.search).get('src') ?? '/spike/room.ply';
let room: SplatMesh | undefined;

function scaleKey(): string {
  return `splat-scale:${source}`;
}

function savedScale(): number {
  try {
    const value = Number(window.localStorage.getItem(scaleKey()));
    return value > 0 ? value : 1;
  } catch {
    return 1;
  }
}

function applyScale(scale: number): void {
  room?.scale.setScalar(scale);
  scaleNote.textContent = scale === 1
    ? 'Scale assumes the phone was held 1.4 m up. Measure a known length to correct it.'
    : `Scale corrected by ×${scale.toFixed(3)} from a measured length.`;
}

// Loading --------------------------------------------------------------------------------------

async function load(bytes: ArrayBuffer, name: string, started: number): Promise<void> {
  status.textContent = `Preparing ${name}…`;
  clearMeasure();
  if (room) {
    scene.remove(room);
    room.dispose();
  }
  const mesh = new SplatMesh({ fileBytes: bytes, fileName: name, raycastable: true });
  scene.add(mesh);
  await mesh.initialized;
  room = mesh;
  applyScale(savedScale());
  element('stat-splats').textContent = (mesh.packedSplats?.numSplats ?? 0).toLocaleString();
  element('stat-size').textContent = `${(bytes.byteLength / 1e6).toFixed(1)} MB`;
  element('stat-load').textContent = `${((performance.now() - started) / 1000).toFixed(1)} s`;
  status.textContent = xr.xrSupported()
    ? 'Drag to look around, or enter VR to stand in the room.'
    : 'Drag to look around; two fingers or arrow keys to move.';
}

async function loadUrl(url: string): Promise<void> {
  const started = performance.now();
  status.textContent = `Downloading ${url}…`;
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`${url} answered ${response.status}. Put the notebook's room.ply in frontend/public/spike/.`);
  }
  await load(await response.arrayBuffer(), url.split('/').pop() ?? 'room.ply', started);
}

element<HTMLInputElement>('splat-file').addEventListener('change', event => {
  const file = (event.target as HTMLInputElement).files?.[0];
  if (!file) return;
  source = `file:${file.name}`;
  const started = performance.now();
  void file.arrayBuffer()
    .then(bytes => load(bytes, file.name, started))
    .catch((error: unknown) => { status.textContent = String(error); });
});

// Measuring ------------------------------------------------------------------------------------

let measuring = false;
const picked: THREE.Vector3[] = [];
const marks = new THREE.Group();
scene.add(marks);
const raycaster = new THREE.Raycaster();

function clearMeasure(): void {
  picked.length = 0;
  marks.clear();
  measureResult.hidden = true;
  scaleForm.hidden = true;
}

function mark(point: THREE.Vector3): void {
  const dot = new THREE.Mesh(
    new THREE.SphereGeometry(0.015, 12, 8),
    new THREE.MeshBasicMaterial({ color: 0xff2d55, depthTest: false }),
  );
  dot.position.copy(point);
  dot.renderOrder = 1;
  marks.add(dot);
}

function measured(): number {
  return picked[0].distanceTo(picked[1]);
}

function pick(x: number, y: number): void {
  if (!room) return;
  const rect = renderer.domElement.getBoundingClientRect();
  const pointer = new THREE.Vector2(((x - rect.left) / rect.width) * 2 - 1, -((y - rect.top) / rect.height) * 2 + 1);
  raycaster.setFromCamera(pointer, camera);
  const [hit] = raycaster.intersectObject(room, false);
  if (!hit) {
    measureResult.hidden = false;
    measureResult.textContent = 'Nothing there to measure; tap on the room.';
    return;
  }
  if (picked.length === 2) clearMeasure();
  picked.push(hit.point.clone());
  mark(hit.point);
  measureResult.hidden = false;
  if (picked.length === 1) {
    measureResult.textContent = 'Tap the other end.';
    return;
  }
  marks.add(new THREE.Line(
    new THREE.BufferGeometry().setFromPoints(picked),
    new THREE.LineBasicMaterial({ color: 0xff2d55, depthTest: false }),
  ));
  measureResult.textContent = `${measured().toFixed(3)} m in the model`;
  scaleForm.hidden = false;
  realLength.focus();
}

let down: { x: number; y: number } | undefined;
renderer.domElement.addEventListener('pointerdown', event => { down = { x: event.clientX, y: event.clientY }; });
renderer.domElement.addEventListener('pointerup', event => {
  if (measuring && down && Math.hypot(event.clientX - down.x, event.clientY - down.y) < TAP_PIXELS) {
    pick(event.clientX, event.clientY);
  }
  down = undefined;
});

measureButton.addEventListener('click', () => {
  measuring = !measuring;
  measureButton.setAttribute('aria-pressed', String(measuring));
  if (measuring) {
    measureResult.hidden = false;
    measureResult.textContent = 'Tap one end of something you have measured, like the desk.';
  } else {
    clearMeasure();
  }
});

scaleForm.addEventListener('submit', event => {
  event.preventDefault();
  const real = Number(realLength.value);
  if (!(real > 0) || picked.length !== 2 || !room) return;
  const scale = room.scale.x * (real / measured());
  try {
    window.localStorage.setItem(scaleKey(), String(scale));
  } catch {
    // The correction then lasts until the page is reloaded.
  }
  applyScale(scale);
  clearMeasure();
  measureResult.hidden = false;
  measureResult.textContent = 'Scale set. Measure another length to check it.';
});

gridButton.addEventListener('click', () => {
  grid.visible = !grid.visible;
  gridButton.setAttribute('aria-pressed', String(grid.visible));
});

// Frame loop -----------------------------------------------------------------------------------

let frames = 0;
let since = performance.now();
renderer.setAnimationLoop(() => {
  if (renderer.xr.isPresenting) {
    xr.updateControllers(camera);
  } else {
    controls.update(rig, camera);
  }
  renderer.render(scene, camera);
  frames += 1;
  const now = performance.now();
  if (now - since >= 1000) {
    element('stat-fps').textContent = `${Math.round((frames * 1000) / (now - since))} fps`;
    frames = 0;
    since = now;
  }
});

loadUrl(source).catch((error: unknown) => {
  status.textContent = error instanceof Error ? error.message : String(error);
});
