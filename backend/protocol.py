"""The shared prototype's WebSocket contract; phone positions are room-frame meters."""

import math
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

Role = Literal["mobile_master", "vr_solver"]
TrackingStatus = Literal["inactive", "tracked", "lost"]
# The phone reports its position in room coordinates directly.
ReferenceSpace = Literal["room"]


class WireModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class Position(WireModel):
    x: float = Field(ge=-100, le=100)
    y: float = Field(ge=-100, le=100)
    z: float = Field(ge=-100, le=100)


# Which way the phone faces across the floor, in radians: 0 toward the desk (-Z), positive left.
Heading = Annotated[float, Field(ge=-3.141592653589793, le=3.141592653589793)]
# How far the phone's screen centre looks above level, in radians: negative looks down.
Pitch = Annotated[float, Field(ge=-1.5707963267948966, le=1.5707963267948966)]


class MarkerState(WireModel):
    tracking_status: TrackingStatus = "inactive"
    reference_space: ReferenceSpace | None = None
    position: Position | None = None
    heading: Heading | None = None
    pitch: Pitch | None = None


PresenceStatus = Literal["inactive", "tracked", "lost", "stale"]


class PresenceState(WireModel):
    """Where one participant is in the room, and which way they face.

    Heading is radians about Y. ``0`` faces the desk, along room -Z. Positive
    turns left. ``stale`` keeps the last place after updates stop.
    """

    tracking_status: PresenceStatus = "inactive"
    position: Position | None = None
    heading: float | None = Field(default=None, ge=-math.pi, le=math.pi)


class RoomLoadedMessage(WireModel):
    type: Literal["room_loaded"]
    room_version: int = Field(ge=1)


class CalibrateMessage(WireModel):
    type: Literal["calibrate"]
    yaw: float = Field(ge=-3.141592653589793, le=3.141592653589793)
    origin: Position


class EntityTransformMessage(WireModel):
    type: Literal["entity_transform"]
    id: str = Field(pattern=r"^[a-z][a-z0-9_]{0,31}$")
    position: Position


class Orientation(WireModel):
    """A quaternion in (x, y, z, w) order. It is normalized when a grip is applied."""

    x: float = Field(ge=-2, le=2)
    y: float = Field(ge=-2, le=2)
    z: float = Field(ge=-2, le=2)
    w: float = Field(ge=-2, le=2)


class SelectMessage(WireModel):
    """The phone's private choice of the object it means to manipulate; a null id deselects."""

    type: Literal["select"]
    room_version: int = Field(ge=1)
    id: str | None = Field(max_length=64)


class AcquireMessage(WireModel):
    """Take hold of an object. The phone names its selection; the headset also sends its grip."""

    type: Literal["acquire"]
    room_version: int = Field(ge=1)
    id: str = Field(max_length=64)
    # Headset only, in room meters. Omitted by the phone, which aims across the floor instead.
    position: Position | None = None
    orientation: Orientation | None = None


class ReleaseMessage(WireModel):
    """The holder lets go. The object stays where the hold left it and is not passed on."""

    type: Literal["release"]
    manipulation_id: int = Field(ge=1)


class GripMessage(WireModel):
    """The headset's controller grip while it holds an object, in room meters."""

    type: Literal["grip"]
    manipulation_id: int = Field(ge=1)
    sequence: int = Field(ge=1)
    position: Position
    orientation: Orientation


class PoseMessage(WireModel):
    type: Literal["pose"]
    sequence: int = Field(ge=1)
    tracking_status: TrackingStatus
    reference_space: ReferenceSpace | None
    position: Position | None
    heading: Heading | None = None
    pitch: Pitch | None = None

    @model_validator(mode="after")
    def check_position(self) -> Self:
        if self.tracking_status == "tracked":
            if self.position is None or self.reference_space is None:
                raise ValueError("Tracked input requires a position and reference space")
        elif self.position is not None or self.heading is not None or self.pitch is not None:
            raise ValueError("Unavailable tracking must not supply a usable position")
        return self


class PresenceMessage(WireModel):
    """One participant's place. This cannot move a room object."""

    type: Literal["presence"]
    sequence: int = Field(ge=1)
    tracking_status: Literal["inactive", "tracked", "lost"]
    position: Position | None
    heading: float | None = Field(ge=-math.pi, le=math.pi)

    @model_validator(mode="after")
    def check_presence(self) -> Self:
        if self.tracking_status == "tracked":
            if self.position is None or self.heading is None:
                raise ValueError("Tracked presence requires a position and heading")
        elif self.position is not None or self.heading is not None:
            raise ValueError("Unavailable presence must not supply a position or heading")
        return self
