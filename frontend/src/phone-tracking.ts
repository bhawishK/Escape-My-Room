/**
 * The phone's camera tracking: the back camera, the OpenCV worker, and the tracked and lost
 * states Python is told about. The camera feed is never shown; the room view is the display.
 */
import { assumedIntrinsics, processingSize, resizeIntrinsics, type ImageSize, type RoomPose } from './marker-geometry';
import type { PoseInput, TrackingMarker } from './protocol';
import type { WorkerReply, WorkerRequest } from './tracking.worker';

/** Frames are processed with their long side at most this many pixels. */
export const PROCESSING_LONG_SIDE = 960;
/** Poses are published at most every 50 ms, 20 per second, as the WebXR path did. */
const PUBLISH_INTERVAL_MS = 50;
/** With no usable marker view for this long, the phone reports tracking lost. */
export const LOST_AFTER_MS = 300;

export type TrackerMode = 'off' | 'starting' | 'tracking';

export interface TrackerStatus {
  mode: TrackerMode;
  /** While tracking: whether the last frames gave a usable room position. */
  tracked: boolean;
  message: string;
}

export interface TrackingReport {
  video: ImageSize | null;
  processing: ImageSize | null;
  frames_per_second: number;
  detect_ms: number;
  poses_published: number;
  markers_seen: number[];
  last_reason: string | null;
}

interface TrackerEvents {
  publish: (pose: PoseInput) => void;
  status: (status: TrackerStatus) => void;
  /** The phone's latest measured pose, each time one is measured. */
  measured: (pose: RoomPose) => void;
}

export function cameraError(error: unknown): string {
  if (error instanceof DOMException) {
    if (error.name === 'NotAllowedError' || error.name === 'SecurityError') {
      return 'Camera permission was denied. '
        + 'Allow camera access for this site in the browser settings, then try again.';
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
  private trackedAt = -Infinity;
  private startedAt = 0;
  private publishedAt = -Infinity;
  private reportedLost = false;
  private readonly frameTimes: number[] = [];
  private readonly stats: TrackingReport = {
    video: null, processing: null, frames_per_second: 0, detect_ms: 0,
    poses_published: 0, markers_seen: [], last_reason: null,
  };

  /** `video` receives the camera stream. It must stay rendered, however small, for frames to arrive. */
  constructor(private readonly video: HTMLVideoElement, private readonly events: TrackerEvents) {
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

  /** Releases the camera. A tracking phone tells Python its position is no longer available. */
  stop(message = 'Tracking off'): void {
    const wasTracking = this.mode === 'tracking';
    this.token++;
    this.mode = 'off';
    this.busy = false;
    if (this.frameRequest !== null) cancelAnimationFrame(this.frameRequest);
    this.frameRequest = null;
    for (const track of this.stream?.getTracks() ?? []) track.stop();
    this.stream = null;
    this.video.srcObject = null;
    if (wasTracking) this.events.publish({ tracking_status: 'inactive', reference_space: null, position: null });
    this.events.status({ mode: 'off', tracked: false, message });
  }

  async start(): Promise<void> {
    if (this.markers.length === 0) {
      throw new Error('This room has no tracking markers, so the phone cannot be placed in it.');
    }
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
      this.video.srcObject = stream;
      await Promise.all([this.video.play(), this.ensureWorker()]);
      if (token !== this.token) return;
      this.mode = 'tracking';
      this.startedAt = performance.now();
      this.trackedAt = -Infinity;
      this.publishedAt = -Infinity;
      this.reportedLost = false;
      this.stats.poses_published = 0;
      this.frameTimes.length = 0;
      this.events.status({ mode: 'tracking', tracked: false, message: 'Point the camera at the printed tag…' });
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

  private schedule(token: number): void {
    this.frameRequest = requestAnimationFrame(() => this.sample(token));
  }

  private sample(token: number): void {
    if (token !== this.token) return;
    this.schedule(token);
    if (this.busy || this.video.readyState < HTMLMediaElement.HAVE_CURRENT_DATA) return;
    const width = this.video.videoWidth;
    const height = this.video.videoHeight;
    if (!width || !height) return;
    this.stats.video = { width, height };
    const size = processingSize(width, height, PROCESSING_LONG_SIDE);
    this.stats.processing = size;
    this.canvas.width = size.width;
    this.canvas.height = size.height;
    const context = this.canvas.getContext('2d', { willReadFrequently: true });
    if (!context) return;
    context.drawImage(this.video, 0, 0, size.width, size.height);
    const rgba = context.getImageData(0, 0, size.width, size.height).data;
    this.busy = true;
    const request: WorkerRequest = {
      kind: 'locate', token, markers: this.markers, frame: { ...size, rgba },
      intrinsics: resizeIntrinsics(assumedIntrinsics(width, height), size.width, size.height),
    };
    this.worker?.postMessage(request, [rgba.buffer]);
  }

  private receive(reply: WorkerReply): void {
    if (reply.kind !== 'located' || reply.token !== this.token) return;
    this.busy = false;
    const now = performance.now();
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
  }

  private tracked(now: number, pose: RoomPose, markerIds: number[]): void {
    this.trackedAt = now;
    this.reportedLost = false;
    this.stats.markers_seen = markerIds;
    this.stats.last_reason = null;
    this.events.measured(pose);
    this.events.status({ mode: 'tracking', tracked: true, message: `Tracking · tag ${markerIds.join(', ')}` });
    if (now - this.publishedAt < PUBLISH_INTERVAL_MS) return;
    this.publishedAt = now;
    this.stats.poses_published++;
    this.events.publish({ tracking_status: 'tracked', reference_space: 'room', position: pose.position });
  }

  /**
   * A frame without a usable marker. The last position is never sent again; after a short grace
   * for single missed frames, the phone reports lost.
   */
  private unseen(now: number, reason: string): void {
    this.stats.last_reason = reason;
    this.stats.markers_seen = [];
    if (now - Math.max(this.trackedAt, this.startedAt) < LOST_AFTER_MS) return;
    this.events.status({ mode: 'tracking', tracked: false, message: `Lost · ${reason}` });
    if (this.reportedLost) return;
    this.reportedLost = true;
    this.events.publish({ tracking_status: 'lost', reference_space: null, position: null });
  }
}
