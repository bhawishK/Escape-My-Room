/**
 * Where a placement task asks the box to land, in room metres.
 * The point is the box's bottom centre. The reach is how far it may be and still count.
 */
export interface PlacementTarget {
  id: 'desk' | 'cabinet' | 'floor';
  label: string;
  point: { x: number; y: number; z: number };
  reach: { x: number; y: number; z: number };
}

/**
 * Floor spots in front of the stand-in room's furniture (`assets/prepared-room/manifest.json`).
 * The desk's front face is z = -0.90 and the box is 0.20 m deep, so its centre sits at z = -0.80.
 * The cabinet's front face is z = -1.00, so the box's centre sits at z = -0.90.
 * The floor spot is open floor, clear of both.
 */
export const PLACEMENT_TARGETS: PlacementTarget[] = [
  { id: 'desk', label: 'Desk', point: { x: 0, y: 0, z: -0.8 }, reach: { x: 0.4, y: 0.15, z: 0.15 } },
  { id: 'cabinet', label: 'Cabinet', point: { x: 1.4, y: 0, z: -0.9 }, reach: { x: 0.3, y: 0.15, z: 0.15 } },
  { id: 'floor', label: 'Floor', point: { x: 0, y: 0, z: 0.8 }, reach: { x: 0.3, y: 0.15, z: 0.3 } },
];

export function placementTarget(id: string): PlacementTarget | null {
  return PLACEMENT_TARGETS.find(target => target.id === id) ?? null;
}

/** Metres outside the region. Zero means the box's bottom centre landed inside it. */
export function placementError(
  position: { x: number; y: number; z: number },
  target: PlacementTarget,
): { metres: number; inside: boolean } {
  const outside = (delta: number, reach: number) => Math.max(0, Math.abs(delta) - reach);
  const metres = Math.hypot(
    outside(position.x - target.point.x, target.reach.x),
    outside(position.y - target.point.y, target.reach.y),
    outside(position.z - target.point.z, target.reach.z),
  );
  return { metres, inside: metres === 0 };
}
