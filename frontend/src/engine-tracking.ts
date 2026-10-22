/**
 * Measured phone tracking from the 8th Wall engine: its back camera and motion sensors together
 * give where the phone is in metres and which way it faces. The camera image is never drawn.
 */
import * as THREE from 'three';
import type { PhoneTracking } from './phone-tracking';
import { PhoneLook, START_EYE, START_VIEW, pitchOf, yawOf, type RoomPose } from './phone-view';
import type { Position, Rotation, TrackingStatus } from './protocol';

/** One frame of the engine's world tracking. */
interface Reality {
  position: Position;
  rotation: Rotation;
  /** `NORMAL` or `LIMITED`. */
  trackingStatus?: string;
  /** Why tracking is limited, such as `INITIALIZING`. */
  trackingReason?: string;
}

interface PipelineModule {
  name: string;
  onCameraStatusChange?: (args: { status: string }) => void;
  onException?: (error: unknown) => void;
  onStart?: (args: { canvas: HTMLCanvasElement }) => void;
  onUpdate?: (args: { processCpuResult: { reality?: Reality } }) => void;
}

/** The parts of the engine's `XR8` global this page uses. */
export interface Engine {
  addCameraPipelineModules(modules: PipelineModule[]): void;
  clearCameraPipelineModules(): void;
  run(options: { canvas: HTMLCanvasElement }): void;
  stop(): void;
  /** Releases the back camera and stops tracking until `resume`. */
  pause(): void;
  resume(): unknown;
  XrController: {
    configure(options: { scale: 'absolute' | 'responsive' }): void;
    updateCameraProjectionMatrix(options: { origin: Position; facing: Rotation }): void;
    recenter(): void;
    pipelineModule(): PipelineModule;
  };
  XrDevice: {
    isDeviceBrowserCompatible(options: { allowedDevices: unknown }): boolean;
    incompatibleReasons(options: { allowedDevices: unknown }): unknown[];
  };
  XrConfig: { device(): { MOBILE: unknown } };
}

/** The engine, when it has loaded and can track on this device and browser; otherwise null. */
export function trackingEngine(): Engine | null {
  return engineUnavailable() === null ? (window as unknown as { XR8: Engine }).XR8 : null;
}

/** Why the engine cannot track here, or null when it can. */
export function engineUnavailable(): string | null {
  const engine = (window as unknown as { XR8?: Engine }).XR8;
  if (!engine) return 'engine not loaded';
  try {
    const allowedDevices = engine.XrConfig.device().MOBILE;
    if (engine.XrDevice.isDeviceBrowserCompatible({ allowedDevices })) return null;
    return `device or browser not supported (reasons ${engine.XrDevice.incompatibleReasons({ allowedDevices }).join(', ')})`;
  } catch (error) {
    // A partly loaded engine must not stop the phone from counting steps instead.
    return `engine check failed: ${error instanceof Error ? error.message : String(error)}`;
  }
}

// Its starting direction: level, toward the desk. The phone's real tilt comes from the engine.
const TOWARD_DESK = { w: 1, x: 0, y: 0, z: 0 };

interface EngineEvents {
  /** The engine has measured a new pose. */
  moved: (pose: RoomPose) => void;
  /** Opening the camera: `requesting`, `hasStream`, `hasVideo` or `failed`. */
  camera: (status: string) => void;
  /** The engine's own tracking status and reason changed. */
  tracking: (status: string, reason: string) => void;
  /** This source's status changed; `hint` says what to do about it, empty when tracked. */
  status: (status: TrackingStatus, hint: string) => void;
  /** After a loss, the room was lined up again with where the phone was; `detail` says by how much. */
  realigned: (detail: string, correction: Correction) => void;
  error: (message: string) => void;
  /** Every frame as the engine gives it, before it is held or lined up: for measuring camera switches. */
  frame?: (status: string, reason: string, raw: RoomPose) => void;
}

const STARTING_HINT = 'Starting tracking · move the phone gently';
const UP = new THREE.Vector3(0, 1, 0);
// How near the start, and how close to facing the desk, a recovery must be to count as a restart.
const RESTART_NEAR = 0.5;
const RESTART_FACING = 30 * Math.PI / 180;

// Every loss on the iPhone came with the phone pointing this far down or more, at the plain floor.
const STEEP_DOWN = -50 * Math.PI / 180;

