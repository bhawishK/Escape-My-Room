"""The box falls and settles when the headset lets go (#161); WebSocket seam, real Havok worker."""

import json
import math
import shutil
import time
from pathlib import Path

import pytest
from test_manipulation import box, open_socket, receive_until
from test_solver_grab import acquire, grip, owned_by
from websockets.exceptions import ConcurrencyError

ROOM = Path(__file__).resolve().parents[1] / "assets" / "prepared-room"


def rotation(state):
    return next(entity for entity in state["room"]["entities"] if entity["id"] == "box")["rotation"]


def ready(ws):
    """The box's resting place, from the first welcome or state once physics has the room."""
    state = receive_until(
        ws,
        lambda event: (
            event["type"] in ("welcome", "state")
            and event["state"]["physics"]["status"] == "running"
            and event["state"]["physics"]["room_version"] is not None
        ),
    )["state"]
    return box(state)


def let_go_from(ws, start, height):
    """Take the box from `start`, lift it so its bottom is `height` higher, and let go then."""
    ws.send(json.dumps(acquire(start)))
    held = receive_until(ws, lambda event: owned_by(event, "vr_solver"))["state"]
    identity = held["manipulation"]["id"]
    lifted = {"x": start["x"], "y": start["y"] + height, "z": start["z"]}
    ws.send(json.dumps(grip(1, lifted, identity)))
    receive_until(
        ws,
        lambda event: (
            owned_by(event, "vr_solver") and event["state"]["manipulation"]["sequence"] == 1
        ),
    )
    ws.send(json.dumps({"type": "release", "manipulation_id": identity}))
    return time.monotonic()


def until_rest(ws, timeout=6.0):
    """Every state from now until physics says nothing moves, with when each arrived."""
    seen = []
    deadline = time.monotonic() + timeout
    moved = False
    while time.monotonic() < deadline:
        event = json.loads(ws.recv(timeout=2))
        if event.get("type") != "state":
            continue
        state = event["state"]
        seen.append((time.monotonic(), state))
        moving = state["physics"]["moving"]
        moved = moved or bool(moving)
        if moved and not moving:
            return seen
    raise AssertionError("The box didn't come to rest.")


def quiet(ws, seconds):
    """True when no message arrives for `seconds`."""
    try:
        ws.recv(timeout=seconds)
    except TimeoutError:
        return True
    except ConcurrencyError:
        return False
    return False


def test_a_box_let_go_in_the_air_falls_and_settles_on_the_floor(start_service, tmp_path):
    with start_service(tmp_path) as url, open_socket(url, "vr_solver") as headset:
        start = ready(headset)
        released = let_go_from(headset, start, 1.0)
        states = until_rest(headset)

        landed = next(at for at, state in states if box(state)["y"] < start["y"] + 0.02)
        assert landed - released < 0.8
        final = states[-1][1]
        # Its bottom rests on the floor, where it started, the right way up or on another face.
        assert box(final)["y"] == pytest.approx(start["y"], abs=0.01)
        q = rotation(final)
        assert math.sqrt(q["x"] ** 2 + q["y"] ** 2 + q["z"] ** 2 + q["w"] ** 2) == pytest.approx(1)
        revisions = [state["revision"] for _, state in states]
        assert revisions == sorted(set(revisions))
        # About 30 states a second while it moved.
        moving = [at for at, state in states if state["physics"]["moving"]]
        rate = (len(moving) - 1) / (moving[-1] - moving[0])
        assert 15 < rate < 45
        assert quiet(headset, 0.6)


def test_a_rejoin_after_the_box_settles_shows_where_it_rests(start_service, tmp_path):
    with start_service(tmp_path) as url:
        with open_socket(url, "vr_solver") as headset:
            let_go_from(headset, ready(headset), 0.6)
            final = until_rest(headset)[-1][1]
        with open_socket(url, "mobile_master") as phone:
            welcome = json.loads(phone.recv(timeout=2))
            assert box(welcome["state"]) == box(final)
            assert rotation(welcome["state"]) == rotation(final)


def test_without_physics_a_box_let_go_stays_where_it_was_let_go(start_service, tmp_path):
    missing = tmp_path / "missing-worker.mjs"
    with (
        start_service(tmp_path / "data", ESCAPE_ROOM_PHYSICS_WORKER=str(missing)) as url,
        open_socket(url, "vr_solver") as headset,
    ):
        start = box(
            receive_until(
                headset,
                lambda event: (
                    event["type"] in ("welcome", "state")
                    and event["state"]["physics"]["status"] == "unavailable"
                ),
            )["state"]
        )
        let_go_from(headset, start, 1.0)
        released = receive_until(
            headset,
            lambda event: event.get("type") == "state" and not event["state"]["manipulation"],
        )["state"]
        assert box(released)["y"] == pytest.approx(start["y"] + 1.0)
        assert quiet(headset, 0.6)


def peak_after_first_landing(states, floor):
    """How high the box bounced after it first reached the floor."""
    heights = [box(state)["y"] - floor for _, state in states]
    first = next(index for index, height in enumerate(heights) if height < 0.02)
    return max(heights[first:])


def test_a_room_can_make_its_box_bouncier(start_service, tmp_path):
    room = tmp_path / "bouncy-room"
    shutil.copytree(ROOM, room)
    manifest = json.loads((room / "manifest.json").read_text(encoding="utf-8"))
    for entity in manifest["entities"]:
        if entity["id"] == "box":
            entity["physics"] = {"restitution": 0.9}
    (room / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    with start_service(tmp_path / "plain") as url, open_socket(url, "vr_solver") as headset:
        start = ready(headset)
        let_go_from(headset, start, 1.0)
        plain = peak_after_first_landing(until_rest(headset), start["y"])
    with (
        start_service(tmp_path / "bouncy", ESCAPE_ROOM_PREPARED_DIR=str(room)) as url,
        open_socket(url, "vr_solver") as headset,
    ):
        start = ready(headset)
        let_go_from(headset, start, 1.0)
        bouncy = peak_after_first_landing(until_rest(headset, timeout=12), start["y"])
    assert plain < 0.2
    assert bouncy > 0.4
