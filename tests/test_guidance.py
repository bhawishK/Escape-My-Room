"""Exit guidance (#281): the headset chooses an exit, and Python keeps the occupant's route to it,
round furniture and the fire, in the shared state. Unit and WebSocket seams."""

import json
import math
from pathlib import Path

import pytest
from test_route import BED, FLOOR, crosses, entity
from test_session_flow import open_socket, receive_until

from backend.guidance import ARRIVED_METRES, REROUTE_SECONDS, Guidance
from backend.room_exits import RoomExit
from backend.route import FIRE_CLEARANCE, ROUTE_CELL

SPLAT_ROOM = Path(__file__).resolve().parents[1] / "assets" / "splat-room"

# The 4 x 3 m room of test_route, with a door in the middle of its +z wall, behind the bed.
DOOR = RoomExit(
    id="door_0",
    kind="door",
    centre=(0.0, 1.0, 1.5),
    width=0.9,
    height=2.0,
    outward=(0.0, 1.0),
    anchor=(0.0, 1.1),
)
ROOM = [FLOOR, BED]
# The occupant stands in front of the bed, on the far side from the door.
START = (-1.0, -1.0)


def test_the_route_goes_round_the_bed_to_the_door():
    guidance = Guidance(exit=DOOR)
    assert guidance.update(ROOM, set(), START, now=0.0)
    wire = guidance.wire()
    assert wire["exit"] == "door_0" and wire["status"] == "routing"
    assert wire["route"][0] == list(START) and wire["route"][-1] == [0.0, 1.1]
    assert not crosses(guidance.route, BED)
    assert wire["length"] > 2.5


def test_until_the_occupant_is_seen_there_is_no_route():
    guidance = Guidance(exit=DOOR)
    assert not guidance.update(ROOM, set(), None, now=0.0)
    assert guidance.wire() == {"exit": "door_0", "status": "waiting", "route": None, "length": None}


def test_a_small_step_keeps_the_route_and_a_real_move_soon_after_waits():
    guidance = Guidance(exit=DOOR)
    guidance.update(ROOM, set(), START, now=0.0)
    first = guidance.route
    assert not guidance.update(ROOM, set(), (-0.97, -1.0), now=5.0)
    assert not guidance.update(ROOM, set(), (1.5, -1.0), now=0.1)
    assert guidance.route == first
    assert guidance.update(ROOM, set(), (1.5, -1.0), now=REROUTE_SECONDS)
    assert guidance.route is not None and guidance.route[0] == (1.5, -1.0)


def test_a_fire_starting_reroutes_at_once_and_keeps_clear_of_it():
    # A 6 x 4 m room with a desk in its middle, between the occupant and a door on its +x wall.
    floor = entity("floor", 0.0, 0.0, 6.0, 4.0, 0.02)
    desk = entity("layout_desk_1", 0.0, 0.0, 0.4, 0.4)
    door = DOOR.model_copy(update={"anchor": (2.5, 0.0)})
    guidance = Guidance(exit=door)
    guidance.update([floor, desk], set(), (-2.5, 0.0), now=0.0)
    calm = guidance.route
    assert guidance.update([floor, desk], {"layout_desk_1"}, (-2.5, 0.0), now=0.01)
    assert guidance.route is not None and guidance.route != calm

    def nearest(route):
        """How near the route comes to the desk's footprint."""
        gaps = []
        for (ax, az), (bx, bz) in zip(route, route[1:], strict=False):
            for i in range(101):
                x, z = ax + (bx - ax) * i / 100, az + (bz - az) * i / 100
                gaps.append(math.hypot(max(abs(x) - 0.2, 0.0), max(abs(z) - 0.2, 0.0)))
        return min(gaps)

    assert nearest(calm) < FIRE_CLEARANCE - ROUTE_CELL
    assert nearest(guidance.route) >= FIRE_CLEARANCE - ROUTE_CELL


def test_with_no_way_through_it_says_so():
    wall = entity("layout_wardrobe_1", 0.0, 0.5, 4.0, 0.4, 2.0)
    guidance = Guidance(exit=DOOR)
    assert guidance.update([FLOOR, wall], set(), START, now=0.0)
    assert guidance.wire()["status"] == "no_route" and guidance.wire()["route"] is None


