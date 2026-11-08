"""One shared room for the connected phone and VR prototype."""

import asyncio
import math
import time
from dataclasses import dataclass, field
from typing import Any, Literal

from fastapi import WebSocket

from backend.alignment import Alignment
from backend.delivery import Outbox
from backend.grab import grab_offset, grabbed_point, normalize
from backend.physics import PhysicsWorker
from backend.prepared_room import (
    FRAME,
    QUATERNION_ORDER,
    UNITS,
    RoomLandmark,
    RoomMap,
    Rotation,
    SceneEntity,
    SplatPlacement,
    floor_bounds,
)
from backend.protocol import (
    MarkerState,
    PoseMessage,
    Position,
    PresenceMessage,
    PresenceState,
    Role,
    Velocity,
)

# A tracked participant who stops sending is marked stale after this long. The last place stays.
PRESENCE_STALE_AFTER = 1.5

# A carried object sits where the screen's centre meets the floor, no nearer or further than this.
CARRY_NEAREST = 0.3
CARRY_FARTHEST = 4.0
# The physics status before the server has started its worker: a worker not yet started.
NO_PHYSICS = PhysicsWorker(lambda: None).status()


@dataclass
class Manipulation:
    """One hold. The phone aims across the floor; the headset keeps the object on its grip."""

    id: int
    entity: str
    owner: Role
    # The floor height the object rested at when the phone picked it up.
    rest_y: float
    # The pose or grip sequence of the latest movement applied, or None before the first.
    sequence: int | None = None
    # Box position in the headset grip's local frame. None for a phone hold.
    offset: tuple[float, float, float] | None = None