/** How the room is lined up with the engine after a recovery from a loss or a camera switch. */
export interface Correction {
  /** Whether this recovery changed the line-up; when false, the one before stays in effect. */
  applied: boolean;
  /** The turn about the vertical, and the shift, in effect on the engine's poses from now on. */
  yaw_deg: number;
  shift_m: { x: number; y: number; z: number };
}

export class EngineTracking implements PhoneTracking {
  private running = false;
  /** Counts starts and stops, so a start that finishes after a stop does not run the engine. */
  private attempts = 0;
  private latest: RoomPose | null = null;
  /** The engine's last status and reason, to report each change once. */
  private engineStatus = '';
  /** Whether the engine is tracking normally now, and whether it has since it started. */
  private normal = false;
  private everNormal = false;
  private reported: TrackingStatus = 'inactive';
  /**
   * Turns (about the vertical) and then shifts the engine's poses into the room. After a loss the
   * engine restarts at the starting viewpoint, wherever the phone really is, so this lines it up
   * again with the last good pose.
   */
  private yaw = 0;
  private readonly turn = new THREE.Quaternion();
  private readonly shift = new THREE.Vector3();
  private readonly scratch = new THREE.Vector3();
  private readonly scratchTurn = new THREE.Quaternion();
  private readonly scratchRaw = new THREE.Quaternion();
  /** The last good pose when tracking was lost, and the turn sensor's heading then. */
  private lostFrom: RoomPose | null = null;
  /**
   * Why the view is held: a loss, when the person may walk on, or a camera switch, made standing
   * still. It is kept with the hold, so it ends when the hold does.
   */
  private lostFor: 'loss' | 'switch' = 'loss';
  /** Whether a camera switch is under way: from `pause` until `endSwitch`. */
  private switching = false;
  private turnAtLoss: number | null = null;
  /** The orientation sensor, which keeps measuring turns while the engine is lost. */
  private readonly look = new PhoneLook();
  /**
   * While the engine cannot be used, lost or paused for a camera switch, the view holds its place
   * and turns with the orientation sensor; `heldTurn` lines the sensor's rotation up with the held
   * orientation. A pause counts as the start of a loss, so recovering from either lines up the same way.
   */
  private heldFrom: RoomPose | null = null;
  private heldTurn: THREE.Quaternion | null = null;
  private readonly scratchHeld = new THREE.Quaternion();

  constructor(private readonly engine: Engine, private readonly canvas: HTMLCanvasElement, private readonly events: EngineEvents) {}

  get active(): boolean { return this.running; }

  /**
   * `inactive` until the engine first tracks normally, since its poses mean nothing while it works
   * out scale; then `tracked`, or `lost` while it is limited, with the view held where it was.
   */
  get status(): TrackingStatus {
    if (!this.running || !this.everNormal) return 'inactive';
    return this.normal ? 'tracked' : 'lost';
  }

  /**
   * Starts the engine. Call from a tap: iPhone grants motion permission only during the tap that
   * asks, so it is asked here before the engine starts.
   */
  async start(): Promise<void> {
    if (this.running) return;
    const attempt = ++this.attempts;
    const motion = (DeviceMotionEvent as unknown as { requestPermission?: () => Promise<string> }).requestPermission;
    await Promise.all([
      // Without turn readings, a loss is lined up again as if the phone had not turned.
      this.look.active ? undefined : this.look.start().catch(error => {
        this.events.error(`orientation sensor unavailable, so turns while lost are not measured: ${error instanceof Error ? error.message : String(error)}`);
      }),
      typeof motion === 'function' ? motion.call(DeviceMotionEvent).catch(() => 'denied') : 'granted',
    ]);
    // Stopped, or started again, while the person answered the permission prompt.
    if (attempt !== this.attempts) {
      // The turn sensor may have started after the stop; a later start starts it again.
      if (!this.running) this.look.stop();
      return;
    }
    this.latest = null;
    this.engineStatus = '';
    this.normal = false;
    this.everNormal = false;
    this.straighten();
    const { engine } = this;
    engine.XrController.configure({ scale: 'absolute' });
    engine.clearCameraPipelineModules();
    engine.addCameraPipelineModules([
      engine.XrController.pipelineModule(),
      {
        name: 'escape-room-tracking',
        onCameraStatusChange: ({ status }) => this.events.camera(status),
        onException: error => this.events.error(error instanceof Error ? error.message : String(error)),
        // In metres, x, z and facing start here once scale is known; the engine replaces this y
        // with the phone's measured height above the floor.
        onStart: () => engine.XrController.updateCameraProjectionMatrix({ origin: START_EYE, facing: TOWARD_DESK }),
        onUpdate: ({ processCpuResult }) => {
          const reality = processCpuResult.reality;
          if (!reality) return;
          const { position: p, rotation: r } = reality;
          const raw = { position: { x: p.x, y: p.y, z: p.z }, orientation: { x: r.x, y: r.y, z: r.z, w: r.w } };
          this.events.frame?.(reality.trackingStatus ?? 'unknown', reality.trackingReason ?? 'unknown', raw);
          const engineStatus = `${reality.trackingStatus ?? 'unknown'} ${reality.trackingReason ?? 'unknown'}`;
          if (engineStatus !== this.engineStatus) {
            this.engineStatus = engineStatus;
            this.events.tracking(reality.trackingStatus ?? 'unknown', reality.trackingReason ?? 'unknown');
          }
          // Limited poses are guesses, metres or tens of metres off on the iPhone; hold the last good one.
          const wasNormal = this.normal;
          this.normal = reality.trackingStatus !== 'LIMITED';
          if (wasNormal && !this.normal && this.latest) this.hold(this.latest);
          if (this.normal) {
            this.everNormal = true;
            if (this.lostFrom) this.recover(raw, this.lostFrom);
            this.latest = this.intoRoom(raw);
            this.heldFrom = null;
          }
          this.reportStatus();
          if (this.normal) this.events.moved(this.latest!);
        },
      },
    ]);
    // Running and starting before the engine runs, so a frame it delivers at once finds them set.
    this.running = true;
    this.reported = 'inactive';
    this.events.status('inactive', STARTING_HINT);
    engine.run({ canvas: this.canvas });
  }

