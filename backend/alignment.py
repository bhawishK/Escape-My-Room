"""Convert one device's WebXR coordinates into the shared room frame.

A room point is ``R_y(yaw) * xr_point + origin``. ``origin`` is the room
position of that device's XR origin. ``yaw`` is a right-handed rotation about
Y, in radians. Yaw ``0`` keeps XR -Z, the view direction, pointing along
room -Z, which is toward the desk. The floor stays horizontal.
"""

import math
from typing import Literal

from pydantic import Field

from backend.protocol import Position, WireModel


class Alignment(WireModel):
    status: Literal["not_aligned", "aligned"] = "not_aligned"
    yaw: float = Field(default=0.0, ge=-math.pi, le=math.pi)
    origin: Position = Field(default_factory=lambda: Position(x=0.0, y=0.0, z=0.0))


def xr_to_room(alignment: Alignment, point: Position) -> Position:
    cosine = math.cos(alignment.yaw)
    sine = math.sin(alignment.yaw)
    return Position(
        x=cosine * point.x + sine * point.z + alignment.origin.x,
        y=point.y + alignment.origin.y,
        z=-sine * point.x + cosine * point.z + alignment.origin.z,
    )
