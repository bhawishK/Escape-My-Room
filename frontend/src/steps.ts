/**
 * Walking from the phone's motion sensor: steps detected from the accelerometer's bounce, and each
 * step moving the viewpoint across the room floor around the furniture. Not a measurement of
 * where the phone is; a rough, step-sized estimate. Pure, so the tests run it on synthetic motion.
 */
import type { Position, RoomEntity } from './protocol';

/** One `devicemotion` reading: acceleration including gravity in m/s², rotation rate in °/s. */
export interface MotionSample {
  time: number;
  x: number;
  y: number;
  z: number;
  rotationRate: number;
}

/** Vertical bounce, in m/s² above gravity, that counts as a step at each sensitivity. */
export const STEP_THRESHOLDS = { low: 1.6, normal: 1.1, high: 0.7 } as const;
export type Sensitivity = keyof typeof STEP_THRESHOLDS;

const GRAVITY_SMOOTHING_MS = 800;
const BOUNCE_SMOOTHING_MS = 60;
/** Steps closer together than this are one step; a brisk walk is about 2.5 steps a second. */
const MIN_STEP_INTERVAL_MS = 300;
/** A phone turning faster than this shakes the sensor without a step, so its readings are ignored. */
const MAX_ROTATION_DEG_S = 150;

/**
 * Counts steps from the vertical bounce of walking. Gravity's direction is tracked slowly, so the
 * phone may be held at any angle; a step is a rise above the threshold after the bounce fell back.
 */
export class StepDetector {
  private gravity: { x: number; y: number; z: number } | null = null;
  private bounce = 0;
  private lastTime: number | null = null;
  private armed = false;
  private lastStep = -Infinity;

  constructor(public threshold: number = STEP_THRESHOLDS.normal) {}

  /** True when this reading completes a step. */
  add(sample: MotionSample): boolean {
    const elapsed = this.lastTime === null ? 0 : Math.max(0, sample.time - this.lastTime);
    this.lastTime = sample.time;
    if (!this.gravity) {
      this.gravity = { x: sample.x, y: sample.y, z: sample.z };
      return false;
    }
    const slow = 1 - Math.exp(-elapsed / GRAVITY_SMOOTHING_MS);
    for (const axis of ['x', 'y', 'z'] as const) this.gravity[axis] += slow * (sample[axis] - this.gravity[axis]);
    const g = Math.hypot(this.gravity.x, this.gravity.y, this.gravity.z);
    if (!(g > 0)) return false;
    const vertical = (sample.x * this.gravity.x + sample.y * this.gravity.y + sample.z * this.gravity.z) / g - g;
    this.bounce += (1 - Math.exp(-elapsed / BOUNCE_SMOOTHING_MS)) * (vertical - this.bounce);
    if (sample.rotationRate > MAX_ROTATION_DEG_S) {
      this.armed = false;
      return false;
    }
    if (this.bounce < 0) this.armed = true;
    if (!this.armed || this.bounce < this.threshold || sample.time - this.lastStep < MIN_STEP_INTERVAL_MS) return false;
    this.armed = false;
    this.lastStep = sample.time;
    return true;
  }
}

/** A rectangle on the floor, in room meters. */
export interface Footprint { minX: number; maxX: number; minZ: number; maxZ: number }

export interface Floorplan {
  /** Where the floor is; walking stays on it. Null when the room has none. */
  floor: Footprint | null;
  /** Furniture that blocks walking. */
  obstacles: Footprint[];
}

/** An entity's footprint: its bottom face, turned by its rotation, as an axis-aligned rectangle. */
function footprint(entity: RoomEntity): Footprint {
  const { x: qx, y: qy, z: qz, w: qw } = entity.rotation;
  const halfW = entity.size.width / 2;
  const halfD = entity.size.depth / 2;
  const xs: number[] = [];
  const zs: number[] = [];
  for (const [x, z] of [[-halfW, -halfD], [halfW, -halfD], [halfW, halfD], [-halfW, halfD]]) {
    // v' = v + 2w(u × v) + 2u × (u × v), with v = (x, 0, z).
    const tx = 2 * (qy * z);
    const ty = 2 * (qz * x - qx * z);
    const tz = 2 * (-qy * x);
    xs.push(entity.position.x + x + qw * tx + (qy * tz - qz * ty));
    zs.push(entity.position.z + z + qw * tz + (qx * ty - qy * tx));
  }
  return { minX: Math.min(...xs), maxX: Math.max(...xs), minZ: Math.min(...zs), maxZ: Math.max(...zs) };
}

/** Thin static entities are floor; taller static ones are furniture. Movable objects never block. */
export function floorplan(entities: readonly RoomEntity[]): Floorplan {
  const floors = entities.filter(entity => entity.kind === 'static' && entity.size.height <= 0.05).map(footprint);
  const floor = floors.length === 0 ? null : {
    minX: Math.min(...floors.map(f => f.minX)), maxX: Math.max(...floors.map(f => f.maxX)),
    minZ: Math.min(...floors.map(f => f.minZ)), maxZ: Math.max(...floors.map(f => f.maxZ)),
  };
  const obstacles = entities.filter(entity => entity.kind === 'static' && entity.size.height > 0.05).map(footprint);
  return { floor, obstacles };
}

/** How close the person's center may come to furniture or the floor's edge. */
const BODY_RADIUS = 0.25;

function onFloor(plan: Floorplan, x: number, z: number): boolean {
  const { floor } = plan;
  return !floor || (x >= floor.minX + BODY_RADIUS && x <= floor.maxX - BODY_RADIUS
    && z >= floor.minZ + BODY_RADIUS && z <= floor.maxZ - BODY_RADIUS);
}

/** Whether a person may stand here: clear of furniture, and on the floor when `bounded`. */
function walkable(plan: Floorplan, x: number, z: number, bounded: boolean): boolean {
  if (bounded && !onFloor(plan, x, z)) return false;
  return !plan.obstacles.some(o => x > o.minX - BODY_RADIUS && x < o.maxX + BODY_RADIUS
    && z > o.minZ - BODY_RADIUS && z < o.maxZ + BODY_RADIUS);
}

/**
 * Where one step of `length` meters toward `heading` lands: 0 faces the desk (-Z) and positive
 * turns left. A step into furniture or off the floor slides along it, or stays put.
 * A person off the floor may walk anywhere clear of furniture, so they can walk onto it.
 */
export function stepFrom(from: Position, heading: number, length: number, plan: Floorplan): Position {
  const dx = -Math.sin(heading) * length;
  const dz = -Math.cos(heading) * length;
  // A person off the floor, such as at a splat room's start outside its floor, is not held back
  // by the floor's edge, or no step would ever land; once on the floor, its edge holds.
  const bounded = onFloor(plan, from.x, from.z);
  for (const [x, z] of [[from.x + dx, from.z + dz], [from.x + dx, from.z], [from.x, from.z + dz]]) {
    if (walkable(plan, x, z, bounded)) return { x, y: from.y, z };
  }
  return from;
}
