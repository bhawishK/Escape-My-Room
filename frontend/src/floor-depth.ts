/**
 * Measures the phone's height above the floor from its back camera with an AI depth model, once
 * per request: it reads until three readings agree, then releases the camera, so the model stops
 * using the CPU and the room view's height holds still. Camera frames stay on the phone; only the
 * depth model is downloaded, once, and it stays loaded for the next measurement.
 */
import { cameraError } from './camera';
import { gravityInCamera, modelCanvas, placeFrame, settledHeight, type FloorResult } from './floor-height';
import type { DepthEngine, DepthProvider, DepthReply, DepthRequest } from './depth.worker';
import type { Rotation } from './protocol';

/**
 * The iPhone 16 main camera's lens spans about 67° across the sensor's long side, so its focal
 * length is about 0.75 x the frame's long side in pixels. Every height scales with this value.
 */
const FOCAL_PER_LONG_SIDE = 0.75;
/** The padding around the frame is Metric3D's mean color, so the model reads it as neutral. */
const PADDING = 'rgb(124, 116, 104)';

export type DepthPhase = 'off' | 'starting' | 'measuring';

export interface DepthReport {
  phase: DepthPhase;
  provider: DepthProvider | null;
  /** From starting to the model being ready: the download the first time, then loading from the cache. */
  model_load_s: number | null;
  model_cached: boolean | null;
  /** The last measurement's readings, and the height it settled on. */
  readings_m: number[];
  height_m: number | null;
  last_reason: string | null;
  inference_ms: number;
  seconds_per_reading: number;
}

interface DepthEvents {
  status: (message: string) => void;
  phase: (phase: DepthPhase) => void;
  /** A measurement settled on this height. */
  height: (meters: number) => void;
}

export class FloorDepth {
  private phase: DepthPhase = 'off';
  private token = 0;
  private stream: MediaStream | null = null;
  private worker: Worker | null = null;
  private ready: Promise<Worker> | null = null;
  /** Once the GPU has failed to run the model, later workers use the CPU only. */
  private engine: DepthEngine = 'auto';
  private readonly canvas = document.createElement('canvas');
  private readings: number[] = [];
  /** Frames tried in this measurement, whether or not they found the floor. */
  private attempts = 0;
  private height: number | null = null;
  private provider: DepthProvider | null = null;
  private loadStartedAt = 0;
  private modelLoadMs: number | null = null;
  private cached: boolean | null = null;
  private lastReason: string | null = null;
  private inferenceMs = 0;
  private readingMs = 0;
  private sentAt = 0;

  /**
   * `video` shows the back camera small, so the person can aim it at the floor. `orientation`
   * gives the camera's current room orientation from the turn sensor, or null without a reading.
   */
  constructor(
    private readonly video: HTMLVideoElement,
    private readonly orientation: () => Rotation | null,
    private readonly events: DepthEvents,
  ) {
    document.addEventListener('visibilitychange', () => {
      if (document.visibilityState === 'hidden' && this.phase !== 'off') {
        this.stop('Height measurement stopped while the page was hidden.');
      }
    });
  }

  getPhase(): DepthPhase { return this.phase; }

  report(): DepthReport {
    return {
      phase: this.phase, provider: this.provider, model_cached: this.cached,
      model_load_s: this.modelLoadMs === null ? null : Math.round(this.modelLoadMs) / 1000,
      readings_m: this.readings.map(value => Math.round(value * 1000) / 1000),
      height_m: this.height,
      last_reason: this.lastReason, inference_ms: Math.round(this.inferenceMs),
      seconds_per_reading: Math.round(this.readingMs) / 1000,
    };
  }