@dataclass
class PrototypeRoom:
    sockets: dict[Role, WebSocket] = field(default_factory=lambda: dict[Role, WebSocket]())
    # Each connected device's outbox, which shared state is published to.
    outboxes: dict[Role, Outbox] = field(default_factory=lambda: dict[Role, Outbox]())
    # Seconds every delivery is held back, to reproduce a slow network on purpose; 0 normally.
    delivery_delay: float = 0.0
    revision: int = 0
    marker: MarkerState = field(default_factory=MarkerState)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    entities: list[SceneEntity] = field(default_factory=lambda: list[SceneEntity]())
    room_version: int | None = None
    # The Gaussian splat drawn as the room's look, when the prepared room has one.
    splat_url: str | None = None
    # A lighter copy for phones, or None when phones draw the full one.
    splat_phone_url: str | None = None
    # The room seen from above (#124).
    map: RoomMap | None = None
    # Objects the phone can calibrate by (#120).
    landmarks: list[RoomLandmark] = field(default_factory=lambda: list[RoomLandmark]())
    splat_placement: SplatPlacement | None = None
    load_error: str | None = None
    loaded_versions: dict[Role, int | None] = field(
        default_factory=lambda: {"mobile_master": None, "vr_solver": None}
    )
    # The phone's private selection; it is never part of the shared snapshot.
    selection: str | None = None
    # The one hold in progress, shared with both devices; its id counts up across holds.
    manipulation: Manipulation | None = None
    manipulation_count: int = 0
    alignment: dict[Role, Alignment] = field(
        default_factory=lambda: {
            "mobile_master": Alignment(),
            "vr_solver": Alignment(),
        }
    )
    presence: dict[Role, PresenceState] = field(
        default_factory=lambda: {
            "mobile_master": PresenceState(),
            "vr_solver": PresenceState(),
        }
    )
    presence_seen: dict[Role, float] = field(default_factory=dict)
    # One timer per role, armed only while that person is tracked.
    presence_timers: dict[Role, asyncio.TimerHandle] = field(default_factory=dict)
    # The server's one physics simulation (#159), or None before the server has started it.
    physics: PhysicsWorker | None = None
    physics_tasks: set[asyncio.Task[None]] = field(
        default_factory=lambda: set[asyncio.Task[None]]()
    )

    def snapshot(self) -> dict[str, Any]:
        available = self.load_error is None and self.room_version is not None
        return {
            "revision": self.revision,
            "mobile_connected": "mobile_master" in self.sockets,
            "vr_connected": "vr_solver" in self.sockets,
            # Recorded with motion measurements, so each is read against its network conditions.
            "delivery": {"simulated_delay_ms": round(self.delivery_delay * 1000)},
            "marker": self.marker.model_dump(),
            "participants": {role: value.model_dump() for role, value in self.presence.items()},
            "alignment": {role: value.model_dump() for role, value in self.alignment.items()},
            "physics": NO_PHYSICS if self.physics is None else self.physics.status(),
            "manipulation": None
            if self.manipulation is None
            else {
                "id": self.manipulation.id,
                "entity": self.manipulation.entity,
                "owner": self.manipulation.owner,
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
                "splat_url": self.splat_url if available else None,
                "splat_phone_url": self.splat_phone_url if available else None,
                "landmarks": [mark.model_dump() for mark in self.landmarks] if available else [],
                "map": self.map.model_dump() if available and self.map else None,
                "splat_placement": self.splat_placement.model_dump()
                if available and self.splat_placement is not None
                else None,
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
                if self.physics is not None:
                    self.physics.place(entity)
                self.revision += 1
                return "ok"
        return "unknown"

    def accept_alignment(self, role: Role, yaw: float, origin: Position) -> str:
        if self.load_error is not None or self.room_version is None:
            return "unavailable"
        self.alignment[role] = Alignment(status="aligned", yaw=yaw, origin=origin)
        self.revision += 1
        return "ok"

    def clear_alignment(self, role: Role) -> None:
        """Drop a device's alignment after its reference space resets or its VR session ends."""
        self.alignment[role] = Alignment()
        self.revision += 1

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
        self,
        role: Role,
        room_version: int,
        entity_id: str,
        grip: tuple[Position, tuple[float, float, float, float]] | None = None,
    ) -> Literal[
        "ok",
        "unavailable",
        "mismatch",
        "not_selected",
        "not_tracked",
        "already_held",
        "controlled_by_other",
        "unknown",
        "not_selectable",
        "no_grip",
    ]:
        """The phone aims its selection. The headset grabs without moving the object."""
        if self.load_error is not None or self.room_version is None:
            return "unavailable"
        if room_version != self.room_version:
            return "mismatch"
        held = self.manipulation
        if held is not None:
            return "already_held" if held.owner == role else "controlled_by_other"
        if role == "vr_solver":
            return self.acquire_grip(entity_id, grip)
        if self.selection is None or entity_id != self.selection:
            return "not_selected"
        if self.marker.tracking_status != "tracked" or self.marker.position is None:
            return "not_tracked"
        self.manipulation_count += 1
        self.manipulation = Manipulation(
            id=self.manipulation_count,
            entity=entity_id,
            owner="mobile_master",
            rest_y=self.entity(entity_id).position.y,
        )
        if self.physics is not None:
            self.physics.hold(entity_id)
        self.carry()
        self.revision += 1
        return "ok"

    def acquire_grip(
        self,
        entity_id: str,
        grip: tuple[Position, tuple[float, float, float, float]] | None,
    ) -> Literal["ok", "unknown", "not_selectable", "no_grip"]:
        entity = next((entity for entity in self.entities if entity.id == entity_id), None)
        if entity is None:
            return "unknown"
        if entity.kind != "movable" or not entity.selectable:
            return "not_selectable"
        if grip is None:
            return "no_grip"
        orientation = normalize(grip[1])
        if orientation is None:
            return "no_grip"
        place = entity.position
        self.manipulation_count += 1
        self.manipulation = Manipulation(
            id=self.manipulation_count,
            entity=entity_id,
            owner="vr_solver",
            rest_y=place.y,
            offset=grab_offset(
                (grip[0].x, grip[0].y, grip[0].z),
                orientation,
                (place.x, place.y, place.z),
            ),
        )
        if self.physics is not None:
            self.physics.hold(entity_id)
        self.revision += 1
        return "ok"

    def accept_grip(
        self,
        role: Role,
        manipulation_id: int,
        sequence: int,
        position: Position,
        orientation: tuple[float, float, float, float],
    ) -> Literal["ok", "stale", "controlled_by_other", "no_grip"]:
        """Move the headset's object with its grip. Anyone else's grip is refused."""
        held = self.manipulation
        if held is None or held.id != manipulation_id:
            return "stale"
        if held.owner != role or held.offset is None:
            return "controlled_by_other"
        unit = normalize(orientation)
        if unit is None:
            return "no_grip"
        point = grabbed_point((position.x, position.y, position.z), unit, held.offset)

        def bounded(value: float) -> float:
            return max(-100, min(100, value))

        self.entity(held.entity).position = Position(
            x=bounded(point[0]), y=bounded(point[1]), z=bounded(point[2])
        )
        held.sequence = sequence
        self.revision += 1
        return "ok"

    def release(
        self,
        role: Role,
        manipulation_id: int,
        velocity: Velocity | None = None,
    ) -> Literal["ok", "stale", "controlled_by_other"]:
        """The holder lets go, throwing it if the headset sent its velocity (#162). The other
        person cannot end the hold or take the object."""
        if self.manipulation is None or self.manipulation.id != manipulation_id:
            return "stale"
        if self.manipulation.owner != role:
            return "controlled_by_other"
        self.drop(velocity)
        self.revision += 1
        return "ok"

    async def broadcast(self, exclude: WebSocket | None = None) -> None:
        """Hand the newest state to each device's outbox; no device waits on another's network."""
        state = self.snapshot()
        for outbox in list(self.outboxes.values()):
            if outbox.socket is not exclude:
                outbox.publish(state)

    def accept_presence(self, role: Role, presence: PresenceMessage) -> None:
        self.presence[role] = PresenceState(
            tracking_status=presence.tracking_status,
            position=presence.position,
            heading=presence.heading,
        )
        if presence.tracking_status == "tracked":
            self.presence_seen[role] = time.monotonic()
        else:
            self.presence_seen.pop(role, None)
        self.revision += 1
        self.arm_presence(role)

    def cancel_presence_timer(self, role: Role) -> None:
        pending = self.presence_timers.pop(role, None)
        if pending is not None:
            pending.cancel()

    def arm_presence(self, role: Role, delay: float = PRESENCE_STALE_AFTER) -> None:
        """Mark this person stale `delay` seconds after the sighting, without a polling task."""

        self.cancel_presence_timer(role)
        if self.presence[role].tracking_status != "tracked" or role not in self.presence_seen:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        seen = self.presence_seen[role]
        self.presence_timers[role] = loop.call_later(delay, self._presence_due, role, seen)

    def physics_changed(self) -> None:
        """The physics status changed: tell both devices, after anything in progress."""
        task = asyncio.get_running_loop().create_task(self._publish_physics())
        # The loop keeps only a weak reference to a task; hold it until it has run.
        self.physics_tasks.add(task)
        task.add_done_callback(self.physics_tasks.discard)

    def physics_moved(self, poses: list[dict[str, Any]]) -> None:
        """Physics moved some objects, or they came to rest: place them and tell both devices."""
        task = asyncio.get_running_loop().create_task(self._apply_physics(poses))
        self.physics_tasks.add(task)
        task.add_done_callback(self.physics_tasks.discard)

    async def _apply_physics(self, poses: list[dict[str, Any]]) -> None:
        async with self.lock:
            held = None if self.manipulation is None else self.manipulation.entity
            for pose in poses:
                if pose["id"] == held:
                    continue
                entity = next((entity for entity in self.entities if entity.id == pose["id"]), None)
                if entity is None:
                    continue
                entity.position = Position.model_validate(pose["position"])
                entity.rotation = Rotation.model_validate(pose["rotation"])
            self.revision += 1
            await self.broadcast()

    async def _publish_physics(self) -> None:
        async with self.lock:
            self.revision += 1
            await self.broadcast()

    def _presence_due(self, role: Role, seen: float) -> None:
        self.presence_timers.pop(role, None)
        asyncio.get_running_loop().create_task(self._apply_stale(role, seen))

    async def _apply_stale(self, role: Role, seen: float) -> None:
        async with self.lock:
            if self.presence_seen.get(role) != seen:
                return
            if self.expire_presence():
                await self.broadcast()
                return
            # The timer can land on the 1.5 s boundary, which is not stale yet.
            if self.presence[role].tracking_status == "tracked":
                self.arm_presence(role, 0.05)

    def expire_presence(self, now: float | None = None) -> bool:
        """Mark tracked participants stale when their last update is too old."""

        clock = time.monotonic() if now is None else now
        changed = False
        for role, seen in list(self.presence_seen.items()):
            current = self.presence[role]
            if current.tracking_status == "tracked" and clock - seen > PRESENCE_STALE_AFTER:
                current.tracking_status = "stale"
                changed = True
        if changed:
            self.revision += 1
        return changed

    def accept_pose(self, pose: PoseMessage) -> None:
        self.marker = MarkerState(
            tracking_status=pose.tracking_status,
            reference_space=pose.reference_space,
            position=pose.position,
            heading=pose.heading,
            pitch=pose.pitch,
        )
        held = self.manipulation
        # A phone pose moves only the phone's hold. The headset's object stays with its grip.
        if held is not None and held.owner == "mobile_master":
            if pose.position is None:
                self.drop()
            else:
                self.carry()
                held.sequence = pose.sequence
        self.revision += 1

    def entity(self, entity_id: str) -> SceneEntity:
        return next(entity for entity in self.entities if entity.id == entity_id)

    def carry(self) -> None:
        """
        Place the held object where the ray from the phone's screen centre meets the floor it
        rests on. Turning swings it around the phone; tilting slides it nearer or further.
        """
        held, phone = self.manipulation, self.marker.position
        if held is None or phone is None:
            return
        heading = self.marker.heading or 0.0
        pitch = self.marker.pitch or 0.0
        drop = phone.y - held.rest_y
        # Level, upward or a phone below the floor never meets it, so the object goes furthest.
        distance = drop / math.tan(-pitch) if pitch < 0 and drop > 0 else CARRY_FARTHEST
        distance = max(CARRY_NEAREST, min(CARRY_FARTHEST, distance))

        x = phone.x - math.sin(heading) * distance
        z = phone.z - math.cos(heading) * distance
        entity = self.entity(held.entity)
        bounds = floor_bounds(self.entities)
        if bounds is not None:
            # Aimed past the floor's edge, the object stays whole on the floor.
            margin = max(entity.size.width, entity.size.depth) / 2
            min_x, max_x, min_z, max_z = bounds
            x = max(min_x + margin, min(max_x - margin, x))
            z = max(min_z + margin, min(max_z - margin, z))

        def bounded(value: float) -> float:
            return max(-100, min(100, value))

        entity.position = Position(x=bounded(x), y=held.rest_y, z=bounded(z))

    def drop(self, velocity: Velocity | None = None) -> None:
        """End the hold. A phone aim falls back to its floor height; a headset grip lets go where
        it is, and the object falls there if physics runs (#161)."""
        held = self.manipulation
        if held is None:
            return
        entity = self.entity(held.entity)
        if held.owner == "mobile_master":
            entity.position = Position(x=entity.position.x, y=held.rest_y, z=entity.position.z)
            if self.physics is not None:
                self.physics.place(entity)
        elif self.physics is not None:
            self.physics.release(entity, velocity)
        self.manipulation = None

    def disconnect(self, role: Role) -> None:
        self.sockets.pop(role, None)
        self.loaded_versions[role] = None
        self.alignment[role] = Alignment()
        self.cancel_presence_timer(role)
        self.presence[role] = PresenceState(tracking_status="lost")
        self.presence_seen.pop(role, None)
        # The object stays at the last accepted place. The other person keeps their own hold.
        if self.manipulation is not None and self.manipulation.owner == role:
            self.drop()
        if role == "mobile_master":
            self.marker = MarkerState(tracking_status="lost")
            self.selection = None
        self.revision += 1
