"""Walls from a room's layout (#269): drawn in the dollhouse, with a doorway.

SpatialLM's layout (`layout.json`, made by the #206 tools or the pipeline's layout stage, #270)
gives the room's wall outline, an axis-aligned rectangle with a height, and its openings. The
four walls are made from the rectangle; a door's wall is split round it, leaving a gap as wide
as the door at its centre. Windows are kept as wall. Physics has its own walls round the floor;
these are for seeing.
"""

import json
import math
from pathlib import Path

from pydantic import BaseModel, Field

THICKNESS = 0.08
# A piece of wall shorter than this beside a door is left out.
SHORTEST = 0.05


class WallSegment(BaseModel):
    """A straight piece of wall on the floor, from one end to the other (x, z in room metres)."""

    start: tuple[float, float]
    end: tuple[float, float]
    height: float = Field(gt=0)
    thickness: float = THICKNESS


def walls_from_layout(layout: dict[str, object]) -> list[WallSegment]:
    """The room's walls, each door's wall split round it; none if the layout has no outline."""
    walls = layout.get("walls")
    if not isinstance(walls, dict):
        return []
    try:
        x0, x1 = sorted(float(v) for v in walls["x"])  # pyright: ignore[reportUnknownVariableType, reportUnknownArgumentType]
        z0, z1 = sorted(float(v) for v in walls["z"])  # pyright: ignore[reportUnknownVariableType, reportUnknownArgumentType]
        height = float(walls["height"])  # pyright: ignore[reportUnknownArgumentType]
    except (KeyError, TypeError, ValueError):
        return []
    if x1 - x0 <= 0 or z1 - z0 <= 0 or height <= 0:
        return []
    # The four sides, going round.
    sides = [((x0, z0), (x1, z0)), ((x1, z0), (x1, z1)), ((x1, z1), (x0, z1)), ((x0, z1), (x0, z0))]
    gaps: list[list[tuple[float, float]]] = [[] for _ in sides]
    openings = layout.get("openings")
    for opening in openings if isinstance(openings, list) else []:  # pyright: ignore[reportUnknownVariableType]
        if not isinstance(opening, dict) or opening.get("kind") != "door":  # pyright: ignore[reportUnknownMemberType]
            continue
        try:
            centre = opening["centre"]  # pyright: ignore[reportUnknownVariableType]
            cx, cz = float(centre[0]), float(centre[2])  # pyright: ignore[reportUnknownArgumentType]
            width = float(opening["width"])  # pyright: ignore[reportUnknownArgumentType]
        except (KeyError, TypeError, ValueError, IndexError):
            continue
        # The door is on the side its centre is nearest to.
        nearest = min(range(4), key=lambda index: _distance_to_side(sides[index], (cx, cz)))
        along = _along(sides[nearest], (cx, cz))
        gaps[nearest].append((along - width / 2, along + width / 2))
    segments: list[WallSegment] = []
    for (start, end), side_gaps in zip(sides, gaps, strict=True):
        length = math.dist(start, end)
        for a, b in _pieces(length, side_gaps):
            segments.append(
                WallSegment(start=_at(start, end, a), end=_at(start, end, b), height=height)
            )
    return segments


def room_walls(directory: Path) -> list[WallSegment]:
    """The walls of the room in `directory`, from its `layout.json` if it has one."""
    path = directory / "layout.json"
    try:
        layout = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return walls_from_layout(layout) if isinstance(layout, dict) else []  # pyright: ignore[reportUnknownArgumentType]


def _along(
    side: tuple[tuple[float, float], tuple[float, float]], point: tuple[float, float]
) -> float:
    (ax, az), (bx, bz) = side
    length = math.dist(side[0], side[1])
    return ((point[0] - ax) * (bx - ax) + (point[1] - az) * (bz - az)) / length


def _distance_to_side(
    side: tuple[tuple[float, float], tuple[float, float]], point: tuple[float, float]
) -> float:
    length = math.dist(side[0], side[1])
    t = max(0.0, min(length, _along(side, point)))
    return math.dist(_at(side[0], side[1], t), point)


def _at(
    start: tuple[float, float], end: tuple[float, float], distance: float
) -> tuple[float, float]:
    length = math.dist(start, end)
    share = distance / length
    return (
        round(start[0] + (end[0] - start[0]) * share, 4),
        round(start[1] + (end[1] - start[1]) * share, 4),
    )


def _pieces(length: float, gaps: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """The stretches of a side of `length` outside its gaps, in order."""
    pieces: list[tuple[float, float]] = []
    at = 0.0
    for a, b in sorted((max(0.0, a), min(length, b)) for a, b in gaps):
        if a - at >= SHORTEST:
            pieces.append((at, a))
        at = max(at, b)
    if length - at >= SHORTEST:
        pieces.append((at, length))
    return pieces
