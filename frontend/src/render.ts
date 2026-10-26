// Render-and-ask (#98): draw views of a prepared room's splat for Python, which asks Qwen about
// them. A headless browser opens this page (`scripts/render-views.mjs`) and calls `renderViews`.
// It uses Spark, the renderer the devices use, so Qwen sees the room as the players do.
import * as THREE from 'three';
import { SparkRenderer, SplatMesh } from '@sparkjsdev/spark';

type Vector = [number, number, number];

export interface ViewRequest {
  position: Vector;
  look_at: Vector;
  fov_degrees: number;
  width: number;
  height: number;
}

export interface RenderRequest {
  splat_url: string;
  placement: {
    position: { x: number; y: number; z: number };
    rotation: { x: number; y: number; z: number; w: number };
    scale: number;
  };
  views: ViewRequest[];
}

export interface RenderedView {
  png: string;
  seconds: number;
}

// Splats are sorted by distance in a worker after the camera moves; a view is captured only once
// the sort has caught up for a few frames running, or after this long.
const SETTLED_FRAMES = 3;
const MAX_SETTLE_MS = 20_000;

const renderer = new THREE.WebGLRenderer({ antialias: false, preserveDrawingBuffer: true });
renderer.setPixelRatio(1);
document.body.append(renderer.domElement);
const scene = new THREE.Scene();
scene.background = new THREE.Color(0x1d1d1f);
const spark = new SparkRenderer({ renderer });
scene.add(spark);
const camera = new THREE.PerspectiveCamera(60, 4 / 3, 0.05, 200);

async function loadSplat(request: RenderRequest): Promise<SplatMesh> {
  const response = await fetch(request.splat_url);
  if (!response.ok) throw new Error(`The splat ${request.splat_url} could not be loaded.`);
  const mesh = new SplatMesh({
    fileBytes: await response.arrayBuffer(),
    fileName: request.splat_url.split('/').pop(),
    raycastable: false,
  });
  await mesh.initialized;
  const { position, rotation, scale } = request.placement;
  mesh.position.set(position.x, position.y, position.z);
  mesh.quaternion.set(rotation.x, rotation.y, rotation.z, rotation.w);
  mesh.scale.setScalar(scale);
  return mesh;
}

function nextFrame(): Promise<void> {
  return new Promise(resolve => requestAnimationFrame(() => resolve()));
}

async function draw(view: ViewRequest): Promise<string> {
  renderer.setSize(view.width, view.height, false);
  camera.aspect = view.width / view.height;
  camera.fov = view.fov_degrees;
  camera.position.set(...view.position);
  const direction = new THREE.Vector3(...view.look_at).sub(camera.position).normalize();
  // Looking straight up or down, "up" on screen is the room's -z, so lookAt stays defined.
  camera.up.set(0, 1, 0);
  if (Math.abs(direction.y) > 0.999) camera.up.set(0, 0, -1);
  camera.lookAt(...view.look_at);
  camera.updateProjectionMatrix();
  const started = performance.now();
  let settled = 0;
  while (settled < SETTLED_FRAMES && performance.now() - started < MAX_SETTLE_MS) {
    renderer.render(scene, camera);
    await nextFrame();
    settled = spark.sorting || spark.sortDirty ? 0 : settled + 1;
  }
  renderer.render(scene, camera);
  return renderer.domElement.toDataURL('image/png');
}

async function renderViews(request: RenderRequest): Promise<RenderedView[]> {
  const mesh = await loadSplat(request);
  scene.add(mesh);
  try {
    const views: RenderedView[] = [];
    for (const view of request.views) {
      const started = performance.now();
      const png = await draw(view);
      views.push({ png, seconds: (performance.now() - started) / 1000 });
    }
    return views;
  } finally {
    scene.remove(mesh);
    mesh.dispose();
  }
}

declare global {
  interface Window {
    renderViews: typeof renderViews;
  }
}
window.renderViews = renderViews;
