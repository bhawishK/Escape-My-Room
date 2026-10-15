"""One shared room for the connected phone and VR prototype."""

import asyncio
from dataclasses import dataclass, field
from typing import Any

from fastapi import WebSocket

from backend.prepared_room import RoomEntity
from backend.protocol import MarkerState, PoseMessage, Position, Role


@dataclass
class PrototypeRoom:
    sockets: dict[Role, WebSocket] = field(default_factory=lambda: dict[Role, WebSocket]())
    revision: int = 0
    marker: MarkerState = field(default_factory=MarkerState)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    entities: list[RoomEntity] = field(default_factory=list)
    room_version: int | None = None
    units: str | None = None
    asset_url: str | None = None
    load_error: str | None = None
    loaded_versions: dict[Role, int | None] = field(
        default_factory=lambda: {"mobile_master": None, "vr_solver": None}
    )

    def snapshot(self) -> dict[str, Any]:
        available = self.load_error is None and self.room_version is not None
        return {
            "revision": self.revision,
            "mobile_connected": "mobile_master" in self.sockets,
            "vr_connected": "vr_solver" in self.sockets,
            "marker": self.marker.model_dump(),
            "room": {
                "available": available,
                "room_version": self.room_version,
                "units": self.units,
                "asset_url": self.asset_url,
                "error": self.load_error,
                "entities": [entity.model_dump() for entity in self.entities],
                "loaded_by": dict(self.loaded_versions),
            },
        }

    def accept_room_version(self, role: Role, version: int) -> str:
        if self.load_error is not None or self.room_version is None:
            return "unavailable"
        if version != self.room_version:
            return "mismatch"
        self.loaded_versions[role] = version
        self.revision += 1
        return "ok"

    def move_entity(self, entity_id: str, position: Position) -> str:
        if self.load_error is not None or self.room_version is None:
            return "unavailable"
        for entity in self.entities:
            if entity.id == entity_id:
                if entity.kind != "movable":
                    return "static"
                entity.position = position
                self.revision += 1
                return "ok"
        return "unknown"

    async def broadcast(self, exclude: WebSocket | None = None) -> None:
        event = {"type": "state", "state": self.snapshot()}
        for socket in list(self.sockets.values()):
            if socket is not exclude:
                try:
                    await asyncio.wait_for(socket.send_json(event), timeout=2)
                except (RuntimeError, OSError, TimeoutError):
                    # The socket endpoint owns disconnect cleanup.
                    continue

    def accept_pose(self, pose: PoseMessage) -> None:
        self.marker = MarkerState(
            tracking_status=pose.tracking_status,
            reference_space=pose.reference_space,
            position=pose.position,
        )
        self.revision += 1

    def disconnect(self, role: Role) -> None:
        self.sockets.pop(role, None)
        self.loaded_versions[role] = None
        if role == "mobile_master":
            self.marker = MarkerState(tracking_status="lost")
        self.revision += 1
