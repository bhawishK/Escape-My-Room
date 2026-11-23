/**
 * The room's walls in the dollhouse (#269): see-through panels from the room's layout, with a
 * cut-away. A wall standing between the viewer and the room's middle fades out, so the inside
 * always shows, as a real dollhouse's open side does. At life size none are drawn: the splat
 * shows the real walls.
 */

/** A piece of wall on the floor, from one end to the other (x, z in room metres), as the server sends it. */
export interface WallSegment {
  start: [number, number];
  end: [number, number];
  height: number;
  thickness: number;
}

/** The middle of the room the walls enclose: the middle of all their ends. */
export function wallsMiddle(walls: readonly WallSegment[]): [number, number] {
  const ends = walls.flatMap(wall => [wall.start, wall.end]);
  if (ends.length === 0) return [0, 0];
  return [
    ends.reduce((sum, end) => sum + end[0], 0) / ends.length,
    ends.reduce((sum, end) => sum + end[1], 0) / ends.length,
  ];
}

/**
 * Whether each wall is cut away for a viewer at `viewer` (x, z in room metres): it is when the
 * viewer is outside the room beyond it, so it would stand between them and the inside.
 */
export function cutAway(walls: readonly WallSegment[], viewer: [number, number]): boolean[] {
  const [cx, cz] = wallsMiddle(walls);
  return walls.map(wall => {
    const mx = (wall.start[0] + wall.end[0]) / 2;
    const mz = (wall.start[1] + wall.end[1]) / 2;
    // The wall's normal, turned to face out of the room.
    let nx = -(wall.end[1] - wall.start[1]);
    let nz = wall.end[0] - wall.start[0];
    if (nx * (mx - cx) + nz * (mz - cz) < 0) [nx, nz] = [-nx, -nz];
    return nx * (viewer[0] - mx) + nz * (viewer[1] - mz) > 0;
  });
}

/** A wall's place as a box: its middle, its turn about the vertical (three.js rotation.y) and length. */
export function wallBox(wall: WallSegment): { x: number; z: number; yaw: number; length: number } {
  const dx = wall.end[0] - wall.start[0];
  const dz = wall.end[1] - wall.start[1];
  return {
    x: (wall.start[0] + wall.end[0]) / 2,
    z: (wall.start[1] + wall.end[1]) / 2,
    // A box's length lies along its local x; turned by yaw it runs from start to end.
    yaw: Math.atan2(-dz, dx),
    length: Math.hypot(dx, dz),
  };
}
