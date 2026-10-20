"""One shared room for the connected phone and VR prototype."""

import asyncio
from dataclasses import dataclass, field
from typing import Any, Literal

from fastapi import WebSocket

from backend.alignment import Alignment
from backend.prepared_room import FRAME, QUATERNION_ORDER, UNITS, SceneEntity
from backend.protocol import MarkerState, PoseMessage, Position, Role


@dataclass
class Manipulation:
    """One hold: the object follows the owner's phone from where both were when it began."""

    id: int
    entity: str
    owner: Role
    phone_start: Position
    entity_start: Position
    # The pose sequence of the latest movement applied, or None before the first.
    sequence: int | None = None


@dataclass
class PrototypeRoom:
    sockets: dict[Role, WebSocket] = field(default_factory=lambda: dict[Role, WebSocket]())
    revision: int = 0
    marker: MarkerState = field(default_factory=MarkerState)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    entities: list[SceneEntity] = field(default_factory=lambda: list[SceneEntity]())
    room_version: int | None = None
    load_error: str | None = None
    loaded_versions: dict[Role, int | None] = field(
        default_factory=lambda: {"mobile_master": None, "vr_solver": None}
    )
    # The phone's private selection; it is never part of the shared snapshot.
    selection: str | None = None
    # The one hold in progress, shared with both devices; its id counts up across holds.
    manipulation: Manipulation | None = None
    manipulation_count: int = 0
    # How far the object moves for each meter the phone moves while held.
    gain: float = 1.0
    alignment: dict[Role, Alignment] = field(
        default_factory=lambda: {
            "mobile_master": Alignment(),
            "vr_solver": Alignment(),
        }
    )

    def snapshot(self) -> dict[str, Any]:
        available = self.load_error is None and self.room_version is not None
        return {
            "revision": self.revision,
            "mobile_connected": "mobile_master" in self.sockets,
            "vr_connected": "vr_solver" in self.sockets,
            "marker": self.marker.model_dump(),
            "alignment": {role: value.model_dump() for role, value in self.alignment.items()},
            "manipulation": None
            if self.manipulation is None
            else {
                "id": self.manipulation.id,
                "entity": self.manipulation.entity,
                "owner": self.manipulation.owner,
                "gain": self.gain,
                "sequence": self.manipulation.sequence,
            },
            "room": {
                "available": available,
                "room_version": self.room_version,
                "units": UNITS if available else None,
                "frame": FRAME if available else None,
                "quaternion_order": QUATERNION_ORDER if available else None,
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
                if self.manipulation is not None and self.manipulation.entity == entity_id:
                    return "controlled"
                entity.position = position
                self.revision += 1
                return "ok"
        return "unknown"

    def accept_alignment(self, role: Role, yaw: float, origin: Position) -> str:
        if self.load_error is not None or self.room_version is None:
            return "unavailable"
        self.alignment[role] = Alignment(status="aligned", yaw=yaw, origin=origin)
        self.revision += 1
        return "ok"

    def select(
        self, room_version: int, entity_id: str | None
    ) -> Literal["ok", "unavailable", "mismatch", "unknown", "not_selectable", "held"]:
        """Choose the phone's selection; anything but "ok" leaves the current one in place."""
        if self.load_error is not None or self.room_version is None:
            return "unavailable"
        if room_version != self.room_version:
            return "mismatch"
        if self.manipulation is not None:
            return "held"
        if entity_id is not None:
            entity = next((entity for entity in self.entities if entity.id == entity_id), None)
            if entity is None:
                return "unknown"
            if entity.kind != "movable" or not entity.selectable:
                return "not_selectable"
        self.selection = entity_id
        return "ok"

    def acquire(
        self, room_version: int, entity_id: str
    ) -> Literal["ok", "unavailable", "mismatch", "not_selected", "not_tracked", "already_held"]:
        """Start the phone's hold on its selected object, from where phone and object are now."""
        if self.load_error is not None or self.room_version is None:
            return "unavailable"
        if room_version != self.room_version:
            return "mismatch"
        if self.selection is None or entity_id != self.selection:
            return "not_selected"
        if self.marker.tracking_status != "tracked" or self.marker.position is None:
            return "not_tracked"
        if self.manipulation is not None:
            return "already_held"
        entity = next(entity for entity in self.entities if entity.id == entity_id)
        self.manipulation_count += 1
        self.manipulation = Manipulation(
            id=self.manipulation_count,
            entity=entity_id,
            owner="mobile_master",
            phone_start=self.marker.position,
            entity_start=entity.position,
        )
        self.revision += 1
        return "ok"

    def release(self, manipulation_id: int) -> Literal["ok", "stale"]:
        """End the current hold; the object stays where the hold left it."""
        if self.manipulation is None or self.manipulation.id != manipulation_id:
            return "stale"
        self.manipulation = None
        self.revision += 1
        return "ok"

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
        held = self.manipulation
        if held is not None and pose.position is None:
            # Without a phone position the hold has nothing to follow, so it ends in place.
            self.manipulation = None
        elif held is not None and pose.position is not None:
            phone, start, origin = pose.position, held.entity_start, held.phone_start

            def follow(entity_start: float, phone_now: float, phone_start: float) -> float:
                return max(-100, min(100, entity_start + self.gain * (phone_now - phone_start)))

            moved = Position(
                x=follow(start.x, phone.x, origin.x),
                # The object keeps its height: only movement across the floor carries it.
                y=start.y,
                z=follow(start.z, phone.z, origin.z),
            )
            for entity in self.entities:
                if entity.id == held.entity:
                    entity.position = moved
            held.sequence = pose.sequence
        self.revision += 1

    def disconnect(self, role: Role) -> None:
        self.sockets.pop(role, None)
        self.loaded_versions[role] = None
        self.alignment[role] = Alignment()
        if role == "mobile_master":
            self.marker = MarkerState(tracking_status="lost")
            self.selection = None
            self.manipulation = None
        self.revision += 1
