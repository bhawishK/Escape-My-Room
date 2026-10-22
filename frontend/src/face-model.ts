/**
 * MediaPipe's face landmarker, loaded once per page and shared by the gaze cursor and eye
 * measurement: one download and one GPU setup, which matters on low-end phones.
 */
import type { FaceLandmarker } from '@mediapipe/tasks-vision';
import wasmLoaderPath from '@mediapipe/tasks-vision/vision_wasm_internal.js?url';
import wasmBinaryPath from '@mediapipe/tasks-vision/vision_wasm_internal.wasm?url';

const FACE_MODEL_URL =
  'https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task';

let model: Promise<FaceLandmarker> | null = null;
let failed = false;

async function createLandmarker(): Promise<FaceLandmarker> {
  const { FaceLandmarker } = await import('@mediapipe/tasks-vision');
  const create = (delegate: 'GPU' | 'CPU') => FaceLandmarker.createFromOptions({ wasmLoaderPath, wasmBinaryPath }, {
    baseOptions: { modelAssetPath: FACE_MODEL_URL, delegate },
    runningMode: 'VIDEO',
    numFaces: 1,
    outputFacialTransformationMatrixes: true,
  });
  return create('GPU').catch(() => create('CPU'));
}

/**
 * The face landmarker for video, on the GPU where it can run, otherwise the CPU; it downloads the
 * first time. A failed load is kept, so one attempt is reported once, until a caller starting
 * something new asks to `retryFailed`.
 */
export function loadFaceModel({ retryFailed = false } = {}): Promise<FaceLandmarker> {
  if (model && failed && retryFailed) model = null;
  if (!model) {
    failed = false;
    model = createLandmarker();
    model.catch(() => { failed = true; });
  }
  return model;
}