def test_near_the_exit_the_occupant_is_out_and_it_stays_so():
    guidance = Guidance(exit=DOOR)
    guidance.update(ROOM, set(), START, now=0.0)
    assert guidance.update(ROOM, set(), (0.0, 1.1 - ARRIVED_METRES + 0.05), now=1.0)
    assert guidance.wire()["status"] == "arrived" and guidance.wire()["route"] is None
    assert not guidance.update(ROOM, set(), START, now=2.0)
    assert guidance.wire()["status"] == "arrived"


def guidance_of(event):
    return event.get("state", {}).get("room", {}).get("guidance")


def room_version(socket):
    return receive_until(socket, lambda event: "state" in event)["state"]["room"]["room_version"]


def presence(socket, sequence, x, z):
    socket.send(
        json.dumps(
            {
                "type": "presence",
                "sequence": sequence,
                "tracking_status": "tracked",
                "position": {"x": x, "y": 1.4, "z": z},
                "heading": 0.0,
            }
        )
    )


def choose(socket, version, exit_id):
    socket.send(json.dumps({"type": "guide_exit", "room_version": version, "exit": exit_id}))


@pytest.fixture
def splat_room_url(start_service, tmp_path):
    with start_service(tmp_path / "data", ESCAPE_ROOM_PREPARED_DIR=str(SPLAT_ROOM)) as url:
        yield url


def test_choosing_an_exit_gives_both_devices_the_same_route_which_follows_the_phone(splat_room_url):
    with (
        open_socket(splat_room_url, "mobile_master") as phone,
        open_socket(splat_room_url, "vr_solver") as headset,
    ):
        version = room_version(headset)
        assert guidance_of(receive_until(phone, lambda e: "state" in e)) is None
        presence(phone, 1, -1.0, -1.0)
        choose(headset, version, "door_0")
        seen = [
            guidance_of(
                receive_until(s, lambda e: (guidance_of(e) or {}).get("status") == "routing")
            )
            for s in (phone, headset)
        ]
        assert seen[0] == seen[1]
        assert seen[0]["exit"] == "door_0"
        assert seen[0]["route"][0] == [-1.0, -1.0] and seen[0]["route"][-1] == [0.9, 0.0]
        # The phone walks to the door: its route starts from where it is, then it's out.
        presence(phone, 2, 0.2, -0.5)
        moved = receive_until(
            headset, lambda e: ((guidance_of(e) or {}).get("route") or [[None]])[0] == [0.2, -0.5]
        )
        assert guidance_of(moved)["status"] == "routing"
        presence(phone, 3, 0.8, 0.1)
        receive_until(phone, lambda e: (guidance_of(e) or {}).get("status") == "arrived")
        # Stopping guidance clears it for both.
        choose(headset, version, None)
        receive_until(phone, lambda e: "state" in e and guidance_of(e) is None)


def test_only_the_headset_chooses_and_only_the_room_s_exits(splat_room_url):
    with (
        open_socket(splat_room_url, "mobile_master") as phone,
        open_socket(splat_room_url, "vr_solver") as headset,
    ):
        version = room_version(headset)
        choose(phone, version, "door_0")
        assert receive_until(phone, lambda e: e.get("type") == "error")["code"] == "role_forbidden"
        choose(headset, version, "door_9")
        assert receive_until(headset, lambda e: e.get("type") == "error")["code"] == "unknown_exit"
        choose(headset, version + 1, "door_0")
        assert (
            receive_until(headset, lambda e: e.get("type") == "error")["code"]
            == "room_version_mismatch"
        )


def test_a_move_held_back_is_routed_once_due_even_if_the_phone_then_stands_still(splat_room_url):
    with (
        open_socket(splat_room_url, "mobile_master") as phone,
        open_socket(splat_room_url, "vr_solver") as headset,
    ):
        version = room_version(headset)
        presence(phone, 1, -1.0, -1.0)
        choose(headset, version, "door_0")
        receive_until(headset, lambda e: (guidance_of(e) or {}).get("status") == "routing")
        # At once after the first route, so it's held back; nothing else is sent after it.
        presence(phone, 2, -0.5, 0.6)
        receive_until(
            headset, lambda e: ((guidance_of(e) or {}).get("route") or [[None]])[0] == [-0.5, 0.6]
        )
