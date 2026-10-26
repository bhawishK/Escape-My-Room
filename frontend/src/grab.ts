import type { Position, Rotation, RoomEntity } from './protocol';

/** Rotate `vector` by a unit quaternion (x, y, z, w). Matches `rotate` in Python. */
export function rotate(orientation: Rotation, vector: Position): Position {
  const { x: qx, y: qy, z: qz, w: qw } = orientation;
  const { x, y, z } = vector;
  const cx = qy * z - qz * y;
  const cy = qz * x - qx * z;
  const cz = qx * y - qy * x;
  const dx = qy * cz - qz * cy;
  const dy = qz * cx - qx * cz;
  const dz = qx * cy - qy * cx;
  return {
    x: x + 2 * qw * cx + 2 * dx,
    y: y + 2 * qw * cy + 2 * dy,
    z: z + 2 * qw * cz + 2 * dz,
  };
}

/** The target ray looks along the controller's local -Z. */
export function rayForward(orientation: Rotation): Position {
  return rotate(orientation, { x: 0, y: 0, z: -1 });
}

/** Where the box sits in the grip's local frame. Reapplying it keeps the box from jumping. */
export function offsetOf(grip: Position, orientation: Rotation, box: Position): Position {
  return rotate(
    { x: -orientation.x, y: -orientation.y, z: -orientation.z, w: orientation.w },
    { x: box.x - grip.x, y: box.y - grip.y, z: box.z - grip.z },
  );
}

/** The box position for a later grip pose and the offset taken when it was grabbed. */
export function grabbedPosition(grip: Position, orientation: Rotation, offset: Position): Position {
  const moved = rotate(orientation, offset);
  return { x: grip.x + moved.x, y: grip.y + moved.y, z: grip.z + moved.z };
}

/**
 * The nearest movable object the ray hits within `maxDistance` meters, or null.
 * An entity's position is the center of its bottom face.
 */
export function targetAlongRay(
  origin: Position,
  direction: Position,
  entities: readonly RoomEntity[],
  maxDistance = 4,
): string | null {
  const length = Math.hypot(direction.x, direction.y, direction.z);
  if (length < 1e-8) return null;
  const ray = { x: direction.x / length, y: direction.y / length, z: direction.z / length };
  let closest: { id: string; distance: number } | null = null;
  for (const entity of entities) {
    if (entity.kind !== 'movable' || !entity.selectable) continue;
    const distance = rayDistance(origin, ray, entity, maxDistance);
    if (distance === null || (closest && distance >= closest.distance)) continue;
    closest = { id: entity.id, distance };
  }
  return closest?.id ?? null;
}

function rayDistance(
  origin: Position,
  direction: Position,
  entity: RoomEntity,
  maxDistance: number,
): number | null {
  const min = {
    x: entity.position.x - entity.size.width / 2,
    y: entity.position.y,
    z: entity.position.z - entity.size.depth / 2,
  };
  const max = {
    x: entity.position.x + entity.size.width / 2,
    y: entity.position.y + entity.size.height,
    z: entity.position.z + entity.size.depth / 2,
  };
  let near = 0;
  let far = maxDistance;
  for (const axis of ['x', 'y', 'z'] as const) {
    const component = direction[axis];
    if (Math.abs(component) < 1e-8) {
      if (origin[axis] < min[axis] || origin[axis] > max[axis]) return null;
      continue;
    }
    let enter = (min[axis] - origin[axis]) / component;
    let exit = (max[axis] - origin[axis]) / component;
    if (enter > exit) [enter, exit] = [exit, enter];
    near = Math.max(near, enter);
    far = Math.min(far, exit);
    if (near > far) return null;
  }
  return near;
}
