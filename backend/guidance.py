"""Exit guidance (#275, #281): the walkable route from the occupant to the exit the commander chose.

The headset chooses one of the room's exits (`backend/room_exits.py`). From then on the route runs
from the phone's latest position to that exit's anchor, round furniture and keeping clear of
anything on fire (`backend/route.py`), and is part of the shared state, so both devices draw the
same route. It is worked out again when the phone has moved, furniture has moved or a fire has
started or stopped, but no more often than REROUTE_SECONDS, except when a fire changes, which
can't wait. Within ARRIVED_METRES of the anchor the occupant is out, and the guidance ends there.
"""

import math
from collections.abc import Collection, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from backend.prepared_room import SceneEntity
from backend.room_exits import RoomExit
from backend.route import length, route, yaw_of

Point = tuple[float, float]

# Within this of the exit's anchor, on the floor, the occupant is out.
ARRIVED_METRES = 0.5
# The route is worked out again at most this often, as the phone or furniture moves.
REROUTE_SECONDS = 0.5
# A phone that has moved less than this keeps its route.
MOVED_METRES = 0.1

GuidanceStatus = Literal["waiting", "routing", "no_route", "arrived"]


def obstacles(entities: Sequence[SceneEntity], fires: Collection[str]) -> tuple[Any, ...]:
    """What the route depends on in the room, to tell when it has changed: each object's
    footprint, to the centimetre, and what is burning."""
    return (
        tuple(
            (
                e.id,
                round(e.position.x, 2),
                round(e.position.z, 2),
                round(e.size.width, 2),
                round(e.size.depth, 2),
                round(e.size.height, 2),
                round(yaw_of(e), 2),
            )
            for e in entities
        ),
        tuple(sorted(fires)),
    )


@dataclass
class Guidance:
    """The commander's chosen exit and the occupant's route to it."""

    exit: RoomExit
    status: GuidanceStatus = "waiting"
    route: list[Point] | None = None
    # Where the phone was, what was in the way and when, the last time the route was worked out.
    routed_from: Point | None = None
    routed_round: tuple[Any, ...] | None = field(default=None, repr=False)
    routed_at: float = -math.inf
    # When a change held back by REROUTE_SECONDS is due to be routed, so it isn't left waiting
    # for the next message if the phone then stands still.
    due: float | None = None

    def update(
        self,
        entities: Sequence[SceneEntity],
        fires: Collection[str],
        phone: Point | None,
        now: float,
    ) -> bool:
        """Work the route out again if it's due; whether anything the devices see changed."""
        if self.status == "arrived":
            return False
        if phone is None:
            # The occupant isn't seen: keep the last route, if any, until they are again.
            return False
        if math.dist(phone, self.exit.anchor) <= ARRIVED_METRES:
            self.status, self.route = "arrived", None
            return True
        room = obstacles(entities, fires)
        first = self.routed_from is None
        fire_changed = self.routed_round is not None and room[1] != self.routed_round[1]
        moved = first or math.dist(phone, self.routed_from or phone) >= MOVED_METRES
        self.due = None
        if not (first or fire_changed):
            if room == self.routed_round and not moved:
                return False
            if now - self.routed_at < REROUTE_SECONDS:
                self.due = self.routed_at + REROUTE_SECONDS
                return False
        way = route(entities, phone, self.exit.anchor, fires)
        self.routed_from, self.routed_round, self.routed_at = phone, room, now
        before = (self.status, self.route)
        self.status, self.route = ("routing", way) if way else ("no_route", None)
        return (self.status, self.route) != before

    def wire(self) -> dict[str, Any]:
        return {
            "exit": self.exit.id,
            "status": self.status,
            "route": None if self.route is None else [list(point) for point in self.route],
            "length": None if self.route is None else round(length(self.route), 2),
        }
