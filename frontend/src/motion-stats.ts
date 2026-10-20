/**
 * Measurements of how motion reaches this device, for the diagnostic report. Every time here is
 * this device's own clock: a round trip is timed from send to answer on one device, and no
 * one-way latency is worked out from two devices' unsynchronised clocks.
 */

/** How long rates are averaged over, and how many samples of each kind are kept. */
const RATE_WINDOW_MS = 5000;
const KEPT = 100;

export interface Correction {
  /** When it happened, in milliseconds since the page loaded. */
  at: number;
  /** How far the drawn object jumped to reach Python's final placement, in meters. */
  meters: number;
}

/** The value a fraction `q` of the way up the sorted samples: 0.5 is the median. */
function quantile(values: readonly number[], q: number): number | null {
  if (values.length === 0) return null;
  const sorted = [...values].sort((a, b) => a - b);
  return sorted[Math.min(sorted.length - 1, Math.floor(sorted.length * q))];
}

export class MotionStats {
  private readonly states: number[] = [];
  private readonly poses: number[] = [];
  private readonly sentAt = new Map<number, number>();
  private readonly roundTrips: number[] = [];
  private readonly corrections: Correction[] = [];
  private acknowledged = 0;
  private coalesced = 0;

  /** A state arrived from Python. */
  state(now = performance.now()): void { this.push(this.states, now); }

  /** A pose with this sequence was sent to Python. */
  pose(sequence: number, now = performance.now()): void {
    this.push(this.poses, now);
    this.sentAt.set(sequence, now);
    // Only recent sends can still be answered.
    for (const old of this.sentAt.keys()) {
      if (this.sentAt.size <= KEPT) break;
      this.sentAt.delete(old);
    }
  }

  /** A pose waited for a congested connection and was replaced by a newer one before sending. */
  replaced(): void { this.coalesced++; }

  /** Python accepted movement up to this pose sequence: the round trip is timed on this device. */
  acknowledge(sequence: number | null, now = performance.now()): void {
    if (sequence === null || sequence <= this.acknowledged) return;
    this.acknowledged = sequence;
    const sent = this.sentAt.get(sequence);
    if (sent !== undefined) this.push(this.roundTrips, now - sent);
  }

  /** The drawn object jumped this far to Python's final placement when a hold ended. */
  correction(meters: number, now = performance.now()): void {
    this.corrections.push({ at: Math.round(now), meters: Number(meters.toFixed(4)) });
    if (this.corrections.length > KEPT) this.corrections.shift();
  }

  /** One line for the page's diagnostics. */
  summary(now = performance.now()): string {
    const ack = quantile(this.roundTrips, 0.5);
    const last = this.corrections.at(-1);
    return [
      `States ${this.rate(this.states, now).toFixed(1)}/s`,
      `poses ${this.rate(this.poses, now).toFixed(1)}/s`,
      `ack ${ack === null ? '–' : `${Math.round(ack)} ms`}`,
      `last correction ${last ? `${last.meters.toFixed(3)} m` : '–'}`,
    ].join(' · ');
  }

  report(settings: Record<string, unknown>, now = performance.now()): Record<string, unknown> {
    const connection = (navigator as unknown as { connection?: { effectiveType?: string; rtt?: number } }).connection;
    return {
      ...settings,
      browser_connection: connection ? { effective_type: connection.effectiveType ?? null, rtt_ms: connection.rtt ?? null } : null,
      state_rate_hz: Number(this.rate(this.states, now).toFixed(2)),
      pose_rate_hz: Number(this.rate(this.poses, now).toFixed(2)),
      poses_replaced_while_congested: this.coalesced,
      acknowledgement_round_trip_ms: {
        median: quantile(this.roundTrips, 0.5), p90: quantile(this.roundTrips, 0.9), samples: this.roundTrips.length,
      },
      corrections: [...this.corrections],
      largest_correction_m: this.corrections.reduce((most, c) => Math.max(most, c.meters), 0),
      clock_note: 'Round trips are timed on this device only; no cross-device one-way latency is inferred.',
    };
  }

  private push(samples: number[], value: number): void {
    samples.push(value);
    if (samples.length > KEPT) samples.shift();
  }

  private rate(times: readonly number[], now: number): number {
    const recent = times.filter(time => now - time <= RATE_WINDOW_MS);
    return recent.length / (RATE_WINDOW_MS / 1000);
  }
}
