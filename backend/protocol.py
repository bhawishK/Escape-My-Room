"""Public request contract. Positions are meters in the sender's XR reference space."""

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

Role = Literal["mobile_master", "vr_solver"]
TrackingSource = Literal["webxr", "simulator"]
TrackingStatus = Literal["inactive", "tracked", "lost", "emulated", "simulated"]
ReferenceSpace = Literal["local", "local-floor"]


class WireModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class JoinRequest(WireModel):
    role: Role
    tracking_source: TrackingSource = "webxr"


class ReleaseRequest(WireModel):
    connection_token: str = Field(min_length=1, max_length=128)


class Position(WireModel):
    x: float = Field(ge=-100, le=100)
    y: float = Field(ge=-100, le=100)
    z: float = Field(ge=-100, le=100)


class MarkerState(WireModel):
    participant_id: str | None = None
    source: TrackingSource | None = None
    tracking_status: TrackingStatus = "inactive"
    reference_space: ReferenceSpace | None = None
    position: Position | None = None


class PoseMessage(WireModel):
    type: Literal["pose"]
    connection_generation: int = Field(ge=1)
    sequence: int = Field(ge=1)
    tracking_status: TrackingStatus
    reference_space: ReferenceSpace | None
    position: Position | None

    @model_validator(mode="after")
    def check_position(self) -> Self:
        if self.tracking_status in ("tracked", "simulated"):
            if self.position is None or self.reference_space is None:
                raise ValueError("A usable pose requires position and reference space")
        elif self.position is not None:
            raise ValueError("Unavailable tracking must not supply a usable position")
        return self
