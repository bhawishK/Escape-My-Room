"""Public request contract. Positions are meters in the sender's XR reference space."""

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

Role = Literal["mobile_master", "vr_solver"]
TrackingSource = Literal["webxr", "simulator"]
TrackingStatus = Literal["inactive", "tracked", "lost", "emulated", "simulated"]


class WireModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class JoinRequest(WireModel):
    role: Role
    tracking_source: TrackingSource = "webxr"


class Position(WireModel):
    x: float = Field(ge=-100, le=100)
    y: float = Field(ge=-100, le=100)
    z: float = Field(ge=-100, le=100)


class PoseMessage(WireModel):
    type: Literal["pose"]
    connection_generation: int = Field(ge=1)
    sequence: int = Field(ge=1)
    tracking_status: TrackingStatus
    reference_space: Literal["local", "local-floor"] | None
    position: Position | None

    @model_validator(mode="after")
    def check_position(self) -> Self:
        if self.tracking_status in ("tracked", "simulated"):
            if self.position is None or self.reference_space is None:
                raise ValueError("A usable pose requires position and reference space")
        elif self.position is not None:
            raise ValueError("Unavailable tracking must not supply a usable position")
        return self
