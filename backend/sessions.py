"""One shared room for the connected phone and VR prototype."""

import asyncio
from dataclasses import dataclass, field
from typing import Any

from fastapi import WebSocket

from backend.protocol import MarkerState, PoseMessage, Role


@dataclass
class PrototypeRoom:
    sockets: dict[Role, WebSocket] = field(default_factory=lambda: dict[Role, WebSocket]())
    revision: int = 0
    marker: MarkerState = field(default_factory=MarkerState)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def snapshot(self) -> dict[str, Any]:
        return {
            "revision": self.revision,
            "mobile_connected": "mobile_master" in self.sockets,
            "vr_connected": "vr_solver" in self.sockets,
            "marker": self.marker.model_dump(),
        }

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
        if role == "mobile_master":
            self.marker = MarkerState(tracking_status="lost")
        self.revision += 1
