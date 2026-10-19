/**
 * A head- or eye-steered cursor over the phone's room view, from the front camera and MediaPipe's
 * face landmarker. One calibration fits both cursors, so they can be compared on the same phone.
 * Camera frames stay on the phone; only the face model is downloaded.
 */
import type { FaceLandmarker } from '@mediapipe/tasks-vision';
import wasmLoaderPath from '@mediapipe/tasks-vision/vision_wasm_internal.js?url';
import wasmBinaryPath from '@mediapipe/tasks-vision/vision_wasm_internal.wasm?url';
import {
  CALIBRATION_POINTS, TEST_POINTS, faceFeatures, fitMapping, meanFeatures, predict,
  type CalibrationSample, type CursorMode, type FaceFeatures, type Mapping, type ScreenPoint,
} from './gaze';

const FACE_MODEL_URL =
  'https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task';
/** A tap uses the frames from just before it, while the person was looking at the dot. */
const TAP_WINDOW_MS = 400;
const MIN_TAP_FRAMES = 3;
/** How far each frame moves the cursor toward its new point; lower is steadier but slower. */
const SMOOTHING = 0.25;

export type GazePhase = 'off' | 'starting' | 'calibrating' | 'tracking' | 'testing';

export interface GazeAccuracy {
  /** Mean distance from each test dot, in CSS pixels, for each cursor. */
  head_px: number;
  eyes_px: number;
  screen: { width: number; height: number };
}

export interface GazeReport {
  phase: GazePhase;
  mode: CursorMode;
  calibration_points: number;
  accuracy: GazeAccuracy | null;
  frames_per_second: number;
  detect_ms: number;
  face_found: boolean;
}

interface GazeEvents {
  status: (message: string) => void;
  phase: (phase: GazePhase) => void;
  /** Highlights whatever is at a screen point, or nothing with null, and returns its name. */
  hover: (point: ScreenPoint | null) => string | null;
}

export interface GazeElements {
  /** Shows the front camera, small, so the person can see their face is in view. */
  video: HTMLVideoElement;
  cursor: HTMLElement;
  /** Covers the screen during calibration and testing, and takes the taps. */
  layer: HTMLElement;
  dot: HTMLElement;
  prompt: HTMLElement;
}

function cameraError(error: unknown): string {
  if (error instanceof DOMException) {
    if (error.name === 'NotAllowedError' || error.name === 'SecurityError') {
      return 'Camera permission was denied. Allow camera access for this site in the browser settings, then try again.';
    }
    if (error.name === 'NotFoundError' || error.name === 'OverconstrainedError') return 'No front camera was found on this device.';
    if (error.name === 'NotReadableError' || error.name === 'AbortError') {
      return 'The camera is in use by another app. Close it and try again.';
    }
  }
  return error instanceof Error ? error.message : 'The camera could not start.';
}

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

export class GazeCursor {
  private phase: GazePhase = 'off';
  private mode: CursorMode = 'eyes';
  private token = 0;
  private stream: MediaStream | null = null;
  private landmarker: Promise<FaceLandmarker> | null = null;
  private frameRequest: number | null = null;
  private lastVideoTime = -1;
  private recent: { time: number; features: FaceFeatures }[] = [];
  private samples: CalibrationSample[] = [];
  private mappings: Record<CursorMode, Mapping> | null = null;
  private target = 0;
  private errors: Record<CursorMode, number[]> = { head: [], eyes: [] };
  private accuracy: GazeAccuracy | null = null;
  private smoothed: ScreenPoint | null = null;
  private hovered: string | null = null;
  private faceFound = false;
  private detectMs = 0;
  private readonly frameTimes: number[] = [];

  constructor(private readonly elements: GazeElements, private readonly events: GazeEvents) {
    elements.layer.addEventListener('pointerdown', event => {
      if ((event.target as HTMLElement).closest('button')) return;
      event.preventDefault();
      this.tap();
    });
    document.addEventListener('visibilitychange', () => {
      if (document.visibilityState === 'hidden' && this.phase !== 'off') {
        this.stop('Gaze cursor stopped while the page was hidden.');
      }
    });
  }

  getPhase(): GazePhase { return this.phase; }
  getMode(): CursorMode { return this.mode; }
  isCalibrated(): boolean { return this.mappings !== null; }

