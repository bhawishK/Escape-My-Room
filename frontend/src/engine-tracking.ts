/**
 * Measured phone tracking from the 8th Wall engine: its back camera and motion sensors together
 * give where the phone is in metres and which way it faces. The camera image is never drawn.
 */
import * as THREE from 'three';
import type { PhoneTracking } from './phone-tracking';
import { PhoneLook, START_EYE, START_VIEW, pitchOf, type RoomPose } from './phone-view';
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

/**
 * Why the engine cannot track here, or null when it can. `?tracking=steps` in the link turns it
 * off, to compare step counting with measured tracking on the same phone.
 */
export function engineUnavailable(): string | null {
  if (new URLSearchParams(location.search).get('tracking') === 'steps') return 'step counting chosen in the link';
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
  realigned: (detail: string) => void;
  /** The scale was measured: `factor` times 8th Wall's distances is the room's. */
  scaled: (scale: EngineScale) => void;
  error: (message: string) => void;
}

const STARTING_HINT = 'Starting tracking · move the phone gently';
const UP = new THREE.Vector3(0, 1, 0);
// How near the start, and how close to facing the desk, a recovery must be to count as a restart.
const RESTART_NEAR = 0.5;
const RESTART_FACING = 30 * Math.PI / 180;

/**
 * The turn about the vertical, 0 facing the desk and positive to the left. Unlike the forward
 * vector's heading it stays steady when the phone points almost straight down, as before a loss.
 */
function yawOf(orientation: Rotation): number {
  const q = new THREE.Quaternion(orientation.x, orientation.y, orientation.z, orientation.w);
  return new THREE.Euler().setFromQuaternion(q, 'YXZ').y;
}
// Every loss on the iPhone came with the phone pointing this far down or more, at the plain floor.
const STEEP_DOWN = -50 * Math.PI / 180;

/** How 8th Wall's distances were corrected: its height for the phone against the real one. */
export interface EngineScale {
  factor: number;
  engine_height_m: number;
  real_height_m: number;
  /** The measured factor was out of range, so the nearest believable one is used. */
  clamped: boolean;
}
/**
 * The phone's real height when the link gives none: the camera height splat rooms are scaled
 * for. On the iPhone 8th Wall put the phone 0.72 m and then 1.16 m up, against a real 1.3-1.4 m
 * (27 October 2026), so it walked the person 50-85% of the way.
 */
