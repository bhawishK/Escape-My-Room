"""One shared room for the connected phone and VR prototype."""

import asyncio
import math
import time
from collections.abc import Coroutine
from dataclasses import dataclass, field
from typing import Any, Literal

from fastapi import WebSocket

from backend.alignment import Alignment
from backend.delivery import Outbox
from backend.furniture import (
    CatalogueItem,
    free_spot,
    furniture_entity,
    on_floor,
    overlapping,
)
from backend.grab import grab_offset, grabbed_point, normalize
from backend.hazard_generation import HazardAsset
from backend.physics import PhysicsWorker
from backend.prepared_room import (
    FRAME,
    QUATERNION_ORDER,
    UNITS,
    EntitySize,
    RoomLandmark,
    RoomMap,
    Rotation,
    SceneEntity,
    SplatPlacement,
    floor_bounds,
    floor_top,
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

# A room holds at most this many placed pieces (#181), so a stuck client can't fill it without end.
MAX_FURNITURE = 24
# Hazards in the room at once (#229), and how far ahead of the asking a start is set, so both
# devices have the first frames before it plays.
MAX_HAZARDS = 4
HAZARD_START_LEAD_SECONDS = 1.0


@dataclass
class SessionHazard:
    """A finished hazard in the room (#229): its frames, where they go and the object they hide,
    and, while it plays, when it started (milliseconds on the server's clock)."""

    id: str
    asset: HazardAsset
    started_at: float | None = None

    def wire(self) -> dict[str, Any]:
        asset = self.asset
        placement = asset.placement
        return {
            "id": self.id,
            "asset": asset.id,
            "hazard": asset.hazard,
            "frames": asset.frames,
            "frames_per_second": asset.frames_per_second,
            "frame_url": asset.frame_url,
            "seconds": asset.seconds,
            "loops": asset.loops,
            "placement": placement.model_dump() if placement is not None else None,
            "hide": placement.hide if placement is not None else None,
            "playing": self.started_at is not None,
            "started_at": self.started_at,
        }


# A placed piece is resized to between these times its catalogue size (#202).
SMALLEST_SCALE = 0.25
LARGEST_SCALE = 3.0

# A carried object sits where the screen's centre meets the floor, no nearer or further than this.
CARRY_NEAREST = 0.3
CARRY_FARTHEST = 4.0
# An object physics has this far below the floor got out of the room and is put back (#213).
FALLEN_BELOW = 1.0
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


def in_room(
    entity: SceneEntity,
    where: tuple[float, float, float],
    entities: list[SceneEntity],
    floor_level: bool = True,
) -> Position:
    """`where` for the entity's bottom centre, kept in the room: whole on the floor's rectangle
    and, with `floor_level`, no lower than its top. Any place for a room without a floor, within
    the protocol's ±100 m."""
    x, y, z = where
    bounds = floor_bounds(entities)
    if bounds is not None:
        margin = max(entity.size.width, entity.size.depth) / 2
        min_x, max_x, min_z, max_z = bounds
        x = max(min_x + margin, min(max_x - margin, x))
        z = max(min_z + margin, min(max_z - margin, z))
    floor = floor_top(entities) if floor_level else None
    if floor is not None:
        y = max(floor, y)

    def bounded(value: float) -> float:
        return max(-100, min(100, value))

    return Position(x=bounded(x), y=bounded(y), z=bounded(z))


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
    # Placed furniture is numbered furniture_1, furniture_2, ... and a number is never reused.
    furniture_count: int = 0
    # Counts pieces added to the catalogue, so pages reload it when one is made (#187).
    catalogue_version: int = 0
    # Hazards in the room (#229), numbered hazard_1, hazard_2, ... never reused.
    hazards: list[SessionHazard] = field(default_factory=lambda: list[SessionHazard]())
    hazard_count: int = 0
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
    # Who has a microphone open for the voice call (#13). Never touches an object or a hold.
    voice_ready: dict[Role, bool] = field(
        default_factory=lambda: {"mobile_master": False, "vr_solver": False}
    )
    # Who has muted their microphone while staying in the call. Starting voice starts unmuted.
    voice_muted: dict[Role, bool] = field(
        default_factory=lambda: {"mobile_master": False, "vr_solver": False}
    )
    # Counts each time a role becomes ready. Devices are sent only the newest state, so a quick
    # stop and start can pass unseen; a new number tells the other device to set the call up again.
    voice_sessions: dict[Role, int] = field(
        default_factory=lambda: {"mobile_master": 0, "vr_solver": 0}
    )
    # Work started from callbacks, held until it has run: physics news, catalogue news.
    background_tasks: set[asyncio.Task[None]] = field(
        default_factory=lambda: set[asyncio.Task[None]]()
    )

    def snapshot(self) -> dict[str, Any]:
        available = self.load_error is None and self.room_version is not None
        return {
            "revision": self.revision,
            # The server's clock when this state was made, for devices to set theirs against it
            # (a hazard's start time is on it, #229).
            "server_time_ms": round(time.time() * 1000),
            "mobile_connected": "mobile_master" in self.sockets,
            "catalogue_version": self.catalogue_version,
            "vr_connected": "vr_solver" in self.sockets,
            # Recorded with motion measurements, so each is read against its network conditions.
            "delivery": {"simulated_delay_ms": round(self.delivery_delay * 1000)},
            "marker": self.marker.model_dump(),
            "participants": {role: value.model_dump() for role, value in self.presence.items()},
            "alignment": {role: value.model_dump() for role, value in self.alignment.items()},
            "physics": NO_PHYSICS if self.physics is None else self.physics.status(),
            "voice": {
                role: {
                    "ready": ready,
                    "session": self.voice_sessions[role],
                    "muted": self.voice_muted[role],
                }
                for role, ready in self.voice_ready.items()
            },
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
                "hazards": [hazard.wire() for hazard in self.hazards] if available else [],
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

    def add_furniture(
        self, room_version: int, item: CatalogueItem | None, position: Position, yaw: float
    ) -> str:
        """Place a catalogue piece (#181). It starts no lower than the floor, and physics drops
        it there from higher up."""
        if self.load_error is not None or self.room_version is None:
            return "unavailable"
        if room_version != self.room_version:
            return "mismatch"
        if item is None:
            return "unknown_item"
        if sum(1 for entity in self.entities if entity.furniture) >= MAX_FURNITURE:
            return "too_many"
        start = on_floor(self.entities, position, item.size, yaw)
        if start is None:
            return "outside"
        entity = furniture_entity(f"furniture_{self.furniture_count + 1}", item, start, yaw)
        # Placed on another piece, it goes beside it instead of being shoved out by physics.
        spot = free_spot(entity, start, self.entities)
        if spot is None:
            return "no_room"
        self.furniture_count += 1
        entity.position = spot
        self.entities.append(entity)
        if self.physics is not None:
            self.physics.add(entity)
        self.revision += 1
        return "ok"

    def resize_furniture(
        self, role: Role, room_version: int, entity_id: str, scale: float, final: bool
    ) -> str:
        """Resize a placed piece evenly to `scale` times its catalogue size (#202), standing where
        it stands. Physics gets it at its new size. When the resize ends, a piece grown into
        another is put beside it, as a drop is. A piece the other person holds stays as it is."""
        if self.load_error is not None or self.room_version is None:
            return "unavailable"
        if room_version != self.room_version:
            return "mismatch"
        entity = next((entity for entity in self.entities if entity.id == entity_id), None)
        if entity is None:
            return "unknown"
        if not entity.furniture:
            return "not_furniture"
        held = self.manipulation
        if held is not None and held.entity == entity_id and held.owner != role:
            return "controlled_by_other"
        scale = max(SMALLEST_SCALE, min(LARGEST_SCALE, scale))
        change = scale / entity.scale
        size = entity.size
        entity.size = EntitySize(
            width=size.width * change, height=size.height * change, depth=size.depth * change
        )
        entity.scale = scale
        if final and overlapping(entity, entity.position, self.entities):
            spot = free_spot(entity, entity.position, self.entities)
            if spot is not None:
                entity.position = spot
        if self.physics is not None:
            # A body's size is fixed, so it is taken out and put back at the new size.
            self.physics.remove(entity_id)
            self.physics.add(entity)
            if held is not None and held.entity == entity_id:
                self.physics.hold(entity_id)
        self.revision += 1
        return "ok"

    def remove_furniture(self, role: Role, room_version: int, entity_id: str) -> str:
        """Take a placed piece away (#183): from the room, the phone's selection and physics. A
        piece the other person holds stays; one this person holds is let go of and taken."""
        if self.load_error is not None or self.room_version is None:
            return "unavailable"
        if room_version != self.room_version:
            return "mismatch"
        entity = next((entity for entity in self.entities if entity.id == entity_id), None)
        if entity is None:
            return "unknown"
        if not entity.furniture:
            return "not_furniture"
        held = self.manipulation
        if held is not None and held.entity == entity_id:
            if held.owner != role:
                return "controlled_by_other"
            self.manipulation = None
        if self.selection == entity_id:
            self.selection = None
        self.entities.remove(entity)
        if self.physics is not None:
            self.physics.remove(entity_id)
        self.revision += 1
        return "ok"

    def add_hazard(self, room_version: int, asset: HazardAsset | None) -> str:
        """Put a finished hazard into the room, stopped (#229)."""
        if self.load_error is not None or self.room_version is None:
            return "unavailable"
        if room_version != self.room_version:
            return "mismatch"
        if asset is None or asset.placement is None:
            return "unknown"
        if len(self.hazards) >= MAX_HAZARDS:
            return "too_many"
        self.hazard_count += 1
        self.hazards.append(SessionHazard(id=f"hazard_{self.hazard_count}", asset=asset))
        self.revision += 1
        return "ok"

    def control_hazard(
        self,
        room_version: int,
        hazard_id: str,
        action: Literal["start_hazard", "stop_hazard", "remove_hazard"],
        now_ms: float | None = None,
    ) -> str:
        """Start a hazard a moment ahead on the server's clock, the same for both devices; stop
        it; or take it away (#229)."""
        if self.load_error is not None or self.room_version is None:
            return "unavailable"
        if room_version != self.room_version:
            return "mismatch"
        hazard = next((hazard for hazard in self.hazards if hazard.id == hazard_id), None)
        if hazard is None:
            return "unknown"
        if action == "start_hazard":
            now = time.time() * 1000 if now_ms is None else now_ms
            hazard.started_at = round(now + HAZARD_START_LEAD_SECONDS * 1000)
        elif action == "stop_hazard":
            hazard.started_at = None
        else:
            self.hazards.remove(hazard)
        self.revision += 1
        return "ok"

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

    def set_voice_ready(self, role: Role, ready: bool) -> bool:
        """Record whether a device is ready to talk. Returns whether anything changed."""
        if self.voice_ready[role] == ready:
            return False
        self.voice_ready[role] = ready
        self.voice_muted[role] = False
        if ready:
            self.voice_sessions[role] += 1
        self.revision += 1
        return True

    def stop_voice(self, role: Role) -> None:
        """A device that left, or was replaced by a new page, has no microphone open."""
        self.voice_ready[role] = False
        self.voice_muted[role] = False

    def set_voice_muted(self, role: Role, muted: bool) -> str:
        """Record a mute. Only a device that has started voice has a microphone to mute."""
        if not self.voice_ready[role]:
            return "not_ready"
        if self.voice_muted[role] != muted:
            self.voice_muted[role] = muted
            self.revision += 1
        return "ok"

    def voice_refusal(self, role: Role) -> str | None:
        """Why a call set-up message from this role can't be passed on, or None when it can."""
        other: Role = "vr_solver" if role == "mobile_master" else "mobile_master"
        if not self.voice_ready[role]:
            return "not_ready"
        if other not in self.outboxes:
            return "peer_gone"
        if not self.voice_ready[other]:
            return "peer_not_ready"
        return None

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
            rest_y=self.carry_height(entity_id),
        )
        if self.physics is not None:
            self.physics.hold(entity_id)
        self.carry()
        self.revision += 1
        return "ok"

    def carry_height(self, entity_id: str) -> float:
        """The height the phone carries an object at: where it rests, or the floor's height if
        physics is moving it, as when the phone catches a falling object (#163). The phone carries
        on the floor, so a box caught as it falls toward a raised surface is carried on the floor
        too. Read before the hold, which takes the object out of physics' moving list."""
        resting = self.entity(entity_id).position.y
        if self.physics is None or not self.physics.is_moving(entity_id):
            return resting
        floor = floor_top(self.entities)
        return resting if floor is None else floor

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

    def track(self, work: Coroutine[Any, Any, None]) -> None:
        """Run `work` on the event loop, held until it has run: the loop keeps only a weak
        reference to a task."""
        task = asyncio.get_running_loop().create_task(work)
        self.background_tasks.add(task)
        task.add_done_callback(self.background_tasks.discard)

    def physics_changed(self) -> None:
        """The physics status changed: tell both devices, after anything in progress."""
        self.track(self._publish_physics())

    def physics_moved(self, poses: list[dict[str, Any]]) -> None:
        """Physics moved some objects, or they came to rest: place them and tell both devices."""
        self.track(self._apply_physics(poses))

    async def _apply_physics(self, poses: list[dict[str, Any]]) -> None:
        async with self.lock:
            held = None if self.manipulation is None else self.manipulation.entity
            for pose in poses:
                if pose["id"] == held:
                    continue
                entity = next((entity for entity in self.entities if entity.id == pose["id"]), None)
                if entity is None:
                    continue
                entity.rotation = Rotation.model_validate(pose["rotation"])
                where = pose["position"]
                entity.position = in_room(
                    entity, (where["x"], where["y"], where["z"]), [], floor_level=False
                )
                floor = floor_top(self.entities)
                if floor is not None and where["y"] < floor - FALLEN_BELOW:
                    # It got out of the room and fell (#213): back on the floor where it left.
                    entity.position = in_room(
                        entity, (where["x"], floor, where["z"]), self.entities
                    )
                    spot = free_spot(entity, entity.position, self.entities)
                    if spot is not None:
                        entity.position = spot
                    if self.physics is not None:
                        self.physics.place(entity)
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
        # Aimed past the floor's edge, the object stays whole on the floor.
        entity.position = in_room(entity, (x, held.rest_y, z), self.entities, floor_level=False)

    def drop(self, velocity: Velocity | None = None) -> None:
        """End the hold. A phone aim falls back to its floor height; a headset grip lets go where
        it is, and the object falls there if physics runs (#161)."""
        held = self.manipulation
        if held is None:
            return
        entity = self.entity(held.entity)
        if held.owner == "mobile_master":
            entity.position = Position(x=entity.position.x, y=held.rest_y, z=entity.position.z)
        else:
            # Physics' walls stop only what it moves, so a held piece can be carried through them
            # or under the floor; let go there, it would fall forever (#213).
            where = entity.position
            entity.position = in_room(entity, (where.x, where.y, where.z), self.entities)
        # Let go inside another piece, it is put beside it rather than shoved out by physics (#183).
        if overlapping(entity, entity.position, self.entities):
            spot = free_spot(entity, entity.position, self.entities)
            if spot is not None:
                entity.position = spot
        if held.owner == "mobile_master":
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
        self.stop_voice(role)
        # The object stays at the last accepted place. The other person keeps their own hold.
        if self.manipulation is not None and self.manipulation.owner == role:
            self.drop()
        if role == "mobile_master":
            self.marker = MarkerState(tracking_status="lost")
            self.selection = None
        self.revision += 1