  report(): GazeReport {
    const span = this.frameTimes.length > 1 ? (this.frameTimes.at(-1)! - this.frameTimes[0]) / 1000 : 0;
    return {
      phase: this.phase, mode: this.mode, calibration_points: this.samples.length,
      accuracy: this.accuracy, frames_per_second: span > 0 ? (this.frameTimes.length - 1) / span : 0,
      detect_ms: this.detectMs, face_found: this.faceFound,
    };
  }

  setMode(mode: CursorMode): void {
    this.mode = mode;
    this.smoothed = null;
    if (this.phase === 'tracking') this.events.status(`Gaze cursor · ${mode === 'eyes' ? 'eyes' : 'head'}`);
  }

  /** Starts the front camera and face tracking, then calibrates. Call from a button press. */
  async start(): Promise<void> {
    this.stop();
    const token = this.token;
    this.setPhase('starting');
    this.events.status('Starting the front camera…');
    try {
      if (!navigator.mediaDevices?.getUserMedia) throw new Error('Camera access needs the trusted HTTPS link.');
      // Ask for the camera first, while the button press still counts as the user's gesture.
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: false, video: { facingMode: 'user', width: { ideal: 640 }, height: { ideal: 480 } },
      }).catch((error: unknown) => { throw new Error(cameraError(error)); });
      if (token !== this.token) {
        for (const track of stream.getTracks()) track.stop();
        return;
      }
      this.stream = stream;
      this.elements.video.srcObject = stream;
      this.elements.video.hidden = false;
      this.events.status('Loading face tracking…');
      this.landmarker ??= createLandmarker().catch((error: unknown) => {
        this.landmarker = null;
        throw new Error(`Face tracking could not load. Check the internet connection, then try again. (${
          error instanceof Error ? error.message : 'unknown error'})`);
      });
      await Promise.all([this.elements.video.play(), this.landmarker]);
      if (token !== this.token) return;
      this.loop(token);
      this.calibrate();
    } catch (error) {
      if (token === this.token) this.stop(error instanceof Error ? error.message : 'The gaze cursor could not start.');
      throw error;
    }
  }

  /** Shows the calibration dots again; the cursor is refitted from the new taps. */
  calibrate(): void {
    if (!this.stream) return;
    this.samples = [];
    this.target = 0;
    this.setPhase('calibrating');
    this.showTarget(CALIBRATION_POINTS[0], `Look at the dot and tap it · 1 of ${CALIBRATION_POINTS.length}`);
  }

  /** Measures both cursors against dots that were not used for calibration. */
  test(): void {
    if (!this.mappings) return;
    this.errors = { head: [], eyes: [] };
    this.target = 0;
    this.setPhase('testing');
    this.showTarget(TEST_POINTS[0], `Accuracy test: look at the dot and tap it · 1 of ${TEST_POINTS.length}`);
  }

  cancel(): void {
    if (this.phase !== 'calibrating' && this.phase !== 'testing') return;
    this.elements.layer.hidden = true;
    if (this.mappings) {
      this.setPhase('tracking');
      this.events.status(`Gaze cursor · ${this.mode}`);
    } else {
      this.stop('Gaze cursor off');
    }
  }

  /** Releases the front camera and hides the cursor. Calibration is kept for the session. */
  stop(message = 'Gaze cursor off'): void {
    this.token++;
    if (this.frameRequest !== null) cancelAnimationFrame(this.frameRequest);
    this.frameRequest = null;
    for (const track of this.stream?.getTracks() ?? []) track.stop();
    this.stream = null;
    this.elements.video.srcObject = null;
    this.elements.video.hidden = true;
    this.elements.cursor.hidden = true;
    this.elements.layer.hidden = true;
    this.recent = [];
    this.smoothed = null;
    this.lastVideoTime = -1;
    this.hover(null);
    if (this.phase !== 'off') {
      this.setPhase('off');
      this.events.status(message);
    }
  }

  private setPhase(phase: GazePhase): void {
    this.phase = phase;
    this.events.phase(phase);
  }

  private showTarget(point: ScreenPoint, prompt: string): void {
    this.elements.layer.hidden = false;
    this.elements.cursor.hidden = true;
    this.elements.dot.style.left = `${point.x * 100}%`;
    this.elements.dot.style.top = `${point.y * 100}%`;
    this.elements.prompt.textContent = prompt;
  }

  private loop(token: number): void {
    this.frameRequest = requestAnimationFrame(() => {
      if (token !== this.token) return;
      this.loop(token);
      void this.landmarker?.then(landmarker => {
        if (token === this.token) this.frame(landmarker);
      });
    });
  }

  private frame(landmarker: FaceLandmarker): void {
    const video = this.elements.video;
    if (video.readyState < HTMLMediaElement.HAVE_CURRENT_DATA || video.currentTime === this.lastVideoTime) return;
    this.lastVideoTime = video.currentTime;
    const started = performance.now();
    const result = landmarker.detectForVideo(video, started);
    const now = performance.now();
    this.detectMs = now - started;
    this.frameTimes.push(now);
    while (this.frameTimes.length > 1 && now - this.frameTimes[0] > 2000) this.frameTimes.shift();
    const landmarks = result.faceLandmarks[0];
    const transform = result.facialTransformationMatrixes?.[0]?.data;
    const features = landmarks && transform ?
      faceFeatures(landmarks, transform, video.videoWidth / Math.max(video.videoHeight, 1)) : null;
    this.faceFound = features !== null;
    while (this.recent.length > 0 && now - this.recent[0].time > 1000) this.recent.shift();
    if (features) this.recent.push({ time: now, features });
    if (this.phase !== 'tracking' || !this.mappings) return;
    if (!features) {
      this.elements.cursor.hidden = true;
      this.hover(null);
      return;
    }
    const point = predict(this.mappings[this.mode], features);
    const clamped = { x: Math.min(1, Math.max(0, point.x)), y: Math.min(1, Math.max(0, point.y)) };
    this.smoothed = this.smoothed ? {
      x: this.smoothed.x + SMOOTHING * (clamped.x - this.smoothed.x),
      y: this.smoothed.y + SMOOTHING * (clamped.y - this.smoothed.y),
    } : clamped;
    this.elements.cursor.hidden = false;
    this.elements.cursor.style.left = `${this.smoothed.x * 100}%`;
    this.elements.cursor.style.top = `${this.smoothed.y * 100}%`;
    this.hover(this.smoothed);
  }

  private hover(point: ScreenPoint | null): void {
    const name = this.events.hover(point);
    this.elements.cursor.dataset.over = String(name !== null);
    if (name === this.hovered) return;
    this.hovered = name;
    if (this.phase === 'tracking') this.events.status(name ? `Looking at ${name}` : `Gaze cursor · ${this.mode}`);
  }

  /** The person tapped while looking at the dot: record what the face showed just before. */
  private tap(): void {
    const now = performance.now();
    const frames = this.recent.filter(frame => now - frame.time <= TAP_WINDOW_MS);
    const features = meanFeatures(frames.map(frame => frame.features));
    if (!features || frames.length < MIN_TAP_FRAMES) {
      this.elements.prompt.textContent = 'Your face is not in view. Hold the phone so the front camera sees you, then tap again.';
      return;
    }
    if (this.phase === 'calibrating') {
      this.samples.push({ features, target: CALIBRATION_POINTS[this.target] });
      this.target++;
      if (this.target < CALIBRATION_POINTS.length) {
        this.showTarget(CALIBRATION_POINTS[this.target],
          `Look at the dot and tap it · ${this.target + 1} of ${CALIBRATION_POINTS.length}`);
        return;
      }
      this.mappings = { head: fitMapping(this.samples, 'head'), eyes: fitMapping(this.samples, 'eyes') };
      this.accuracy = null;
      this.elements.layer.hidden = true;
      this.smoothed = null;
      this.setPhase('tracking');
      this.events.status(`Calibrated · gaze cursor · ${this.mode}`);
    } else if (this.phase === 'testing' && this.mappings) {
      const goal = TEST_POINTS[this.target];
      const { innerWidth: width, innerHeight: height } = window;
      for (const mode of ['head', 'eyes'] as const) {
        const point = predict(this.mappings[mode], features);
        this.errors[mode].push(Math.hypot((point.x - goal.x) * width, (point.y - goal.y) * height));
      }
      this.target++;
      if (this.target < TEST_POINTS.length) {
        this.showTarget(TEST_POINTS[this.target],
          `Accuracy test: look at the dot and tap it · ${this.target + 1} of ${TEST_POINTS.length}`);
        return;
      }
      const mean = (values: number[]) => values.reduce((sum, value) => sum + value, 0) / values.length;
      this.accuracy = {
        head_px: Math.round(mean(this.errors.head)), eyes_px: Math.round(mean(this.errors.eyes)),
        screen: { width, height },
      };
      this.elements.layer.hidden = true;
      this.setPhase('tracking');
      this.events.status(`Mean error · eyes ${this.accuracy.eyes_px} px · head ${this.accuracy.head_px} px `
        + `(screen ${width} × ${height})`);
    }
  }
}