  private reportStatus(): void {
    const status = this.status;
    if (status === this.reported) return;
    this.reported = status;
    this.events.status(status, status === 'tracked' ? '' : status === 'inactive' ? STARTING_HINT : this.lostHint());
  }

  private lostHint(): string {
    const steep = this.latest !== null && pitchOf(this.latest.orientation) < STEEP_DOWN;
    return steep ? 'Tracking lost · raise the phone from the plain floor toward something with detail' :
      'Tracking lost · point at something with detail and move slower';
  }

  stop(): void {
    this.attempts++;
    this.heldFrom = null;
    this.switching = false;
    this.lostFor = 'loss';
    this.look.stop();
    if (!this.running) return;
    this.engine.stop();
    this.running = false;
  }

  /** Whether the view is held in place and turning with the orientation sensor, the engine away. */
  get viewHeld(): boolean { return this.heldFrom !== null; }

  /**
   * Releases the back camera for a while. Like a loss, the view holds its place and turns with the
   * orientation sensor until the engine tracks normally again.
   */
  pause(): void {
    if (!this.running) return;
    this.switching = true;
    // Already lost, the person may have walked on: the switch holds from where the view is now.
    if (this.heldFrom) {
      const here = this.pose();
      this.heldFrom = null;
      this.hold(here);
    } else if (this.latest) this.hold(this.latest);
    this.engine.pause();
  }

  /**
   * A camera switch has finished. A hold still waiting for tracking becomes an ordinary loss: from
   * here the person may walk, so a later recovery keeps where the engine finds itself.
   */
  endSwitch(): void {
    this.switching = false;
    this.lostFor = 'loss';
  }

  /**
   * Holds the view at `from`, turning with the sensor, and remembers it as where the loss began.
   * A hold already under way, such as a pause followed by a loss, keeps its start and turn.
   */
  private hold(from: RoomPose): void {
    if (this.heldFrom) return;
    this.heldFrom = from;
    this.heldTurn = this.turnFor(from, this.look.orientation());
    this.lostFrom = from;
    this.turnAtLoss = this.turnYaw();
    // During a switch, even a loss after a stale normal frame is the switch's to line up.
    this.lostFor = this.switching ? 'switch' : 'loss';
  }

  resume(): void {
    if (!this.running) return;
    void Promise.resolve(this.engine.resume()).catch(error => {
      this.events.error(`resume failed: ${error instanceof Error ? error.message : String(error)}`);
    });
  }

  /** Makes where the phone is now the starting viewpoint facing the desk. */
  recenter(): void {
    if (!this.running) return;
    this.straighten();
    this.engine.XrController.recenter();
  }

  /** Back to the engine's own world, as at the start. */
  private straighten(): void {
    this.lostFor = 'loss';
    this.yaw = 0;
    this.turn.identity();
    this.shift.set(0, 0, 0);
    this.lostFrom = null;
    this.turnAtLoss = null;
  }

