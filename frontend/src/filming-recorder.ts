/**
 * The filming coach's camera (#100): records the room video in the page, with one prompt at a time
 * over the picture and a ring showing which ways have been filmed.
 *
 * Seven times a second a 90 x 160 grey copy of the frame is measured (`filming-coach`), and the
 * orientation sensor says where the camera points (`filming-coverage`); both work offline and on
 * low-end phones. Every few seconds a small JPEG also goes to the server, where Qwen says whether
 * it is a close-up of a plain surface or the floor is out of view; that check is quiet when it
 * fails or its budget is spent. The recording is MP4, which iPhone Safari and current Android Chrome record and
 * the server reads; where the browser can't, the coach isn't offered and the phone's own camera
 * app records as before.
 */

import { FilmingCoach, MEASURE_HEIGHT, MEASURE_WIDTH, measure, type Gray } from './filming-coach';
import { FilmingCoverage, cameraDirection, type Cell } from './filming-coverage';
import { element } from './dom';

const SAMPLE_MS = 1000 / 7;
/** The server's limits (#136, #100): at least 20 s, under 5 minutes. */
const LONGEST_MS = 5 * 60_000;
const MP4_TYPES = ['video/mp4;codecs=avc1', 'video/mp4'];
/** The server's check (#100): a frame this often, its prompt shown this long, this many pixels. */
const CHECK_EVERY_MS = 4000;
const CHECK_FIRST_MS = 1000;
const CHECK_SHOWN_MS = 6000;
const CHECK_LONG_SIDE = 320;
/** Checks that fail this many times running stop for the recording. */
const CHECK_FAILURES = 2;
/** A busy camera (just let go by another app) is tried this many times, this far apart. */
const CAMERA_TRIES = 4;
const CAMERA_RETRY_MS = 500;

/** The MP4 type this browser records, or null when it can't. */
export function recordingType(): string | null {
  if (typeof MediaRecorder === 'undefined' || !navigator.mediaDevices?.getUserMedia) return null;
  return MP4_TYPES.find(type => MediaRecorder.isTypeSupported(type)) ?? null;
}

