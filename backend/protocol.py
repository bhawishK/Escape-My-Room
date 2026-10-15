"""The shared prototype's WebSocket contract; positions are XR meters."""

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

Role = Literal["mobile_master", "vr_solver"]
TrackingStatus = Literal["inactive", "tracked", "lost", "emulated"]
ReferenceSpace = Literal["local", "local-floor"]


class WireModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class Position(WireModel):
    x: float = Field(ge=-100, le=100)
    y: float = Field(ge=-100, le=100)
    z: float = Field(ge=-100, le=100)


class MarkerState(WireModel):
    tracking_status: TrackingStatus = "inactive"
    reference_space: ReferenceSpace | None = None
    position: Position | None = None


class RoomLoadedMessage(WireModel):
    type: Literal["room_loaded"]
    room_version: int = Field(ge=1)


class EntityTransformMessage(WireModel):
    type: Literal["entity_transform"]
    id: str = Field(pattern=r"^[a-z][a-z0-9_]{0,31}$")
    position: Position


class PoseMessage(WireModel):
    type: Literal["pose"]
    sequence: int = Field(ge=1)
    tracking_status: TrackingStatus
    reference_space: ReferenceSpace | None
    position: Position | None

    @model_validator(mode="after")
    def check_position(self) -> Self:
        if self.tracking_status == "tracked":
            if self.position is None or self.reference_space is None:
                raise ValueError("Tracked input requires a position and reference space")
        elif self.position is not None:
            raise ValueError("Unavailable tracking must not supply a usable position")
        return self
