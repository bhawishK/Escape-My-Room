"""A walkable route across the room's floor (#275): round furniture and the fire, to a goal.

The floor is a grid of ROUTE_CELL squares inside its bounds. A cell is blocked by any object
standing on it (its footprint widened by a person's clearance, CLEARANCE) and, more widely, by
the burning object (FIRE_CLEARANCE). The route is the shortest way through free cells, moving
in eight directions (A*), then straightened where nothing is in the way, so it reads as a few
clean legs rather than a staircase. A start or goal on a blocked cell is moved to the nearest
free one; with no way through, there is no route.
"""

import heapq
import math
from collections.abc import Sequence

from backend.furniture import footprint
from backend.prepared_room import FLOOR_THICKNESS, SceneEntity, floor_bounds

ROUTE_CELL = 0.1
# A person needs this much room round furniture, and keeps this far from a fire.
CLEARANCE = 0.25
FIRE_CLEARANCE = 0.6
# Things that aren't in the way: the floor and walls; and flat things such as rugs.
FLAT = 0.05

Point = tuple[float, float]


def yaw_of(entity: SceneEntity) -> float:
    return 2 * math.atan2(entity.rotation.y, entity.rotation.w)


def _inside(point: Point, corners: Sequence[Point]) -> bool:
    """Whether `point` is inside the convex polygon `corners`, given in order round it."""
    sign = 0
    for (ax, az), (bx, bz) in zip(corners, [*corners[1:], corners[0]], strict=True):
        cross = (bx - ax) * (point[1] - az) - (bz - az) * (point[0] - ax)
        if abs(cross) < 1e-12:
            continue
        side = 1 if cross > 0 else -1
        if sign and side != sign:
            return False
        sign = side
    return True


class FloorGrid:
    """Which floor cells a person can stand on."""

    def __init__(self, entities: Sequence[SceneEntity], fire: str | None = None) -> None:
        bounds = floor_bounds(list(entities))
        self.x0, self.x1, self.z0, self.z1 = bounds or (-2.0, 2.0, -2.0, 2.0)
        self.columns = max(1, int((self.x1 - self.x0) / ROUTE_CELL))
        self.rows = max(1, int((self.z1 - self.z0) / ROUTE_CELL))
        self.blocked = [[False] * self.columns for _ in range(self.rows)]
        # The room's edge is a wall: a person keeps their clearance from it too.
        margin = max(1, round(CLEARANCE / ROUTE_CELL))
        for row in range(self.rows):
            for column in range(self.columns):
                if min(row, column, self.rows - 1 - row, self.columns - 1 - column) < margin - 1:
                    self.blocked[row][column] = True
        for entity in entities:
            if entity.size.height <= max(FLAT, FLOOR_THICKNESS) or entity.id.startswith(
                ("floor", "wall")
            ):
                continue
            clearance = FIRE_CLEARANCE if entity.id == fire else CLEARANCE
            size = type(entity.size)(
                width=entity.size.width + 2 * clearance,
                height=entity.size.height,
                depth=entity.size.depth + 2 * clearance,
            )
            corners = footprint(entity.position, size, yaw_of(entity))
            xs, zs = [c[0] for c in corners], [c[1] for c in corners]
            for row in range(self._row(min(zs)), self._row(max(zs)) + 1):
                for column in range(self._column(min(xs)), self._column(max(xs)) + 1):
                    if _inside(self.centre((column, row)), corners):
                        self.blocked[row][column] = True

    def _column(self, x: float) -> int:
        return min(self.columns - 1, max(0, int((x - self.x0) / ROUTE_CELL)))

    def _row(self, z: float) -> int:
        return min(self.rows - 1, max(0, int((z - self.z0) / ROUTE_CELL)))

    def cell(self, point: Point) -> tuple[int, int]:
        return self._column(point[0]), self._row(point[1])

    def centre(self, cell: tuple[int, int]) -> Point:
        column, row = cell
        return (self.x0 + (column + 0.5) * ROUTE_CELL, self.z0 + (row + 0.5) * ROUTE_CELL)

    def free(self, cell: tuple[int, int]) -> bool:
        column, row = cell
        return 0 <= column < self.columns and 0 <= row < self.rows and not self.blocked[row][column]

    def nearest_free(self, cell: tuple[int, int]) -> tuple[int, int] | None:
        """The free cell nearest `cell`, searching outwards; None if the floor is all blocked."""
        if self.free(cell):
            return cell
        for reach in range(1, max(self.columns, self.rows)):
            ring = [
                (cell[0] + dx, cell[1] + dz)
                for dx in range(-reach, reach + 1)
                for dz in range(-reach, reach + 1)
                if max(abs(dx), abs(dz)) == reach
            ]
            found = [c for c in ring if self.free(c)]
            if found:
                return min(found, key=lambda c: math.dist(c, cell))
        return None

    def clear_between(self, a: Point, b: Point) -> bool:
        """Whether the straight way from `a` to `b` crosses only free cells."""
        steps = max(1, int(math.dist(a, b) / (ROUTE_CELL / 3)))
        return all(
            self.free(
                self.cell((a[0] + (b[0] - a[0]) * i / steps, a[1] + (b[1] - a[1]) * i / steps))
            )
            for i in range(steps + 1)
        )


def route(
    entities: Sequence[SceneEntity], start: Point, goal: Point, fire: str | None = None
) -> list[Point] | None:
    """The walkable way from `start` to `goal` (x, z in room metres), round furniture and the
    burning object `fire`, as the points where it turns; None if there's no way through."""
    grid = FloorGrid(entities, fire)
    first, last = grid.nearest_free(grid.cell(start)), grid.nearest_free(grid.cell(goal))
    if first is None or last is None:
        return None
    came: dict[tuple[int, int], tuple[int, int] | None] = {first: None}
    cost: dict[tuple[int, int], float] = {first: 0.0}
    waiting: list[tuple[float, tuple[int, int]]] = [(0.0, first)]
    steps = [(dx, dz) for dx in (-1, 0, 1) for dz in (-1, 0, 1) if dx or dz]
    while waiting:
        _, here = heapq.heappop(waiting)
        if here == last:
            break
        for dx, dz in steps:
            there = (here[0] + dx, here[1] + dz)
            # No cutting a blocked corner diagonally.
            if not grid.free(there) or (
                dx
                and dz
                and not (grid.free((here[0] + dx, here[1])) and grid.free((here[0], here[1] + dz)))
            ):
                continue
            new = cost[here] + math.hypot(dx, dz)
            if new < cost.get(there, math.inf):
                cost[there], came[there] = new, here
                heapq.heappush(waiting, (new + math.dist(there, last), there))
    if last not in came:
        return None
    cells: list[tuple[int, int]] = []
    at: tuple[int, int] | None = last
    while at is not None:
        cells.append(at)
        at = came[at]
    cells.reverse()
    points = [start, *[grid.centre(c) for c in cells[1:-1]], goal]
    # Straightened: from each kept point, the furthest later point in plain sight.
    kept = [points[0]]
    index = 0
    while index < len(points) - 1:
        furthest = index + 1
        for later in range(len(points) - 1, index, -1):
            if grid.clear_between(points[index], points[later]):
                furthest = later
                break
        kept.append(points[furthest])
        index = furthest
    return [(round(x, 3), round(z, 3)) for x, z in kept]


def length(points: Sequence[Point]) -> float:
    return sum(math.dist(a, b) for a, b in zip(points, points[1:], strict=False))
