/**
 * Where the phone is and which way it faces, from one source, so the room view, aiming, presence
 * and the poses sent to Python do not depend on how the phone is tracked.
 */
import { PhoneLook, START_EYE, headingOf, phoneViewpoint, type RoomPose } from './phone-view';
import type { Rotation, TrackingStatus } from './protocol';
import { StepWalker } from './step-walk';
import type { Floorplan } from './steps';

export interface PhoneTracking {
  readonly active: boolean;
  /** `tracked` while the source is running, otherwise `inactive`. */
  readonly status: TrackingStatus;
  /** Call from a tap: iPhone asks for sensor permission and only allows it during a gesture. */
  start(): Promise<void>;
  stop(): void;
  /** Where the room view looks from now and which way it faces. */
  pose(now?: number): RoomPose;
  /** Where tracking has put the phone, to tell Python: the end of a glide, not part way through. */
  reportedPose(): RoomPose;
  /** Which way the phone faces in the room, or null before the source has a reading. */
  orientation(): Rotation | null;
}

interface StepEvents {
  /** A step has started the view toward `pose`, `steps` steps since walking started. */
  step: (pose: RoomPose, steps: number) => void;
}

/**
 * Turning from the orientation sensor and walking by counted steps. Position is estimated, not
 * measured. `height` gives the height the view stands at.
 */
export class StepTracking implements PhoneTracking {
  private readonly look = new PhoneLook();
  private readonly walker: StepWalker;

  constructor(private readonly height: () => number, events: StepEvents) {
    this.walker = new StepWalker(START_EYE, () => headingOf(phoneViewpoint(this.look).orientation), {
      step: (position, steps) => events.step(this.at(position), steps),
    });
  }

  get active(): boolean { return this.look.active || this.walker.active; }

  get status(): TrackingStatus { return this.active ? 'tracked' : 'inactive'; }

  get stepLength(): number { return this.walker.stepLength; }
  set stepLength(meters: number) { this.walker.stepLength = meters; }

  setFloorplan(plan: Floorplan): void { this.walker.setFloorplan(plan); }

  /**
   * Starts turning and walking together, so both permission requests happen in the same tap. If
   * either fails, what this call started is stopped again; what was already running keeps running.
   */
  async start(): Promise<void> {
    const startTurning = !this.look.active;
    const startWalking = !this.walker.active;
    try {
      await Promise.all([startTurning && this.look.start(), startWalking && this.walker.start()]);
    } catch (error) {
      if (startTurning) this.look.stop();
      if (startWalking) this.walker.stop();
      throw error;
    }
  }

  /** Starts turning alone, for measuring the height, which needs only which way the phone faces. */
  startTurning(): Promise<void> {
    return this.look.active ? Promise.resolve() : this.look.start();
  }

  /** Stops turning and walking; the view stays where walking left it. */
  stop(): void {
    this.look.stop();
    this.walker.stop();
  }

  /** Puts the view back where the room view starts, and returns that pose. */
  reset(): RoomPose { return this.at(this.walker.reset()); }

  pose(now = performance.now()): RoomPose { return this.at(this.walker.position(now)); }

  reportedPose(): RoomPose { return this.at(this.walker.target()); }

  orientation(): Rotation | null { return this.look.orientation(); }

  private at(position: { x: number; z: number }): RoomPose {
    return phoneViewpoint(this.look, { x: position.x, y: this.height(), z: position.z });
  }
}
