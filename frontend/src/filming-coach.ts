/**
 * The filming coach's checks (#100): from small grey copies of the camera's frames, how bright the
 * picture is, how much fine detail it has and how fast it moves, and the one prompt to show.
 *
 * Everything is worked out on the phone from a 90 x 160 frame, so it works offline and on low-end
 * phones. The limits come from room 10's own video sampled this way (7 a second), which made a good
 * room where it was filmed: steady filming moved about 0.2 frame widths a second and its fastest
 * sweep about 0.5; the close-up of a plain door had a sixth of the usual fine detail.
 */

export const MEASURE_WIDTH = 90;
export const MEASURE_HEIGHT = 160;

/** A grey frame, one byte a pixel, row by row. */
export interface Gray {
  width: number;
  height: number;
  data: Uint8Array | Uint8ClampedArray;
}

export interface FrameMeasure {
  /** Mean brightness, 0 to 1. */
  brightness: number;
  /** Fine detail: the variance of the frame's Laplacian. Low when blurred or plain. */
  detail: number;
  /** How far the picture moved since the previous frame, in frame widths; 0 for the first. */
  shift: number;
}

/** Picture prompts here; which ways are still to film, from `filming-coverage`. */
export type PromptId = 'dark' | 'fast' | 'blur' | 'plain' | 'left' | 'right' | 'behind' | 'floor';

export interface Prompt {
  id: PromptId;
  text: string;
}

const TEXTS: Record<PicturePrompt, string> = {
  dark: 'Too dark: turn the lights on',
  fast: 'Slow down',
  blur: 'Hold steady: the picture is blurred',
  plain: 'Step back to show more of the room',
};
type PicturePrompt = 'dark' | 'fast' | 'blur' | 'plain';
// Most important first: only one prompt shows at a time.
const PRIORITY: PicturePrompt[] = ['dark', 'fast', 'blur', 'plain'];

const DARK_BRIGHTNESS = 0.2;
/** Frame widths a second: room 10's fastest sweep was about 0.5. */
const FAST_WIDTHS_PER_SECOND = 0.6;
/** Blurred: under this share of the detail of the seconds before. */
const BLUR_SHARE = 0.3;
/** Plain: detail under this, for a while (the plain door close-up was about 180; usual 1,200). */
const PLAIN_DETAIL = 250;
/** How long each problem lasts before its prompt shows. */
const HOLD_MS: Record<PicturePrompt, number> = { dark: 500, fast: 300, blur: 300, plain: 1500 };
/** A prompt stays up at least this long, so it can be read. */
const SHOWN_MS = 1500;
/** Blur is judged against the detail between these many ms ago. */
const BEFORE_FROM_MS = 3000;
const BEFORE_TO_MS = 600;
// Picture shift is searched this far each way, at half size (10 of 45 pixels: 1.6 widths a second).
const SEARCH = 10;

function halfSize(frame: Gray): Float32Array {
  const width = frame.width >> 1;
  const height = frame.height >> 1;
  const out = new Float32Array(width * height);
  for (let y = 0; y < height; y += 1) {
    for (let x = 0; x < width; x += 1) {
      const i = 2 * y * frame.width + 2 * x;
      out[y * width + x] = (frame.data[i] + frame.data[i + 1] + frame.data[i + frame.width] + frame.data[i + frame.width + 1]) / 4;
    }
  }
  return out;
}

/** How far `current` moved from `previous`, in pixels of the half-size frames: the best match. */
function pictureShift(previous: Float32Array, current: Float32Array, width: number, height: number): number {
  let best = Infinity;
  let moved = 0;
  for (let dy = -SEARCH; dy <= SEARCH; dy += 1) {
    for (let dx = -SEARCH; dx <= SEARCH; dx += 1) {
      let sum = 0;
      for (let y = SEARCH; y < height - SEARCH; y += 1) {
        const row = y * width;
        const other = (y + dy) * width + dx;
        for (let x = SEARCH; x < width - SEARCH; x += 1) sum += Math.abs(previous[row + x] - current[other + x]);
      }
      // A near tie keeps the smaller move, so a featureless picture doesn't seem to jump.
      const distance = Math.hypot(dx, dy);
      if (sum < best * 0.999 || (sum <= best * 1.001 && distance < moved)) {
        best = Math.min(best, sum);
        moved = distance;
      }
    }
  }
  return moved;
}

