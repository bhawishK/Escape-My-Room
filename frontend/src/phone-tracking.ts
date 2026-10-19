import { errorMessage } from './api';
import { processingSize, resizeIntrinsics, type RoomPose } from './marker-geometry';
import type { CameraCalibration, CameraIntrinsics, PoseInput, TrackingMarker } from './protocol';
import type { WorkerReply, WorkerRequest } from './tracking.worker';
import type { Frame } from './vision';

/** Frames are processed with their long side at most this many pixels. */
export const PROCESSING_LONG_SIDE = 960;
/** Poses are published at most every 50 ms, 20 per second, as the WebXR path did. */
const PUBLISH_INTERVAL_MS = 50;
/** With no usable marker view for this long, the phone reports tracking lost. */
export const LOST_AFTER_MS = 300;
/** Calibration keeps one board view at most this often, so the views differ. */
const BOARD_INTERVAL_MS = 700;
export const CALIBRATION_VIEWS = 15;

export type TrackerMode = 'off' | 'starting' | 'tracking' | 'calibrating';

export interface TrackerStatus {
  mode: TrackerMode;
  /** While tracking: whether the last frames gave a usable room position. */
  tracked: boolean;
  message: string;
}

export interface TrackingReport {
  video: { width: number; height: number } | null;
  processing: { width: number; height: number } | null;
  calibration: Pick<CameraCalibration, 'width' | 'height' | 'fx' | 'fy' | 'cx' | 'cy' | 'rms_px' | 'recorded_at'> | null;
  frames_per_second: number;
  detect_ms: number;
  poses_published: number;
  markers_seen: number[];
  last_reason: string | null;
}

interface TrackerEvents {
  publish: (pose: PoseInput) => void;
  status: (status: TrackerStatus) => void;
  /** The phone's own latest measured pose, for its view; null when tracking stops. */
  view: (pose: RoomPose | null) => void;
}

export function cameraError(error: unknown): string {
  if (error instanceof DOMException) {
    if (error.name === 'NotAllowedError' || error.name === 'SecurityError') {
      return 'Camera permission was denied. Allow camera access for this site in the browser settings, then try again.';
    }
    if (error.name === 'NotFoundError' || error.name === 'OverconstrainedError') {
      return 'No back camera was found on this device.';
    }
    if (error.name === 'NotReadableError' || error.name === 'AbortError') {
      return 'The camera is in use by another app. Close it and try again.';
    }
  }
  return error instanceof Error ? error.message : 'The camera could not start.';
}

/**
 * Measures the phone's room position with its back camera and the room's printed AprilTags.
 * Only one frame is processed at a time, so results never queue up behind the camera; results
 * from before a stop carry an old token and are dropped.
 */
export class PhoneTracker {
  private worker: Worker | null = null;
  private workerReady: Promise<Worker> | null = null;
  private stream: MediaStream | null = null;
  private token = 0;
  private mode: TrackerMode = 'off';
  private busy = false;
  private frameRequest: number | null = null;
  private readonly canvas = document.createElement('canvas');
  private markers: TrackingMarker[] = [];
  private calibrations: CameraCalibration[] = [];
  private calibration: CameraCalibration | null = null;
  private trackedAt = -Infinity;
  private startedAt = 0;
  private publishedAt = -Infinity;
  private reportedLost = false;
  private lastBoardAt = -Infinity;
  private solving = false;
  private readonly frameTimes: number[] = [];
  private readonly stats: TrackingReport = {
    video: null, processing: null, calibration: null, frames_per_second: 0, detect_ms: 0,
    poses_published: 0, markers_seen: [], last_reason: null,
  };

  constructor(private readonly preview: HTMLVideoElement, private readonly events: TrackerEvents) {
    document.addEventListener('visibilitychange', () => {
      if (document.visibilityState === 'hidden' && this.mode !== 'off') {
        this.stop('Tracking stopped while the page was hidden. Start it again when you are back.');
      }
    });
    window.addEventListener('pagehide', () => this.stop());
  }

  setMarkers(markers: TrackingMarker[]): void {
    this.markers = markers;
  }

  getMode(): TrackerMode { return this.mode; }

  report(): TrackingReport { return structuredClone(this.stats); }

  async startTracking(): Promise<void> {
    if (this.markers.length === 0) {
      throw new Error('This room has no tracking markers, so the phone cannot be placed in it.');
    }
    await this.open('tracking', async () => {
      const response = await fetch('/api/tracking/cameras');
      if (!response.ok) throw new Error(await errorMessage(response, 'Camera calibrations could not be loaded'));
      this.calibrations = (await response.json() as { calibrations: CameraCalibration[] }).calibrations;
    });
  }

  async startCalibration(): Promise<void> {
    await this.open('calibrating', async () => undefined);
  }