  /** Measures the height once: starts the back camera and the depth model. Call from a button press. */
  async start(): Promise<void> {
    this.stop();
    const token = this.token;
    this.setPhase('starting');
    this.events.status('Starting the back camera…');
    try {
      if (!navigator.mediaDevices?.getUserMedia) throw new Error('Camera access needs the trusted HTTPS link.');
      // Ask for the camera first, while the button press still counts as the user's gesture.
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: false, video: { facingMode: { ideal: 'environment' }, width: { ideal: 1280 }, height: { ideal: 720 } },
      }).catch((error: unknown) => { throw new Error(cameraError(error, 'back')); });
      if (token !== this.token) {
        for (const track of stream.getTracks()) track.stop();
        return;
      }
      this.stream = stream;
      this.video.srcObject = stream;
      this.video.hidden = false;
      this.events.status('Loading the depth model…');
      this.loadStartedAt = performance.now();
      const [, worker] = await Promise.all([this.video.play(), this.ensureWorker(token)]);
      if (token !== this.token) return;
      this.readings = [];
      this.attempts = 0;
      this.setPhase('measuring');
      this.events.status(`Measuring height (${this.provider === 'webgpu' ? 'GPU' : 'CPU'}) · hold still with the floor in view`);
      this.measure(worker, token);
    } catch (error) {
      if (token === this.token) this.stop(error instanceof Error ? error.message : 'The height could not be measured.');
      throw error;
    }
  }

  /** Releases the back camera. The model stays loaded, and any measured height stays. */
  stop(message = 'Height measurement cancelled'): void {
    this.token++;
    for (const track of this.stream?.getTracks() ?? []) track.stop();
    this.stream = null;
    this.video.srcObject = null;
    this.video.hidden = true;
    if (this.phase !== 'off') {
      this.setPhase('off');
      this.events.status(message);
    }
  }

  private setPhase(phase: DepthPhase): void {
    this.phase = phase;
    this.events.phase(phase);
  }

  private ensureWorker(token: number): Promise<Worker> {
    this.ready ??= this.spawn(token).catch((error: unknown) => {
      this.ready = null;
      throw error;
    });
    return this.ready;
  }

  /** Starts a worker on the current engine; a GPU that cannot run the model falls back to the CPU. */
  private spawn(token: number): Promise<Worker> {
    return new Promise<Worker>((resolve, reject) => {
      const worker = new Worker(new URL('./depth.worker.ts', import.meta.url), { type: 'module' });
      worker.onmessage = (event: MessageEvent<DepthReply>) => {
        const message = event.data;
        if (message.kind === 'progress' && token === this.token) {
          const share = message.total ? ` · ${Math.round(100 * message.loaded / message.total)} %` : '';
          this.events.status(`Downloading the depth model (${Math.round(message.loaded / 1e6)} MB)${share}…`);
        } else if (message.kind === 'ready') {
          this.provider = message.provider;
          this.modelLoadMs = performance.now() - this.loadStartedAt;
          this.cached = message.cached;
          worker.onmessage = reply => this.receive(reply.data as DepthReply);
          this.worker = worker;
          resolve(worker);
        } else if (message.kind === 'load-failed') {
          worker.terminate();
          if (message.gpu && this.engine === 'auto') {
            this.engine = 'cpu';
            if (token === this.token) this.events.status('The GPU could not run the depth model; switching to the CPU…');
            resolve(this.spawn(token));
            return;
          }
          reject(new Error(`The depth model could not load: ${message.message}. Check the internet connection, then try again.`));
        }
      };
      worker.onerror = () => {
        worker.terminate();
        reject(new Error('The depth model could not load. Reload the page and try again.'));
      };
      worker.postMessage({ kind: 'load', engine: this.engine } satisfies DepthRequest);
    });
  }

  /** Sends the current camera frame to the model; the next one goes when this one's answer comes. */
  private measure(worker: Worker, token: number): void {
    if (token !== this.token) return;
    const width = this.video.videoWidth;
    const height = this.video.videoHeight;
    const facing = this.orientation();
    if (!width || !height || !facing) {
      this.events.status(facing ? 'Waiting for the camera…' : 'Waiting for the motion sensor…');
      setTimeout(() => this.measure(worker, token), 200);
      return;
    }
    const frame = { width, height };
    const canvas = modelCanvas(frame);
    const placement = placeFrame(frame, canvas);
    this.canvas.width = canvas.width;
    this.canvas.height = canvas.height;
    const context = this.canvas.getContext('2d', { willReadFrequently: true })!;
    context.fillStyle = PADDING;
    context.fillRect(0, 0, canvas.width, canvas.height);
    context.drawImage(this.video, placement.left, placement.top, placement.width, placement.height);
    const rgba = context.getImageData(0, 0, canvas.width, canvas.height).data;
    const request: DepthRequest = {
      kind: 'measure', token, rgba, canvas, placement,
      focal: FOCAL_PER_LONG_SIDE * Math.max(width, height), down: gravityInCamera(facing),
    };
    this.sentAt = performance.now();
    worker.postMessage(request, [rgba.buffer]);
  }

  private receive(reply: DepthReply): void {
    if (reply.kind === 'crashed') {
      this.worker?.terminate();
      this.worker = null;
      this.ready = null;
      const token = this.token;
      if (reply.gpu && this.engine === 'auto' && this.phase === 'measuring') {
        // The GPU failed part way: carry on with a fresh worker on the CPU.
        this.engine = 'cpu';
        this.events.status('The GPU stopped running the depth model; switching to the CPU…');
        this.ensureWorker(token).then(worker => this.measure(worker, token)).catch((error: unknown) => {
          if (token === this.token) this.stop(error instanceof Error ? error.message : 'The height could not be measured.');
        });
        return;
      }
      this.stop(`The depth model stopped working: ${reply.message}`);
      return;
    }
    if (reply.kind !== 'measured' || reply.token !== this.token || !this.worker) return;
    this.readingMs = performance.now() - this.sentAt;
    this.inferenceMs = reply.inferenceMs;
    this.settle(reply.result, this.worker, reply.token);
  }

  /** Adds a reading, and either settles on a height and stops, gives up, or reads another frame. */
  private settle(result: FloorResult, worker: Worker, token: number): void {
    this.attempts++;
    this.lastReason = result.kind === 'none' ? result.reason : null;
    if (result.kind === 'measured') this.readings = [...this.readings, result.height];
    const outcome = settledHeight(this.readings, this.attempts);
    const pace = `${(this.readingMs / 1000).toFixed(1)} s per reading, ${(this.inferenceMs / 1000).toFixed(1)} s inference`;
    if (outcome.kind === 'settled') {
      this.height = outcome.height;
      this.events.height(outcome.height);
      this.stop(`Height ${outcome.height.toFixed(2)} m from ${this.readings.length} readings · ${pace}`);
    } else if (outcome.kind === 'failed') {
      this.stop(outcome.reason);
    } else {
      const latest = result.kind === 'measured' ? `${result.height.toFixed(2)} m` : result.reason;
      const count = `${this.readings.length} ${this.readings.length === 1 ? 'reading' : 'readings'}`;
      this.events.status(`Measuring height · ${count} so far · last ${latest} · ${pace}`);
      this.measure(worker, token);
    }
  }
}
