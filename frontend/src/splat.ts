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
const floorButton = element<HTMLButtonElement>('set-floor');
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

// `?at=x,z&yaw=degrees&pitch=degrees` starts somewhere else, for example where the video was
// filmed (report.json lists those positions). Yaw turns left from facing -z.
const start = new URLSearchParams(window.location.search);
function standAt(x: number, z: number, yaw: number, pitch: number, height = EYE_HEIGHT): void {
  rig.position.set(x, 0, z);
  rig.rotation.set(0, yaw, 0);
  camera.position.set(0, height, 0);
  camera.rotation.set(pitch, 0, 0);
}
if (start.has('at')) {
  const [atX, atZ] = (start.get('at') ?? '').split(',').map(Number);
  standAt(atX || 0, atZ || 0, THREE.MathUtils.degToRad(Number(start.get('yaw')) || 0),
    THREE.MathUtils.degToRad(Number(start.get('pitch')) || 0));
}
scene.add(new SparkRenderer({ renderer }));

// Splats don't hide what is behind them, so a large grid shows through the walls. Keep it room
// sized and faint: it is only there to check that the floor lies at height 0.
const grid = new THREE.GridHelper(4, 8, 0xff9500, 0xaeaeb2);
grid.position.y = 0.002;
for (const material of [grid.material].flat()) {
  material.transparent = true;
  material.opacity = 0.45;
}
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

// Scale and floor ------------------------------------------------------------------------------
// The notebook takes the lowest large flat surface as the floor and scales the room by assuming
// the phone was held 1.4 m above it. If the real floor was barely filmed, a bed or desk top can
// be taken instead. Tapping the real floor and measuring a known length correct both; the
// corrections are remembered per file in this browser. `floor` is in the file's own units.

let source = new URLSearchParams(window.location.search).get('src') ?? '/spike/room.ply';
let room: SplatMesh | undefined;
let correction = { scale: 1, floor: 0 };

function correctionKey(): string {
  return `splat-correction:${source}`;
}

function savedCorrection(): { scale: number; floor: number } {
  try {
    const saved = JSON.parse(window.localStorage.getItem(correctionKey()) ?? '{}') as { scale?: number; floor?: number };
    return { scale: saved.scale && saved.scale > 0 ? saved.scale : 1, floor: saved.floor ?? 0 };
  } catch {
    return { scale: 1, floor: 0 };
  }
}

function applyCorrection(next: { scale: number; floor: number }, remember = true): void {
  correction = next;
  if (room) {
    room.scale.setScalar(next.scale);
    room.position.y = -next.scale * next.floor;
    room.updateMatrixWorld();
  }
  if (remember) {
    try {
      window.localStorage.setItem(correctionKey(), JSON.stringify(next));
    } catch {
      // The correction then lasts until the page is reloaded.
    }
  }
  const scaleText = next.scale === 1
    ? 'Scale assumes the phone was held 1.4 m up; measure a known length to correct it.'
    : `Scale corrected ×${next.scale.toFixed(3)} from a measured length.`;
  const floorText = next.floor === 0
    ? 'Floor as the notebook found it; tap Set floor if the grid is not on the real floor.'
    : 'Floor set by tapping it.';
  scaleNote.textContent = `${scaleText} ${floorText}`;
}

// Viewpoints ----------------------------------------------------------------------------------
// The notebook's report.json lists where each frame was filmed from (and, from later runs, the way
// it faced). Only those places show the room well; elsewhere the splat has gaps and smears.

interface Viewpoint { position: [number, number, number]; forward?: [number, number, number] }
const VIEWPOINT_STRIDE = 10;
let viewpoints: Viewpoint[] = [];
let viewpointIndex = 0;
let roomMiddle = new THREE.Vector3();

/** The median splat position: unlike the bounding box, stray splats far outside don't move it. */
function middleOf(mesh: SplatMesh): THREE.Vector3 {
  const xs: number[] = [];
  const ys: number[] = [];
  const zs: number[] = [];
  mesh.forEachSplat((index, centre) => {
    if (index % 10 === 0) {
      xs.push(centre.x);
      ys.push(centre.y);
      zs.push(centre.z);
    }
  });
  const median = (values: number[]) => values.sort((a, b) => a - b)[Math.floor(values.length / 2)] ?? 0;
  return new THREE.Vector3(median(xs), median(ys), median(zs));
}

function showViewpoint(index: number): void {
  if (!room || viewpoints.length === 0) return;
  viewpointIndex = (index + viewpoints.length) % viewpoints.length;
  const { position, forward } = viewpoints[viewpointIndex];
  const { x, y, z } = room.localToWorld(new THREE.Vector3(...position));
  const facing = forward
    ? new THREE.Vector3(...forward)
    : room.localToWorld(roomMiddle.clone()).sub(new THREE.Vector3(x, y, z));
  facing.normalize();
  const pitch = forward ? Math.asin(THREE.MathUtils.clamp(facing.y, -1, 1)) : THREE.MathUtils.degToRad(-10);
  standAt(x, z, Math.atan2(-facing.x, -facing.z), pitch, y);
  element('viewpoint-label').textContent = `Filmed viewpoint ${viewpointIndex + 1} of ${viewpoints.length}`;
}

async function loadViewpoints(url: string): Promise<void> {
  viewpoints = [];
  element('viewpoints').hidden = true;
  try {
    const response = await fetch(url.replace(/[^/]*$/, 'report.json'));
    if (!response.ok) return;
    const report = await response.json() as { cameras?: Viewpoint[] };
    viewpoints = (report.cameras ?? []).filter((_, i) => i % VIEWPOINT_STRIDE === 0);
  } catch {
    return;
  }
  if (viewpoints.length === 0) return;
  if (room && !viewpoints[0].forward) roomMiddle = middleOf(room);
  element('viewpoints').hidden = false;
  if (!start.has('at')) showViewpoint(Math.floor(viewpoints.length / 2));
}

element<HTMLButtonElement>('next-viewpoint').addEventListener('click', () => { showViewpoint(viewpointIndex + 1); });

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
  applyCorrection(savedCorrection(), false);
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
  await loadViewpoints(url);
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

// Taps either measure (two points) or set the floor (one point).
let tapMode: 'off' | 'measure' | 'floor' = 'off';

function setTapMode(next: 'off' | 'measure' | 'floor'): void {
  tapMode = next;
  measureButton.setAttribute('aria-pressed', String(next === 'measure'));
  floorButton.setAttribute('aria-pressed', String(next === 'floor'));
}
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
    measureResult.textContent = 'Nothing there; tap on the room.';
    return;
  }
  if (tapMode === 'floor') {
    const floor = room.worldToLocal(hit.point.clone()).y;
    applyCorrection({ ...correction, floor });
    setTapMode('off');
    measureResult.hidden = false;
    measureResult.textContent = 'Floor set. The grid should now lie on it.';
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
  if (tapMode !== 'off' && down && Math.hypot(event.clientX - down.x, event.clientY - down.y) < TAP_PIXELS) {
    pick(event.clientX, event.clientY);
  }
  down = undefined;
});

floorButton.addEventListener('click', () => {
  clearMeasure();
  setTapMode(tapMode === 'floor' ? 'off' : 'floor');
  measureResult.hidden = tapMode !== 'floor';
  measureResult.textContent = 'Tap a spot on the real floor.';
});

measureButton.addEventListener('click', () => {
  setTapMode(tapMode === 'measure' ? 'off' : 'measure');
  if (tapMode === 'measure') {
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
  applyCorrection({ ...correction, scale: correction.scale * (real / measured()) });
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
