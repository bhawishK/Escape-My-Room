/**
 * Where the person's face is relative to the phone, from the front camera and MediaPipe's face
 * landmarker, for drawing the room from the eyes later (the stable window, #74). The model's face
 * transform is in centimetres, from the middle of the face, which stands in for the point between
 * the eyes. Its scale assumes MediaPipe's default camera field of view, so it is approximate on
 * phones whose front camera differs.
 */
import type { FaceLandmarker } from '@mediapipe/tasks-vision';
import { loadFaceModel } from './face-model';

/** How long to look for a face once the camera and the model are both ready. */
const LOOK_MS = 1500;
/** How long to wait for the face model, which downloads the first time. */
const MODEL_WAIT_MS = 3000;
/** How often to check for a new camera frame; a timer keeps ticking where animation frames stop. */
const TICK_MS = 30;
/**
 * How far the front camera sits above the middle of the screen, in centimetres. Roughly an
 * iPhone 16's in portrait; other phones differ.
 */
export const FRONT_CAMERA_ABOVE_SCREEN_CENTRE_CM = 7;

export type EyeMeasurement =
  | {
    found: true;
    /** Along the camera's axis, and straight-line, from the front camera in centimetres. */
    depth_cm: number;
    distance_cm: number;
    /**
     * Offsets as the front camera's picture has them, x to its right and y up. Whether the picture
     * is mirrored, so whether +x is the person's left or right, is still to be checked on a phone.
     */
    from_camera_cm: { x: number; y: number };
    from_screen_centre_cm: { x: number; y: number };
    /** Camera frames looked at, each once. */
    frames: number;
  }
  | { found: false; reason: string; frames: number };

const tick = () => new Promise(resolve => setTimeout(resolve, TICK_MS));

/** Waits for the face model, giving up after a while or as soon as `cancelled`. */
async function modelFor(cancelled: () => boolean): Promise<FaceLandmarker | 'still loading' | 'cancelled'> {
  const load: { settled: FaceLandmarker | Error | null } = { settled: null };
  loadFaceModel().then(model => { load.settled = model; }, (error: unknown) => {
    load.settled = error instanceof Error ? error : new Error(String(error));
  });
  const until = performance.now() + MODEL_WAIT_MS;
  while (load.settled === null) {
    if (cancelled()) return 'cancelled';
    if (performance.now() >= until) return 'still loading';
    await tick();
  }
  if (load.settled instanceof Error) throw load.settled;
  return load.settled;
}

/** Measures the eyes from `video`, which must already show the front camera; `cancelled` stops it early. */
export async function measureEyes(video: HTMLVideoElement, cancelled: () => boolean = () => false): Promise<EyeMeasurement> {
  let model: FaceLandmarker;
  try {
    const ready = await modelFor(cancelled);
    if (ready === 'cancelled') return { found: false, reason: 'cancelled', frames: 0 };
    if (ready === 'still loading') return { found: false, reason: 'model still loading', frames: 0 };
    model = ready;
  } catch (error) {
    return { found: false, reason: `model failed to load: ${error instanceof Error ? error.message : String(error)}`, frames: 0 };
  }
  const until = performance.now() + LOOK_MS;
  let frames = 0;
  let lastVideoTime = -1;
  while (performance.now() < until && !cancelled()) {
    await tick();
    // Each camera frame is looked at once, however often the timer ticks.
    if (video.readyState < 2 || video.currentTime === lastVideoTime) continue;
    lastVideoTime = video.currentTime;
    frames++;
    const result = model.detectForVideo(video, performance.now());
    const transform = result.facialTransformationMatrixes?.[0]?.data;
    if (!transform) continue;
    // Column-major 4 × 4: the translation is the face's place, the camera looking down -Z.
    const [x, y, z] = [transform[12], transform[13], transform[14]];
    const round = (value: number) => Math.round(value * 10) / 10 + 0;
    return {
      found: true, depth_cm: round(-z), distance_cm: round(Math.hypot(x, y, z)), frames,
      from_camera_cm: { x: round(x), y: round(y) },
      from_screen_centre_cm: { x: round(x), y: round(y + FRONT_CAMERA_ABOVE_SCREEN_CENTRE_CM) },
    };
  }
  return { found: false, reason: cancelled() ? 'cancelled' : 'no face found', frames };
}