  /** Releases the camera. A tracking phone tells Python its position is no longer available. */
  stop(message = 'Tracking off'): void {
    const wasTracking = this.mode === 'tracking';
    this.token++;
    this.mode = 'off';
    this.busy = false;
    this.solving = false;
    if (this.frameRequest !== null) cancelAnimationFrame(this.frameRequest);
    this.frameRequest = null;
    for (const track of this.stream?.getTracks() ?? []) track.stop();
    this.stream = null;
    this.preview.srcObject = null;
    this.preview.hidden = true;
    if (wasTracking) this.events.publish({ tracking_status: 'inactive', reference_space: null, position: null });
    this.events.view(null);
    this.events.status({ mode: 'off', tracked: false, message });
  }

  private async open(mode: 'tracking' | 'calibrating', prepare: () => Promise<void>): Promise<void> {
    this.stop();
    const token = this.token;
    this.mode = 'starting';
    this.events.status({ mode: 'starting', tracked: false, message: 'Starting the camera…' });
    try {
      if (!navigator.mediaDevices?.getUserMedia) {
        throw new Error('Camera access needs the trusted HTTPS link.');
      }
      // Ask for the camera first, while the button press still counts as the user's gesture.
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: false,
        video: { facingMode: { ideal: 'environment' }, width: { ideal: 1280 }, height: { ideal: 720 } },
      }).catch((error: unknown) => { throw new Error(cameraError(error)); });
      if (token !== this.token) {
        for (const track of stream.getTracks()) track.stop();
        return;
      }
      this.stream = stream;
      for (const track of stream.getVideoTracks()) {
        track.addEventListener('ended', () => {
          if (token === this.token) this.stop('The camera stopped. Start tracking again.');
        });
      }
      this.preview.srcObject = stream;
      this.preview.hidden = false;
      await Promise.all([this.preview.play(), this.ensureWorker(), prepare()]);
      if (token !== this.token) return;
      this.mode = mode;
      this.startedAt = performance.now();
      this.trackedAt = -Infinity;
      this.publishedAt = -Infinity;
      this.reportedLost = false;
      this.lastBoardAt = -Infinity;
      this.stats.poses_published = 0;
      this.frameTimes.length = 0;
      if (mode === 'calibrating') this.post({ kind: 'reset-board' });
      this.events.status(mode === 'tracking' ?
        { mode, tracked: false, message: 'Looking for a room marker…' } :
        { mode, tracked: false, message: `Calibrating · 0 of ${CALIBRATION_VIEWS} board views` });
      this.schedule(token);
    } catch (error) {
      if (token === this.token) this.stop(error instanceof Error ? error.message : 'The camera could not start.');
      throw error;
    }
  }

  private ensureWorker(): Promise<Worker> {
    this.workerReady ??= new Promise<Worker>((resolve, reject) => {
      const worker = new Worker(new URL('./tracking.worker.ts', import.meta.url), { type: 'module' });
      const settle = (event: MessageEvent<WorkerReply>) => {
        if (event.data.kind === 'ready') {
          worker.onmessage = reply => this.receive(reply.data as WorkerReply);
          this.worker = worker;
          resolve(worker);
        } else if (event.data.kind === 'load-failed') {
          reject(new Error(`The marker tracker could not load: ${event.data.message}`));
        }
      };
      worker.onmessage = settle;
      worker.onerror = () => reject(new Error('The marker tracker could not load. Reload the page and try again.'));
    }).catch((error: unknown) => {
      this.workerReady = null;
      throw error;
    });
    return this.workerReady;
  }

  private post(request: WorkerRequest, transfer: Transferable[] = []): void {
    this.worker?.postMessage(request, transfer);
  }

  private schedule(token: number): void {
    this.frameRequest = requestAnimationFrame(() => this.sample(token));
  }

  private sample(token: number): void {
    if (token !== this.token) return;
    this.schedule(token);
    if (this.busy || this.preview.readyState < HTMLMediaElement.HAVE_CURRENT_DATA) return;
    const now = performance.now();
    const width = this.preview.videoWidth;
    const height = this.preview.videoHeight;
    if (!width || !height) return;
    this.stats.video = { width, height };
    if (this.mode === 'tracking') {
      const intrinsics = this.intrinsicsFor(width, height);
      if (!intrinsics) {
        this.unseen(now, `Calibrate the camera at ${width}×${height} first, holding the phone as you will track.`);
        return;
      }
      this.send(frame => ({ kind: 'locate', token, frame, intrinsics: resizeIntrinsics(intrinsics, frame.width, frame.height), markers: this.markers }));
    } else if (this.mode === 'calibrating' && !this.solving && now - this.lastBoardAt >= BOARD_INTERVAL_MS) {
      this.lastBoardAt = now;
      this.send(frame => ({ kind: 'board', token, frame }));
    }
  }

  private send(request: (frame: Frame) => WorkerRequest): void {
    const size = processingSize(this.preview.videoWidth, this.preview.videoHeight, PROCESSING_LONG_SIDE);
    this.stats.processing = size;
    this.canvas.width = size.width;
    this.canvas.height = size.height;
    const context = this.canvas.getContext('2d', { willReadFrequently: true });
    if (!context) return;
    context.drawImage(this.preview, 0, 0, size.width, size.height);
    const rgba = context.getImageData(0, 0, size.width, size.height).data;
    this.busy = true;
    const message = request({ width: size.width, height: size.height, rgba });
    this.post(message, [rgba.buffer]);
  }

  private intrinsicsFor(width: number, height: number): CameraIntrinsics | null {
    const found = this.calibrations.find(item => item.width === width && item.height === height) ?? null;
    if (found !== this.calibration) {
      this.calibration = found;
      this.stats.calibration = found && {
        width: found.width, height: found.height, fx: found.fx, fy: found.fy, cx: found.cx, cy: found.cy,
        rms_px: found.rms_px, recorded_at: found.recorded_at,
      };
    }
    return found;
  }

  private receive(reply: WorkerReply): void {
    if (!('token' in reply) || reply.token !== this.token) return;
    this.busy = false;
    const now = performance.now();
    if (reply.kind === 'located') {
      this.frameTimes.push(now);
      while (this.frameTimes.length > 1 && now - this.frameTimes[0] > 2000) this.frameTimes.shift();
      const span = (now - this.frameTimes[0]) / 1000;
      this.stats.frames_per_second = span > 0 ? (this.frameTimes.length - 1) / span : 0;
      this.stats.detect_ms = reply.millis;
      if (reply.result.kind === 'tracked') {
        this.tracked(now, reply.result.pose, reply.result.markerIds);
      } else {
        this.unseen(now, reply.result.reason);
      }
    } else if (reply.kind === 'board') {
      const message = `Calibrating · ${reply.views} of ${CALIBRATION_VIEWS} board views · ${reply.corners} corners in view`;
      this.events.status({ mode: 'calibrating', tracked: false, message });
      if (reply.views >= CALIBRATION_VIEWS) {
        this.solving = true;
        this.busy = true;
        this.events.status({ mode: 'calibrating', tracked: false, message: 'Solving the camera calibration…' });
        this.post({ kind: 'solve', token: this.token });
      }
    } else if (reply.kind === 'solved') {
      void this.saveCalibration(reply.intrinsics, reply.rmsPx);
    } else if (reply.kind === 'solve-failed') {
      this.stop(`Calibration failed: ${reply.message}`);
    }
  }

  private tracked(now: number, pose: RoomPose, markerIds: number[]): void {
    this.trackedAt = now;
    this.reportedLost = false;
    this.stats.markers_seen = markerIds;
    this.stats.last_reason = null;
    this.events.view(pose);
    this.events.status({ mode: 'tracking', tracked: true, message: `Tracking · marker ${markerIds.join(', ')}` });
    if (now - this.publishedAt < PUBLISH_INTERVAL_MS) return;
    this.publishedAt = now;
    this.stats.poses_published++;
    this.events.publish({ tracking_status: 'tracked', reference_space: 'room', position: pose.position });
  }

  /** A frame without a usable marker. The last position is never repeated; after a short grace, the phone reports lost. */
  private unseen(now: number, reason: string): void {
    this.stats.last_reason = reason;
    this.stats.markers_seen = [];
    if (now - Math.max(this.trackedAt, this.startedAt) < LOST_AFTER_MS) return;
    this.events.status({ mode: 'tracking', tracked: false, message: `Lost · ${reason}` });
    if (this.reportedLost) return;
    this.reportedLost = true;
    this.events.publish({ tracking_status: 'lost', reference_space: null, position: null });
  }

  private async saveCalibration(intrinsics: CameraIntrinsics, rmsPx: number): Promise<void> {
    const token = this.token;
    const width = this.preview.videoWidth;
    const height = this.preview.videoHeight;
    // The views were processed smaller than the video; express the result in video pixels.
    const video = resizeIntrinsics(intrinsics, width, height);
    const body = {
      ...video, rms_px: rmsPx * width / intrinsics.width, views: CALIBRATION_VIEWS, user_agent: navigator.userAgent.slice(0, 512),
    };
    try {
      const response = await fetch('/api/tracking/cameras', {
        method: 'PUT', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body),
      });
      if (token !== this.token) return;
      if (!response.ok) throw new Error(await errorMessage(response, 'The calibration could not be saved'));
      const saved = await response.json() as CameraCalibration;
      this.stop(`Calibrated ${saved.width}×${saved.height} · error ${saved.rms_px.toFixed(2)} px`);
    } catch (error) {
      if (token === this.token) this.stop(error instanceof Error ? error.message : 'The calibration could not be saved.');
    }
  }
}
