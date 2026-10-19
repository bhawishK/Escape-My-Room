/**
 * Moves the phone's room view one step at a time as the person walks, from `devicemotion`.
 * Each step glides the view a step length toward where the phone faces, around the furniture.
 */
import type { Position } from './protocol';
import { STEP_THRESHOLDS, StepDetector, stepFrom, type Floorplan, type Sensitivity } from './steps';

/** How long the view takes to glide one step, so it moves rather than jumps. */
const GLIDE_MS = 350;
export const STEP_LENGTHS = [0.4, 0.5, 0.6, 0.7, 0.8] as const;

interface WalkEvents {
  /** The view has started toward a new position, `steps` steps since walking started. */
  step: (position: Position, steps: number) => void;
}

export class StepWalker {
  private readonly detector = new StepDetector();
  private listening = false;
  private from: Position;
  private to: Position;
  private movedAt = -Infinity;
  private steps = 0;
  private plan: Floorplan = { floor: null, obstacles: [] };
  stepLength = 0.6;
  sensitivity: Sensitivity = 'normal';
  private readonly listener = (event: DeviceMotionEvent) => {
    const a = event.accelerationIncludingGravity;
    if (a?.x == null || a.y == null || a.z == null) return;
    const r = event.rotationRate;
    const rotationRate = Math.hypot(r?.alpha ?? 0, r?.beta ?? 0, r?.gamma ?? 0);
    if (this.detector.add({ time: event.timeStamp, x: a.x, y: a.y, z: a.z, rotationRate })) this.step();
  };

  /** `heading` gives the direction the phone faces: 0 toward the desk, positive turning left. */
  constructor(private readonly home: Position, private readonly heading: () => number, private readonly events: WalkEvents) {
    this.from = home;
    this.to = home;
  }

  get active(): boolean { return this.listening; }

  setFloorplan(plan: Floorplan): void { this.plan = plan; }

  setSensitivity(sensitivity: Sensitivity): void {
    this.sensitivity = sensitivity;
    this.detector.threshold = STEP_THRESHOLDS[sensitivity];
  }

  /** Call from a button press: iPhone asks for motion permission and only allows it during a gesture. */
  async start(): Promise<void> {
    const request = (DeviceMotionEvent as unknown as { requestPermission?: () => Promise<string> })
      .requestPermission;
    if (typeof request === 'function') {
      const answer = await request.call(DeviceMotionEvent).catch(() => 'denied');
      if (answer !== 'granted') {
        throw new Error('Motion permission was denied. Allow motion access for this site, then try again.');
      }
    }
    this.steps = 0;
    window.addEventListener('devicemotion', this.listener);
    this.listening = true;
  }

  /** Stops counting steps; the view stays where walking left it. */
  stop(): void {
    window.removeEventListener('devicemotion', this.listener);
    this.listening = false;
  }

  /** Puts the view back where the room view starts. */
  reset(): Position {
    this.from = this.home;
    this.to = this.home;
    this.movedAt = -Infinity;
    return this.to;
  }

  /** Where the view is now, part way through a glide when a step was just taken. */
  position(now = performance.now()): Position {
    const t = Math.min(1, Math.max(0, (now - this.movedAt) / GLIDE_MS));
    const eased = t * (2 - t);
    return {
      x: this.from.x + eased * (this.to.x - this.from.x),
      y: this.to.y,
      z: this.from.z + eased * (this.to.z - this.from.z),
    };
  }

  /** Where the view is heading: the end of the current glide. */
  target(): Position { return this.to; }

  private step(): void {
    const now = performance.now();
    this.from = this.position(now);
    this.to = stepFrom(this.to, this.heading(), this.stepLength, this.plan);
    this.movedAt = now;
    this.steps++;
    this.events.step(this.to, this.steps);
  }
}
