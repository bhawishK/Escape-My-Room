/**
 * Measured phone tracking from the 8th Wall engine: its back camera and motion sensors together
 * give where the phone is in metres and which way it faces. The camera image is never drawn.
 */
import type { PhoneTracking } from './phone-tracking';
import { START_EYE, START_VIEW, type RoomPose } from './phone-view';
import type { Position, Rotation, TrackingStatus } from './protocol';

/** One frame of the engine's world tracking. */
interface Reality {
  position: Position;
  rotation: Rotation;
}

interface PipelineModule {
  name: string;
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
    pipelineModule(): PipelineModule;
  };
  XrDevice: { isDeviceBrowserCompatible(options: { allowedDevices: unknown }): boolean };
  XrConfig: { device(): { MOBILE: unknown } };
}

/** The engine, when it has loaded and can track on this device and browser; otherwise null. */
export function trackingEngine(): Engine | null {
  const engine = (window as unknown as { XR8?: Engine }).XR8;
  if (!engine) return null;
  return engine.XrDevice.isDeviceBrowserCompatible({ allowedDevices: engine.XrConfig.device().MOBILE }) ? engine : null;
}

// Its starting direction: level, toward the desk. The phone's real tilt comes from the engine.
const TOWARD_DESK = { w: 1, x: 0, y: 0, z: 0 };

interface EngineEvents {
  /** The engine has measured a new pose. */
  moved: (pose: RoomPose) => void;
}

export class EngineTracking implements PhoneTracking {
  private running = false;
  /** Counts starts and stops, so a start that finishes after a stop does not run the engine. */
  private attempts = 0;
  private latest: RoomPose | null = null;

  constructor(private readonly engine: Engine, private readonly canvas: HTMLCanvasElement, private readonly events: EngineEvents) {}

  get active(): boolean { return this.running; }

  get status(): TrackingStatus { return this.running ? 'tracked' : 'inactive'; }

  /**
   * Starts the engine. Call from a tap: iPhone grants motion permission only during the tap that
   * asks, so it is asked here before the engine starts.
   */
  async start(): Promise<void> {
    if (this.running) return;
    const attempt = ++this.attempts;
    await Promise.all([DeviceOrientationEvent, DeviceMotionEvent].map(event => {
      const request = (event as unknown as { requestPermission?: () => Promise<string> }).requestPermission;
      return typeof request === 'function' ? request.call(event).catch(() => 'denied') : 'granted';
    }));
    // Stopped, or started again, while the person answered the permission prompt.
    if (attempt !== this.attempts) return;
    this.latest = null;
    const { engine } = this;
    engine.XrController.configure({ scale: 'absolute' });
    engine.clearCameraPipelineModules();
    engine.addCameraPipelineModules([
      engine.XrController.pipelineModule(),
      {
        name: 'escape-room-tracking',
        // In metres, x, z and facing start here once scale is known; the engine replaces this y
        // with the phone's measured height above the floor.
        onStart: () => engine.XrController.updateCameraProjectionMatrix({ origin: START_EYE, facing: TOWARD_DESK }),
        onUpdate: ({ processCpuResult }) => {
          const reality = processCpuResult.reality;
          if (!reality) return;
          const { position: p, rotation: r } = reality;
          this.latest = { position: { x: p.x, y: p.y, z: p.z }, orientation: { x: r.x, y: r.y, z: r.z, w: r.w } };
          this.events.moved(this.latest);
        },
      },
    ]);
    engine.run({ canvas: this.canvas });
    this.running = true;
  }

  stop(): void {
    this.attempts++;
    if (!this.running) return;
    this.engine.stop();
    this.running = false;
  }

  pose(): RoomPose { return this.latest ?? START_VIEW; }

  reportedPose(): RoomPose { return this.pose(); }

  orientation(): Rotation | null { return this.latest?.orientation ?? null; }
}