function clock(ms: number): string {
  const seconds = Math.floor(ms / 1000);
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`;
}

/** A name for the recording, from when it started: room-2026-11-20-0915.mp4. */
function fileName(started: Date): string {
  const two = (value: number) => String(value).padStart(2, '0');
  return `room-${started.getFullYear()}-${two(started.getMonth() + 1)}-${two(started.getDate())}-`
    + `${two(started.getHours())}${two(started.getMinutes())}.mp4`;
}

interface DeviceOrientationWithPermission {
  requestPermission?: () => Promise<'granted' | 'denied'>;
}

export class FilmingRecorder {
  private readonly dialog = element('coach');
  private readonly camera = element<HTMLVideoElement>('coach-camera');
  private readonly promptLine = element('coach-prompt');
  private readonly ring = element<HTMLCanvasElement>('coach-ring');
  private readonly time = element('coach-time');
  private readonly recordButton = element<HTMLButtonElement>('coach-record');
  private readonly cancelButton = element<HTMLButtonElement>('coach-cancel');
  private readonly sampler = document.createElement('canvas');
  private stream: MediaStream | null = null;
  private recorder: MediaRecorder | null = null;
  private chunks: Blob[] = [];
  private started = 0;
  private startedAt = new Date();
  private timer: number | null = null;
  private previous: Gray | null = null;
  private coach = new FilmingCoach();
  private coverage = new FilmingCoverage();
  private facing: number | null = null;
  private note: string | null = null;
  private recording = '';
  private lastCheck = 0;
  private checking = false;
  private checksOn = true;
  private checkFailures = 0;
  private serverPrompt: { text: string; until: number } | null = null;
  private readonly onOrientation = (event: DeviceOrientationEvent) => {
    if (event.alpha === null || event.beta === null || event.gamma === null) return;
    const direction = cameraDirection(event.alpha, event.beta, event.gamma);
    this.facing = direction.heading;
    if (this.recorder) this.coverage.add(direction, performance.now());
  };

  /**
   * `type` is the MP4 type to record (`recordingType`); `done` gets the finished recording and
   * `failed` a reason the camera couldn't be used.
   */
  constructor(
    private readonly type: string,
    private readonly done: (file: File) => void,
    private readonly failed: (reason: string) => void,
  ) {
    this.recordButton.addEventListener('click', () => { void (this.recorder ? this.stop() : this.record()); });
    this.cancelButton.addEventListener('click', () => this.close());
  }

  /** Shows the camera, ready to record. */
  async open(): Promise<void> {
    const constraints: MediaStreamConstraints = {
      audio: false,
      video: { facingMode: { ideal: 'environment' }, width: { ideal: 1920 }, height: { ideal: 1080 }, frameRate: { ideal: 30 } },
    };
    for (let attempt = 1; ; attempt += 1) {
      try {
        this.stream = await navigator.mediaDevices.getUserMedia(constraints);
        break;
      } catch (error) {
        // A camera still held a moment by another app or page is busy, not refused: try again.
        const busy = error instanceof DOMException && error.name === 'NotReadableError';
        if (!busy || attempt === CAMERA_TRIES) {
          this.failed('The camera could not be opened. Allow camera access, or use Record video instead.');
          return;
        }
        await new Promise(resolve => setTimeout(resolve, CAMERA_RETRY_MS));
      }
    }
    this.camera.srcObject = this.stream;
    this.dialog.hidden = false;
    this.recordButton.textContent = 'Record';
    this.time.textContent = clock(0);
    this.show(null);
    this.drawRing([]);
    void this.camera.play().catch(() => undefined);
  }

  private minimumMs(): number {
    return Number(this.dialog.dataset.minSeconds ?? '20') * 1000;
  }

  private async record(): Promise<void> {
    if (!this.stream) return;
    // iPhones ask for the orientation sensor once, from a tap; without it, the ring stays empty.
    const permission = (DeviceOrientationEvent as unknown as DeviceOrientationWithPermission).requestPermission;
    if (permission) await permission().catch(() => 'denied');
    window.addEventListener('deviceorientation', this.onOrientation);
    this.coach = new FilmingCoach();
    this.coverage = new FilmingCoverage();
    this.previous = null;
    this.note = null;
    this.chunks = [];
    this.recording = `rec-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
    this.checksOn = true;
    this.checkFailures = 0;
    this.serverPrompt = null;
    this.recorder = new MediaRecorder(this.stream, { mimeType: this.type });
    this.recorder.addEventListener('dataavailable', event => { if (event.data.size) this.chunks.push(event.data); });
    this.recorder.start(1000);
    this.started = performance.now();
    this.lastCheck = this.started - CHECK_EVERY_MS + CHECK_FIRST_MS;
    this.startedAt = new Date();
    this.recordButton.textContent = 'Stop';
    this.dialog.dataset.recording = 'true';
    this.timer = window.setInterval(() => this.sample(), SAMPLE_MS);
  }

  private sample(): void {
    const now = performance.now();
    const elapsed = now - this.started;
    this.time.textContent = clock(elapsed);
    if (elapsed >= LONGEST_MS) {
      void this.stop();
      return;
    }
    const video = this.camera;
    if (video.videoWidth && video.videoHeight) {
      const portrait = video.videoHeight >= video.videoWidth;
      const width = portrait ? MEASURE_WIDTH : MEASURE_HEIGHT;
      const height = portrait ? MEASURE_HEIGHT : MEASURE_WIDTH;
      this.sampler.width = width;
      this.sampler.height = height;
      const context = this.sampler.getContext('2d', { willReadFrequently: true });
      if (context) {
        context.drawImage(video, 0, 0, width, height);
        const pixels = context.getImageData(0, 0, width, height).data;
        const grey = new Uint8Array(width * height);
        for (let i = 0; i < grey.length; i += 1) {
          grey[i] = (pixels[4 * i] * 77 + pixels[4 * i + 1] * 150 + pixels[4 * i + 2] * 29) >> 8;
        }
        const frame = { width, height, data: grey };
        this.coach.add(measure(frame, this.previous), now);
        this.previous = frame;
      }
    }
    if (this.checksOn && !this.checking && now - this.lastCheck >= CHECK_EVERY_MS) void this.check(now);
    if (this.note && elapsed >= this.minimumMs()) this.note = null;
    const asked = this.serverPrompt && now < this.serverPrompt.until ? this.serverPrompt.text : null;
    // One at a time: the phone's own picture checks, then Qwen's, then which ways are left.
    const prompt = this.coach.prompt(now)?.text ?? asked
      ?? (this.facing === null ? null : this.coverage.prompt(this.facing, now)?.text ?? null);
    this.show(this.note ?? prompt);
    this.drawRing(this.coverage.cells());
  }

  /** Sends a small frame to the server's check; any failure just leaves the prompt off. */
  private async check(now: number): Promise<void> {
    const video = this.camera;
    if (!video.videoWidth || !video.videoHeight) return;
    this.lastCheck = now;
    this.checking = true;
    const scale = CHECK_LONG_SIDE / Math.max(video.videoWidth, video.videoHeight);
    const canvas = document.createElement('canvas');
    canvas.width = Math.round(video.videoWidth * scale);
    canvas.height = Math.round(video.videoHeight * scale);
    canvas.getContext('2d')?.drawImage(video, 0, 0, canvas.width, canvas.height);
    const image = canvas.toDataURL('image/jpeg', 0.7).split(',')[1];
    const recording = this.recording;
    try {
      const response = await fetch('/api/coach/check', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ recording, image }),
      });
      if (!response.ok) throw new Error(`check ${response.status}`);
      const result = await response.json() as { status: string; prompt: string | null };
      if (recording !== this.recording) return;
      if (result.status === 'over_budget') this.checksOn = false;
      this.checkFailures = result.status === 'unavailable' ? this.checkFailures + 1 : 0;
      if (result.prompt) this.serverPrompt = { text: result.prompt, until: performance.now() + CHECK_SHOWN_MS };
    } catch {
      this.checkFailures += 1;
    } finally {
      this.checking = false;
      if (this.checkFailures >= CHECK_FAILURES) this.checksOn = false;
    }
  }

  private show(text: string | null): void {
    this.promptLine.textContent = text ?? '';
    this.promptLine.hidden = text === null;
  }

  private async stop(): Promise<void> {
    const recorder = this.recorder;
    if (!recorder) return;
    if (performance.now() - this.started < this.minimumMs()) {
      // Too short for a room: say so and keep filming. Cancel stops without keeping it.
      this.note = `Keep filming: at least ${this.minimumMs() / 1000} s, round the whole room`;
      this.show(this.note);
      return;
    }
    const finished = new Promise<void>(resolve => recorder.addEventListener('stop', () => resolve(), { once: true }));
    recorder.stop();
    await finished;
    const file = new File(this.chunks, fileName(this.startedAt), { type: 'video/mp4' });
    this.close();
    this.done(file);
  }

  /** Stops the camera and the recording, if any, without keeping it. */
  close(): void {
    if (this.timer !== null) window.clearInterval(this.timer);
    this.timer = null;
    window.removeEventListener('deviceorientation', this.onOrientation);
    if (this.recorder && this.recorder.state !== 'inactive') this.recorder.stop();
    this.recorder = null;
    this.stream?.getTracks().forEach(track => track.stop());
    this.stream = null;
    this.camera.srcObject = null;
    delete this.dialog.dataset.recording;
    this.dialog.hidden = true;
  }

  /** Twelve headings in three rings, floor innermost; filmed ones filled, and where it faces. */
  private drawRing(cells: Cell[]): void {
    const context = this.ring.getContext('2d');
    if (!context) return;
    const size = this.ring.width;
    const middle = size / 2;
    context.clearRect(0, 0, size, size);
    const radii = { floor: [12, 22], eye: [24, 34], ceiling: [36, 44] } as const;
    for (const band of ['floor', 'eye', 'ceiling'] as const) {
      for (let sector = 0; sector < 12; sector += 1) {
        const filmed = cells.some(cell => cell.band === band && cell.filmed && Math.floor(cell.heading / 30) === sector);
        // Heading 0 is up; clockwise as the headings are.
        const from = (sector * 30 - 90) * Math.PI / 180;
        const to = ((sector + 1) * 30 - 90) * Math.PI / 180;
        const [inner, outer] = radii[band];
        context.beginPath();
        context.arc(middle, middle, outer * size / 96, from + 0.04, to - 0.04);
        context.arc(middle, middle, inner * size / 96, to - 0.04, from + 0.04, true);
        context.closePath();
        context.fillStyle = filmed ? 'rgba(52, 199, 89, 0.95)' : 'rgba(255, 255, 255, 0.25)';
        context.fill();
      }
    }
    if (this.facing !== null) {
      const angle = (this.facing - 90) * Math.PI / 180;
      context.beginPath();
      context.moveTo(middle, middle);
      context.lineTo(middle + Math.cos(angle) * 46 * size / 96, middle + Math.sin(angle) * 46 * size / 96);
      context.strokeStyle = '#ffffff';
      context.lineWidth = 3;
      context.stroke();
    }
  }
}
