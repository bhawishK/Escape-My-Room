"""Where a hazard's 4D frames go in the room (#228, part of #221).

L4GM's frames are in its own frame: +y up, and the picture's camera at +z, so the object's
pictured front faces +z. Its 4D step renders its views lined up with the picture at azimuth 0 and
elevation 0, and kiui's `orbit_camera(0, 0)` stands at +z. Measured on the live bed: seen from
+z it looks like its video (0.79), from the sides it doesn't (0.31 to 0.35). The object comes out
level even though its picture was taken from 20 degrees above: the live bed is thinnest within
5 degrees of level, so it isn't tilted.

A hazard on an object in the room turns that front to face the side its picture was taken from,
scales the object's long side to its box's and stands it on the box's base, over the box's centre;
the real object is hidden (`hide`). A new object is placed the same way in a box of its true size,
from its description as furniture's is (#186), on the floor.

The measures are taken on the first frame, before the hazard grows (flames, smoke), and on its
splats' 2% to 98% spread, so a few stray splats don't count.
"""

import math
from dataclasses import dataclass
from typing import Literal

import numpy as np
from pydantic import BaseModel

from backend.furniture_generation import target_size

LOW, HIGH = 0.02, 0.98
# Only splats at least this opaque are measured: L4GM's faint haze spreads past the object.
SOLID = 0.5


@dataclass(frozen=True)
class Box:
    """A place for the object: its base's centre, turn about y (as three.js turns) and footprint
    (width along its own x). A box `by` height sets the object's height instead of its length."""

    x: float
    y: float
    z: float
    yaw: float
    width: float
    depth: float
    height: float | None = None
    by: Literal["long", "height"] = "long"

    @property
    def long_axis(self) -> tuple[float, float]:
        """The room's floor direction of the box's longer side."""
        if self.width >= self.depth:
            return math.cos(self.yaw), -math.sin(self.yaw)
        return math.sin(self.yaw), math.cos(self.yaw)


@dataclass(frozen=True)
class Footprint:
    axis: tuple[float, float]  # the floor direction `long` is measured along
    long: float
    short: float
    centre: tuple[float, float]  # the middle of the footprint, on the floor (x, z)
    base: float
    height: float


class Placement(BaseModel):
    """Where the frames go, as three.js places them: scaled, turned about y (rotation.y = turn),
    then moved."""

    position: tuple[float, float, float]
    turn: float
    scale: float
    # The room object the hazard replaces, hidden while it plays.
    hide: str | None = None


def footprint(xyz: np.ndarray, axis: tuple[float, float] | None = None) -> Footprint:
    """The splats' spread on the floor along `axis` (else their own longest direction) and
    across it, its middle, and their base and height."""
    floor = xyz[:, [0, 2]]
    if axis is None:
        _, vectors = np.linalg.eigh(np.cov((floor - floor.mean(axis=0)).T))
        axis = (float(vectors[0, 1]), float(vectors[1, 1]))
    along = np.array(axis) / math.hypot(*axis)
    across = np.array([-along[1], along[0]])
    a_low, a_high = np.quantile(floor @ along, [LOW, HIGH])
    c_low, c_high = np.quantile(floor @ across, [LOW, HIGH])
    middle = along * (a_low + a_high) / 2 + across * (c_low + c_high) / 2
    y_low, y_high = np.quantile(xyz[:, 1], [LOW, HIGH])
    return Footprint(
        axis=(float(along[0]), float(along[1])),
        long=float(a_high - a_low),
        short=float(c_high - c_low),
        centre=(float(middle[0]), float(middle[1])),
        base=float(y_low),
        height=float(y_high - y_low),
    )


def place(
    first_frame: dict[str, np.ndarray],
    box: Box,
    facing: tuple[float, float],
    hide: str | None = None,
) -> Placement:
    """The frames placed in `box`, their front turned to `facing` (the floor direction from the
    object towards where its picture was taken)."""
    turn = math.atan2(facing[0], facing[1])
    turned = turned_about_y(solid(first_frame), turn)
    shape = footprint(turned, box.long_axis)
    if box.by == "height" and box.height:
        scale = box.height / shape.height
    else:
        scale = max(box.width, box.depth) / shape.long
    return Placement(
        position=(
            box.x - scale * shape.centre[0],
            box.y - scale * shape.base,
            box.z - scale * shape.centre[1],
        ),
        turn=turn,
        scale=scale,
        hide=hide,
    )


def solid(splats: dict[str, np.ndarray]) -> np.ndarray:
    """The positions of the splats opaque enough to measure (all of them if none says)."""
    if "opacity" not in splats:
        return splats["xyz"]
    return splats["xyz"][1 / (1 + np.exp(-splats["opacity"])) >= SOLID]


def turned_about_y(xyz: np.ndarray, turn: float) -> np.ndarray:
    """Positions turned about y, as three.js turns them."""
    c, s = math.cos(turn), math.sin(turn)
    return np.stack([xyz[:, 0] * c + xyz[:, 2] * s, xyz[:, 1], -xyz[:, 0] * s + xyz[:, 2] * c], 1)


def true_size_box(description: str, at: tuple[float, float]) -> Box:
    """A new object's box on the floor at `at` (x, z): its height if the description gives one,
    else its length, its usual size or 1 m (as furniture is sized, #186), as its long side."""
    measure, metres = target_size(description)
    if measure == "height":
        return Box(
            x=at[0], y=0.0, z=at[1], yaw=0.0, width=1.0, depth=1.0, height=metres, by="height"
        )
    return Box(x=at[0], y=0.0, z=at[1], yaw=0.0, width=metres, depth=metres / 2)