/** Brightness, detail and movement of a frame; `previous` is the frame sampled before it. */
export function measure(frame: Gray, previous: Gray | null): FrameMeasure {
  const { width, height, data } = frame;
  let total = 0;
  for (let i = 0; i < data.length; i += 1) total += data[i];
  let sum = 0;
  let squares = 0;
  let count = 0;
  for (let y = 1; y < height - 1; y += 1) {
    for (let x = 1; x < width - 1; x += 1) {
      const i = y * width + x;
      const value = 4 * data[i] - data[i - 1] - data[i + 1] - data[i - width] - data[i + width];
      sum += value;
      squares += value * value;
      count += 1;
    }
  }
  const mean = sum / count;
  let shift = 0;
  if (previous && previous.width === width && previous.height === height) {
    shift = pictureShift(halfSize(previous), halfSize(frame), width >> 1, height >> 1) / (width >> 1);
  }
  return { brightness: total / data.length / 255, detail: squares / count - mean * mean, shift };
}

function median(values: number[]): number {
  const sorted = [...values].sort((a, b) => a - b);
  return sorted[Math.floor(sorted.length / 2)];
}

/** Turns measured frames into one prompt at a time, each only once its problem has lasted. */
export class FilmingCoach {
  private readonly history: { at: number; detail: number }[] = [];
  private last: { at: number; shift: number } | null = null;
  private readonly since = new Map<PicturePrompt, number>();
  private shown: { prompt: Prompt & { id: PicturePrompt }; at: number } | null = null;

  /** A frame's measures, sampled at `at` ms. */
  add(measured: FrameMeasure, at: number): void {
    const speed = this.last && at > this.last.at ? measured.shift / ((at - this.last.at) / 1000) : 0;
    this.last = { at, shift: measured.shift };
    const before = this.history.filter(h => h.at >= at - BEFORE_FROM_MS && h.at <= at - BEFORE_TO_MS);
    const active: Record<PicturePrompt, boolean> = {
      dark: measured.brightness < DARK_BRIGHTNESS,
      fast: speed > FAST_WIDTHS_PER_SECOND,
      blur: before.length >= 4 && measured.detail < BLUR_SHARE * median(before.map(h => h.detail)),
      plain: measured.detail < PLAIN_DETAIL,
    };
    for (const id of PRIORITY) {
      if (!active[id]) this.since.delete(id);
      else if (!this.since.has(id)) this.since.set(id, at);
    }
    this.history.push({ at, detail: measured.detail });
    while (this.history.length && this.history[0].at < at - BEFORE_FROM_MS) this.history.shift();
  }

  /** The prompt to show at `at` ms, or null. */
  prompt(at: number): Prompt | null {
    const due = PRIORITY.find(id => {
      const start = this.since.get(id);
      return start !== undefined && at - start >= HOLD_MS[id];
    });
    if (this.shown && at - this.shown.at < SHOWN_MS) {
      // A more important problem may replace it; a lesser one waits.
      if (due && PRIORITY.indexOf(due) < PRIORITY.indexOf(this.shown.prompt.id)) {
        this.shown = { prompt: { id: due, text: TEXTS[due] }, at };
      }
      return this.shown.prompt;
    }
    if (!due) {
      this.shown = null;
      return null;
    }
    if (this.shown?.prompt.id !== due) this.shown = { prompt: { id: due, text: TEXTS[due] }, at };
    return this.shown.prompt;
  }
}
