/**
 * Runs the Metric3D depth model off the page's thread and turns each frame into a floor height,
 * so the room view keeps its frame rate even when inference takes seconds.
 */
import type * as Ort from 'onnxruntime-web';
import jsepWasmUrl from 'onnxruntime-web/ort-wasm-simd-threaded.jsep.wasm?url';
import wasmUrl from 'onnxruntime-web/ort-wasm-simd-threaded.wasm?url';
import { floorHeight, frameDepth, fromFloat16, toFloat16, type FloorResult, type Placement, type Size, type Vec3 } from './floor-height';

/** Metric3D v2 ViT-Small, converted to ONNX by onnx-community (CC0-1.0), pinned to one revision. */
const DEPTH_MODEL_URL =
  'https://huggingface.co/onnx-community/metric3d-vit-small/resolve/ee63b95d92d2f629b3e019e88f57eea7c1e97d4b/onnx/model_fp16.onnx';
const MODEL_CACHE = 'depth-model';

/** Which engine to run the model on: the GPU when one works, or the CPU only. */
export type DepthEngine = 'auto' | 'cpu';
/** The engine ONNX Runtime actually ran on: the GPU through WebGPU, or the CPU through WebAssembly. */
export type DepthProvider = 'webgpu' | 'wasm';

export type DepthRequest = { kind: 'load'; engine: DepthEngine } | MeasureRequest;

export interface MeasureRequest {
  kind: 'measure';
  token: number;
  /** The canvas's RGBA pixels: the camera frame placed inside it, the rest mean gray. */
  rgba: Uint8ClampedArray;
  canvas: Size;
  placement: Placement;
  /** The camera frame's focal length in its own pixels. */
  focal: number;
  /** Gravity in the image frame when the frame was taken. */
  down: Vec3;
}

export type DepthReply =
  | { kind: 'progress'; loaded: number; total: number }
  | { kind: 'ready'; provider: DepthProvider; cached: boolean }
  /** `gpu` says whether the GPU was in use, so the page can retry on the CPU. */
  | { kind: 'load-failed'; message: string; gpu: boolean }
  | { kind: 'crashed'; message: string; gpu: boolean }
  | { kind: 'measured'; token: number; result: FloorResult; inferenceMs: number; totalMs: number };

// The project compiles against the DOM library; these are the worker globals this file uses.
const scope = self as unknown as {
  postMessage(message: DepthReply): void;
  onmessage: ((event: MessageEvent<DepthRequest>) => void) | null;
};
const reply = (message: DepthReply) => scope.postMessage(message);

let provider: DepthProvider | null = null;
let loading = true;
const describe = (error: unknown) => (error instanceof Error ? error.message : String(error ?? 'unknown error'));
/** Any failure, including ones thrown from ONNX Runtime's own callbacks, reaches the page. */
function failed(error: unknown): void {
  const gpu = provider === 'webgpu';
  reply(loading ? { kind: 'load-failed', message: describe(error), gpu } : { kind: 'crashed', message: describe(error), gpu });
}
self.addEventListener('error', event => {
  event.preventDefault();
  failed(event.error ?? event.message);
});
self.addEventListener('unhandledrejection', event => {
  event.preventDefault();
  failed(event.reason);
});

/** The model's bytes, from the phone's cache after the first download. */
async function modelBytes(): Promise<{ bytes: Uint8Array; cached: boolean }> {
  const cache = await caches.open(MODEL_CACHE).catch(() => null);
  const hit = await cache?.match(DEPTH_MODEL_URL);
  if (hit) return { bytes: new Uint8Array(await hit.arrayBuffer()), cached: true };
  const response = await fetch(DEPTH_MODEL_URL);
  if (!response.ok || !response.body) throw new Error(`the download failed (HTTP ${response.status})`);
  const total = Number(response.headers.get('content-length')) || 0;
  const reader = response.body.getReader();
  const chunks: Uint8Array[] = [];
  let loaded = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    chunks.push(value);
    loaded += value.length;
    reply({ kind: 'progress', loaded, total });
  }
  const bytes = new Uint8Array(loaded);
  let offset = 0;
  for (const chunk of chunks) {
    bytes.set(chunk, offset);
    offset += chunk.length;
  }
  await cache?.put(DEPTH_MODEL_URL, new Response(bytes)).catch(() => undefined);
  return { bytes, cached: false };
}