export const HELD_AT = 1.4;
// The height is the median over this much normal tracking, after each start and restart.
const SCALE_SAMPLE_MS = 1500;
const SCALE_SAMPLES = 5;
// A factor beyond these is a wrong height, not a scale error.
const MIN_FACTOR = 0.5;
const MAX_FACTOR = 2;

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
  /** Stopped so another feature can use a camera, until `resume`. */
  private pausedForCamera = false;
  /** A start is waiting on its permission prompt. */
  private starting = false;
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
  private turnAtLoss: number | null = null;
  /** The orientation sensor, which keeps measuring turns while the engine is lost. */
  private readonly look = new PhoneLook();

  /** 8th Wall's distances times this are the room's; 1 until the first measurement. */
  private factor = 1;
  /** Heights 8th Wall reported since it started, while the scale is being measured. */
  private heights: number[] = [];
  private sampleSince: number | null = null;
  private scaleKnown = false;

  constructor(
    private readonly engine: Engine,
    private readonly canvas: HTMLCanvasElement,
    private readonly events: EngineEvents,
    /** How high the phone is really held, in metres. */
    private readonly heldAt = HELD_AT,
  ) {}

  get active(): boolean { return this.running; }

  /** Stopped for another camera, until `resume`; the phone runs one camera at a time. */
  get paused(): boolean { return this.pausedForCamera; }

  /**
   * `inactive` until the engine first tracks normally, since its poses mean nothing while it works
   * out scale; then `tracked`, or `lost` while it is limited or paused, with the view held.
   */
  get status(): TrackingStatus {
    if (this.pausedForCamera) return 'lost';
    if (!this.running || !this.everNormal) return 'inactive';
    return this.normal ? 'tracked' : 'lost';
  }

  /**
   * Stops the engine so another feature can use a camera, including a start still waiting on its
   * permission prompt. The phone counts as lost, holding the view where it was, until `resume`;
   * `hint` says why.
   */
  pause(hint: string): void {
    if (this.pausedForCamera || (!this.running && !this.starting)) return;
    // A start still waiting on its prompt sees this and does not run the engine.
    this.attempts++;
    if (this.running) this.engine.stop();
    this.starting = false;
    // Still this phone's tracking, only stopped for now, so `stop` ends it.
    this.running = true;
    this.pausedForCamera = true;
    this.reported = 'lost';
    this.events.status('lost', hint);
  }

  /**
   * Starts the engine again after a pause. It restarts at the starting viewpoint, so the room is
   * recentred there.
   */
  async resume(): Promise<void> {
    if (!this.pausedForCamera) return;
    this.pausedForCamera = false;
    this.running = false;
    await this.start();
  }

  /**
   * Starts the engine. Call from a tap: iPhone grants motion permission only during the tap that
   * asks, so it is asked here before the engine starts.
   */
  async start(): Promise<void> {
    if (this.running) return;
    const attempt = ++this.attempts;
    this.starting = true;
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
    this.starting = false;
    this.latest = null;
    this.factor = 1;
    this.measureScaleAgain();
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
          const engineStatus = `${reality.trackingStatus ?? 'unknown'} ${reality.trackingReason ?? 'unknown'}`;
          if (engineStatus !== this.engineStatus) {
            this.engineStatus = engineStatus;
            this.events.tracking(reality.trackingStatus ?? 'unknown', reality.trackingReason ?? 'unknown');
          }
          // Limited poses are guesses, metres or tens of metres off on the iPhone; hold the last good one.
          const wasNormal = this.normal;
          this.normal = reality.trackingStatus !== 'LIMITED';
          // The scale is measured over unbroken tracking: a loss before it is known starts again.
          if (wasNormal && !this.normal && !this.scaleKnown) this.measureScaleAgain();
          if (wasNormal && !this.normal && this.latest) {
            this.lostFrom = this.latest;
            this.turnAtLoss = this.turnYaw();
          }
          if (this.normal) {
            this.everNormal = true;
            this.sampleHeight(p.y, performance.now());
            const raw = { position: this.toScale(p), orientation: { x: r.x, y: r.y, z: r.z, w: r.w } };
            if (this.lostFrom) this.recover(raw, this.lostFrom);
            this.latest = this.intoRoom(raw);
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
    this.starting = false;
    this.look.stop();
    if (!this.running) return;
    // A paused engine is stopped already.
    if (!this.pausedForCamera) this.engine.stop();
    this.pausedForCamera = false;
    this.running = false;
  }

  /** Makes where the phone is now the starting viewpoint facing the desk. */
  recenter(): void {
    if (!this.running) return;
    this.straighten();
    this.engine.XrController.recenter();
  }

  /** Back to the engine's own world, as at the start. */
  private straighten(): void {
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
    const away = Math.hypot(raw.position.x - START_EYE.x, raw.position.z - START_EYE.z);
    if (away > RESTART_NEAR || Math.abs(yawOf(raw.orientation)) > RESTART_FACING) {
      this.events.realigned(`kept: the engine found its place again, ${away.toFixed(2)} m from the start`);
      return;
    }
    this.lineUp(raw, from);
  }

  /**
   * Lines the engine's restarted world up with the last good pose: the phone is taken to be where it
   * was, facing as far round from then as the turn sensor says it turned. Height is kept too, since
   * the restarted engine's height was 0.9-2.8 m off on the iPhone.
   */
  /** 8th Wall's position in real metres: scaled about where it started, and its height too. */
  private toScale(p: Position): Position {
    const f = this.factor;
    return { x: START_EYE.x + f * (p.x - START_EYE.x), y: f * p.y, z: START_EYE.z + f * (p.z - START_EYE.z) };
  }

  /** Collects 8th Wall's heights until there are enough to say how far off its scale is. */
  private sampleHeight(height: number, now: number): void {
    if (this.scaleKnown) return;
    this.sampleSince ??= now;
    this.heights.push(height);
    if (now - this.sampleSince < SCALE_SAMPLE_MS || this.heights.length < SCALE_SAMPLES) return;
    const sorted = [...this.heights].sort((a, b) => a - b);
    const reported = sorted[Math.floor(sorted.length / 2)];
    const measured = reported > 0 ? this.heldAt / reported : MAX_FACTOR;
    this.factor = Math.min(MAX_FACTOR, Math.max(MIN_FACTOR, measured));
    this.scaleKnown = true;
    this.events.scaled({
      factor: Number(this.factor.toFixed(3)), engine_height_m: Number(reported.toFixed(3)),
      real_height_m: this.heldAt, clamped: this.factor !== measured,
    });
  }

  /** A restarted engine works its scale out afresh, so it is measured again. */
  private measureScaleAgain(): void {
    this.scaleKnown = false;
    this.heights = [];
    this.sampleSince = null;
  }

  private lineUp(raw: RoomPose, from: RoomPose): void {
    this.measureScaleAgain();
    const now = this.turnYaw();
    const turned = now !== null && this.turnAtLoss !== null ? now - this.turnAtLoss : 0;
    this.yaw = yawOf(from.orientation) + turned - yawOf(raw.orientation);
    this.turn.setFromAxisAngle(UP, this.yaw);
    const turnedRaw = this.scratch.set(raw.position.x, raw.position.y, raw.position.z).applyQuaternion(this.turn);
    this.shift.set(from.position.x, from.position.y, from.position.z).sub(turnedRaw);
    this.turnAtLoss = null;
    const p = from.position;
    this.events.realigned(`lined up: engine restarted at (${raw.position.x.toFixed(2)}, ${raw.position.y.toFixed(2)}, ${raw.position.z.toFixed(2)}); ` +
      `kept the last good place (${p.x.toFixed(2)}, ${p.y.toFixed(2)}, ${p.z.toFixed(2)}), turned ${(turned * 180 / Math.PI).toFixed(0)}° while lost`);
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

  pose(): RoomPose { return this.latest ?? START_VIEW; }

  reportedPose(): RoomPose { return this.pose(); }

  orientation(): Rotation | null { return this.latest?.orientation ?? null; }
}
