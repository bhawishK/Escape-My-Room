"""The shared prototype's WebSocket contract; phone positions are room-frame meters."""

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


class SelectMessage(WireModel):
    """The phone's private choice of the object it means to manipulate; a null id deselects."""

    type: Literal["select"]
    room_version: int = Field(ge=1)
    id: str | None = Field(max_length=64)


class AcquireMessage(WireModel):
    """The phone takes hold of its selected object, to carry it as the phone moves."""

    type: Literal["acquire"]
    room_version: int = Field(ge=1)
    id: str = Field(max_length=64)


class ReleaseMessage(WireModel):
    """The phone lets go of its hold; the object stays where the hold left it."""

    type: Literal["release"]
    manipulation_id: int = Field(ge=1)
    # "interrupted" when the phone let go without the person choosing to, such as on the page
    # being hidden, so the headset can tell that from a placement.
    reason: Literal["placed", "interrupted"] = "placed"


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
