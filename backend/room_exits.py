"""The room's exits (#275, #280): its doors and windows, each with an anchor on the floor inside it.

Exit guidance sends the occupant to an exit. The room's layout (`layout.json`, from SpatialLM,
#270) gives the wall outline, an axis-aligned rectangle, and its openings. Each door and window
becomes an exit: the opening is put on the side of the rectangle its centre is nearest to, as the
walls do (`backend/room_walls.py`), and its anchor is the floor point INSET inside it, towards the
room's middle. The anchor is what a route leads to; the opening is what the headset points at.

A room without a usable layout has no exits. #276 fills them from AI for any room.
"""

import json
import math
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

# The anchor stands this far inside the opening, on the floor: where a person is at the exit.
INSET = 0.4
# And at least this far from the corners along its wall, so a door at a corner is reachable.
CORNER = 0.3

ExitKind = Literal["door", "window"]


class RoomExit(BaseModel):
    """A door or window of the room, in room metres (x, z on the floor; y up)."""

    id: str
    kind: ExitKind
    # The middle of the opening, on its wall: x, y (its middle's height), z.
    centre: tuple[float, float, float]
    width: float = Field(gt=0)
    height: float = Field(gt=0)
    # Out of the room through the opening, as a unit vector on the floor (x, z).
    outward: tuple[float, float]
    # Where a person stands at this exit: on the floor, INSET inside the opening (x, z).
    anchor: tuple[float, float]


Side = tuple[tuple[float, float], tuple[float, float]]


def exits_from_layout(layout: dict[str, object]) -> list[RoomExit]:
    """The room's doors, then its windows; none if the layout has no outline or openings."""
    walls = layout.get("walls")
    openings = layout.get("openings")
    if not isinstance(walls, dict) or not isinstance(openings, list):
        return []
    try:
        x0, x1 = sorted(float(v) for v in walls["x"])  # pyright: ignore[reportUnknownVariableType, reportUnknownArgumentType]
        z0, z1 = sorted(float(v) for v in walls["z"])  # pyright: ignore[reportUnknownVariableType, reportUnknownArgumentType]
    except (KeyError, TypeError, ValueError):
        return []
    if x1 - x0 <= 0 or z1 - z0 <= 0:
        return []
    middle = ((x0 + x1) / 2, (z0 + z1) / 2)
    sides: list[Side] = [
        ((x0, z0), (x1, z0)),
        ((x1, z0), (x1, z1)),
        ((x1, z1), (x0, z1)),
        ((x0, z1), (x0, z0)),
    ]
    exits: list[RoomExit] = []
    for index, opening in enumerate(openings):  # pyright: ignore[reportUnknownVariableType, reportUnknownArgumentType]
        if not isinstance(opening, dict):
            continue
        kind = opening.get("kind")  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
        if kind not in ("door", "window"):
            continue
        try:
            cx, cy, cz = (float(v) for v in opening["centre"])  # pyright: ignore[reportUnknownVariableType, reportUnknownArgumentType]
            width = float(opening["width"])  # pyright: ignore[reportUnknownArgumentType]
            height = float(opening["height"])  # pyright: ignore[reportUnknownArgumentType]
        except (KeyError, TypeError, ValueError):
            continue
        if width <= 0 or height <= 0:
            continue
        side = min(sides, key=lambda s: _distance_to_side(s, (cx, cz)))
        length = math.dist(*side)
        along = max(0.0, min(length, _along(side, (cx, cz))))
        on_wall = _at(side, along)
        # Out of the room: square to the wall, away from the middle.
        (ax, az), (bx, bz) = side
        nx, nz = (bz - az) / length, -(bx - ax) / length
        if (on_wall[0] - middle[0]) * nx + (on_wall[1] - middle[1]) * nz < 0:
            nx, nz = -nx, -nz
        # Inside: INSET in from the wall, but no further than the room's middle, and off corners.
        depth = abs((on_wall[0] - middle[0]) * nx + (on_wall[1] - middle[1]) * nz)
        corner = min(CORNER, length / 2)
        foot = _at(side, min(max(along, corner), length - corner))
        inset = min(INSET, depth)
        anchor = (foot[0] - nx * inset, foot[1] - nz * inset)
        raw_id = opening.get("id")  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
        exits.append(
            RoomExit(
                id=raw_id if isinstance(raw_id, str) and raw_id else f"{kind}_{index}",
                kind=kind,
                centre=(_r(on_wall[0]), _r(cy), _r(on_wall[1])),
                width=width,
                height=height,
                outward=(_r(nx) + 0.0, _r(nz) + 0.0),
                anchor=(_r(anchor[0]), _r(anchor[1])),
            )
        )
    exits.sort(key=lambda e: e.kind != "door")
    # Two openings given one id would be one exit to the devices: keep the first.
    unique: dict[str, RoomExit] = {}
    for exit_ in exits:
        unique.setdefault(exit_.id, exit_)
    return list(unique.values())


def room_exits(directory: Path) -> list[RoomExit]:
    """The exits of the room in `directory`, from its `layout.json` if it has one."""
    try:
        layout = json.loads((directory / "layout.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return exits_from_layout(layout) if isinstance(layout, dict) else []  # pyright: ignore[reportUnknownArgumentType]


def _r(value: float) -> float:
    return round(value, 4)


def _along(side: Side, point: tuple[float, float]) -> float:
    (ax, az), (bx, bz) = side
    return ((point[0] - ax) * (bx - ax) + (point[1] - az) * (bz - az)) / math.dist(*side)


def _at(side: Side, distance: float) -> tuple[float, float]:
    (ax, az), (bx, bz) = side
    share = distance / math.dist(*side)
    return (ax + (bx - ax) * share, az + (bz - az) * share)


def _distance_to_side(side: Side, point: tuple[float, float]) -> float:
    along = max(0.0, min(math.dist(*side), _along(side, point)))
    return math.dist(_at(side, along), point)
