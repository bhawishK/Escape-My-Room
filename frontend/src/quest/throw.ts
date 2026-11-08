// How fast a held object is moving as it is let go, so letting go mid-swing throws it (#162).
import type { Position } from '../protocol';

/** Only the last this many milliseconds of movement count: the swing, not the wind-up. */
const WINDOW_MS = 100;
/** Fewer samples than this, or a shorter span, is too little to tell a speed from. */
const MIN_SAMPLES = 3;
const MIN_SPAN_MS = 30;

interface Sample { time: number; position: Position }

/**
 * The held object's recent places, one per frame, in room metres. Its velocity is the best-fit
 * straight line through the last 100 ms of them, which steadies the hand's frame-to-frame jitter.
 */
export class ThrowVelocity {
  private samples: Sample[] = [];

  add(position: Position, time: number): void {
    this.samples.push({ time, position: { ...position } });
    while (this.samples.length > 0 && time - this.samples[0].time > WINDOW_MS) this.samples.shift();
  }

  clear(): void {
    this.samples = [];
  }

  /** Metres per second, or null when there is too little recent movement to say. */
  velocity(now: number): Position | null {
    const recent = this.samples.filter(sample => now - sample.time <= WINDOW_MS);
    if (recent.length < MIN_SAMPLES) return null;
    const span = recent[recent.length - 1].time - recent[0].time;
    if (span < MIN_SPAN_MS) return null;
    const meanTime = recent.reduce((sum, sample) => sum + sample.time, 0) / recent.length;
    const spread = recent.reduce((sum, sample) => sum + (sample.time - meanTime) ** 2, 0);
    const slope = (axis: keyof Position): number => {
      const mean = recent.reduce((sum, sample) => sum + sample.position[axis], 0) / recent.length;
      const together = recent.reduce(
        (sum, sample) => sum + (sample.time - meanTime) * (sample.position[axis] - mean), 0);
      // Metres per millisecond, as metres per second.
      return (together / spread) * 1000;
    };
    return { x: slope('x'), y: slope('y'), z: slope('z') };
  }
}