/** ONNX Runtime, loaded for the chosen engine. */
let ort: typeof Ort;

async function load(engine: DepthEngine): Promise<Ort.InferenceSession> {
  // The WebGPU build touches WebGPU even when running on the CPU, and crashed that way in Edge,
  // so the CPU engine loads the plain WebAssembly build, which has no WebGPU code at all.
  if (engine === 'cpu') {
    ort = await import('onnxruntime-web/wasm');
    ort.env.wasm.wasmPaths = { wasm: wasmUrl };
  } else {
    ort = await import('onnxruntime-web/webgpu');
    ort.env.wasm.wasmPaths = { wasm: jsepWasmUrl };
  }
  // Threads need a cross-origin isolated page, which this prototype does not set up.
  ort.env.wasm.numThreads = 1;
  const { bytes, cached } = await modelBytes();
  const gpu = (navigator as Navigator & { gpu?: { requestAdapter(): Promise<unknown> } }).gpu;
  const adapter = engine === 'auto' ? await gpu?.requestAdapter().catch(() => null) : null;
  provider = adapter ? 'webgpu' : 'wasm';
  const session = await ort.InferenceSession.create(bytes, { executionProviders: [provider] });
  // A tiny run first: a GPU path that cannot run fails here, before the page relies on it. Its
  // failures can escape ONNX Runtime's promises, which the handlers above catch.
  await session.run({ pixel_values: new ort.Tensor('float16', new Uint16Array(3 * 56 * 56), [1, 3, 56, 56]) });
  loading = false;
  reply({ kind: 'ready', provider, cached });
  return session;
}

/** The canvas as the model's input: float16 pixel values 0 to 255, planes R, G, B. */
function pixelTensor(rgba: Uint8ClampedArray, canvas: Size): Ort.Tensor {
  const plane = canvas.width * canvas.height;
  const values = new Float32Array(plane * 3);
  for (let index = 0; index < plane; index++) {
    values[index] = rgba[index * 4];
    values[plane + index] = rgba[index * 4 + 1];
    values[2 * plane + index] = rgba[index * 4 + 2];
  }
  return new ort.Tensor('float16', toFloat16(values), [1, 3, canvas.height, canvas.width]);
}

/** Float16 output arrives as raw bits, or as numbers where the browser has Float16Array. */
function floats(tensor: Ort.Tensor): Float32Array {
  const data = tensor.data;
  return data instanceof Uint16Array ? fromFloat16(data) : Float32Array.from(data as ArrayLike<number>);
}

let session: Ort.InferenceSession | null = null;

scope.onmessage = async event => {
  const request = event.data;
  if (request.kind === 'load') {
    load(request.engine).then(ready => { session = ready; }, failed);
    return;
  }
  // The page measures only after 'ready', so the session is there.
  if (!session) return;
  const started = performance.now();
  let result: FloorResult;
  let inferenceMs = 0;
  try {
    const outputs = await session.run({ pixel_values: pixelTensor(request.rgba, request.canvas) });
    inferenceMs = performance.now() - started;
    const depth = outputs.predicted_depth;
    const [, height, width] = depth.dims;
    const map = frameDepth(
      { width, height, depth: floats(depth), normals: floats(outputs.predicted_normal) },
      request.canvas, request.placement, request.focal);
    result = floorHeight(map, request.down);
  } catch (error) {
    result = { kind: 'none', reason: `The depth model failed on this frame: ${describe(error)}` };
  }
  reply({ kind: 'measured', token: request.token, result, inferenceMs, totalMs: performance.now() - started });
};