  /**
   * After a loss, the engine either finds its place again or restarts at the starting viewpoint
   * facing the desk, wherever the phone really is. On the iPhone every restart came back within
   * 0.1 m of the start and 15° of the desk. Only a restart is lined up again with the last good pose;
   * a found place is kept, so movement during the loss is not thrown away.
   */
  private recover(raw: RoomPose, from: RoomPose): void {
    this.lostFrom = null;
    // A camera switch is made standing still, so whatever the engine says, the phone is where it was.
    if (this.lostFor === 'switch') {
      this.lostFor = 'loss';
      this.lineUp(raw, from, 'after a camera switch');
      return;
    }
    const away = Math.hypot(raw.position.x - START_EYE.x, raw.position.z - START_EYE.z);
    if (away > RESTART_NEAR || Math.abs(yawOf(raw.orientation)) > RESTART_FACING) {
      this.events.realigned(`kept: the engine found its place again, ${away.toFixed(2)} m from the start`, this.correction(false));
      return;
    }
    this.lineUp(raw, from, 'engine restarted');
  }

  private correction(applied: boolean): Correction {
    const round = (value: number) => Math.round(value * 1000) / 1000 + 0;
    return {
      applied, yaw_deg: Math.round(this.yaw * 180 / Math.PI * 10) / 10 + 0,
      shift_m: { x: round(this.shift.x), y: round(this.shift.y), z: round(this.shift.z) },
    };
  }

  /**
   * Lines the engine's restarted world up with the last good pose: the phone is taken to be where it
   * was, facing as far round from then as the turn sensor says it turned. Height is kept too, since
   * the restarted engine's height was 0.9-2.8 m off on the iPhone.
   */
  private lineUp(raw: RoomPose, from: RoomPose, why: string): void {
    const now = this.turnYaw();
    const turned = now !== null && this.turnAtLoss !== null ? now - this.turnAtLoss : 0;
    this.yaw = yawOf(from.orientation) + turned - yawOf(raw.orientation);
    this.turn.setFromAxisAngle(UP, this.yaw);
    const turnedRaw = this.scratch.set(raw.position.x, raw.position.y, raw.position.z).applyQuaternion(this.turn);
    this.shift.set(from.position.x, from.position.y, from.position.z).sub(turnedRaw);
    this.turnAtLoss = null;
    const p = from.position;
    this.events.realigned(`lined up, ${why}: engine at (${raw.position.x.toFixed(2)}, ${raw.position.y.toFixed(2)}, ${raw.position.z.toFixed(2)}); ` +
      `kept the last good place (${p.x.toFixed(2)}, ${p.y.toFixed(2)}, ${p.z.toFixed(2)}), turned ${(turned * 180 / Math.PI).toFixed(0)}° meanwhile`, this.correction(true));
  }

  private intoRoom(raw: RoomPose): RoomPose {
    const p = this.scratch.set(raw.position.x, raw.position.y, raw.position.z).applyQuaternion(this.turn).add(this.shift);
    const o = this.scratchTurn.copy(this.turn).multiply(this.scratchRaw.set(raw.orientation.x, raw.orientation.y, raw.orientation.z, raw.orientation.w));
    return { position: { x: p.x, y: p.y, z: p.z }, orientation: { x: o.x, y: o.y, z: o.z, w: o.w } };
  }

  private turnYaw(): number | null {
    const turned = this.look.orientation();
    return turned ? yawOf(turned) : null;
  }

  pose(): RoomPose {
    if (!this.heldFrom) return this.latest ?? START_VIEW;
    const sensed = this.look.orientation();
    if (!sensed) return this.heldFrom;
    // No sensor reading when the hold began: the first one counts as facing as the engine last did.
    this.heldTurn ??= this.turnFor(this.heldFrom, sensed);
    const turned = this.scratchHeld.copy(this.heldTurn!).multiply(sensed);
    return { position: this.heldFrom.position, orientation: { x: turned.x, y: turned.y, z: turned.z, w: turned.w } };
  }

  /** The rotation that takes `sensed` onto `pose`'s orientation, or null without a reading. */
  private turnFor(pose: RoomPose, sensed: THREE.Quaternion | null): THREE.Quaternion | null {
    if (!sensed) return null;
    const o = pose.orientation;
    return new THREE.Quaternion(o.x, o.y, o.z, o.w).multiply(sensed.clone().invert());
  }

  reportedPose(): RoomPose { return this.pose(); }

  orientation(): Rotation | null { return this.heldFrom ? this.pose().orientation : this.latest?.orientation ?? null; }
}
