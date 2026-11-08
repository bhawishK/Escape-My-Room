"""The headset throws the box (#162); WebSocket seam, real Havok worker."""

import json
import math

import pytest
from test_manipulation import box, error_code, open_socket, receive_until
from test_physics_fall import ready, rotation, until_rest
from test_solver_grab import acquire, grip, owned_by

GRAVITY = 9.81
# The prepared room's floor is 4 m square around the origin; the box is 0.2 m.
FLOOR_EDGE = 2.0
HALF_BOX = 0.1


def lift(ws, start, height):
    """Take the box from `start` and hold it `height` higher. Returns the hold's id."""
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
    return identity


def throw(ws, identity, velocity, angular_velocity=None):
    message = {"type": "release", "manipulation_id": identity, "velocity": velocity}
    if angular_velocity is not None:
        message["angular_velocity"] = angular_velocity
    ws.send(json.dumps(message))


def centre_height(state):
    """How high the box's centre is. A box can come to rest on any face; its position is the
    centre of its own bottom face, wherever that face points."""
    q, up = rotation(state), HALF_BOX
    # The box's own up, (0, up, 0), turned by q; only its height matters.
    return box(state)["y"] + up * (1 - 2 * (q["x"] ** 2 + q["z"] ** 2))


def inside_the_floor(position):
    # Any point of a box kept in by the walls, its bottom face's centre included, is over the floor.
    limit = FLOOR_EDGE + 0.01
    return abs(position["x"]) <= limit and abs(position["z"]) <= limit


def test_a_throw_flies_in_an_arc_lands_where_its_speed_says_and_rests_on_the_floor(
    start_service, tmp_path
):
    with start_service(tmp_path) as url, open_socket(url, "vr_solver") as headset:
        start = ready(headset)
        throw(headset, lift(headset, start, 1.0), {"x": 1.5, "y": 0.0, "z": 0.0})
        states = until_rest(headset)

        # Falling 1 m takes sqrt(2 / g) s, while it travels 1.5 m/s across.
        expected = start["x"] + 1.5 * math.sqrt(2 * 1.0 / GRAVITY)
        landing = next(box(state) for _, state in states if box(state)["y"] < start["y"] + 0.03)
        assert landing["x"] == pytest.approx(expected, abs=0.15)
        assert landing["z"] == pytest.approx(start["z"], abs=0.05)
        final = box(states[-1][1])
        # It slid on a little after landing, then stopped on the floor.
        assert final["x"] >= landing["x"] - 0.05
        assert centre_height(states[-1][1]) == pytest.approx(start["y"] + HALF_BOX, abs=0.01)
        assert inside_the_floor(final)


def test_a_throw_at_the_floors_edge_comes_to_rest_inside_the_floor(start_service, tmp_path):
    with start_service(tmp_path) as url, open_socket(url, "vr_solver") as headset:
        start = ready(headset)
        throw(headset, lift(headset, start, 0.5), {"x": 6.0, "y": 1.0, "z": 0.0})
        states = until_rest(headset, timeout=12)
        assert all(inside_the_floor(box(state)) for _, state in states)
        assert centre_height(states[-1][1]) == pytest.approx(start["y"] + HALF_BOX, abs=0.01)


def test_a_throw_faster_than_the_cap_flies_as_one_at_the_cap(start_service, tmp_path):
    with start_service(tmp_path) as url, open_socket(url, "vr_solver") as headset:
        start = ready(headset)
        throw(headset, lift(headset, start, 0.5), {"x": 0.0, "y": 40.0, "z": 0.0})
        states = until_rest(headset, timeout=12)
        # Thrown straight up at the cap of 8 m/s it rises 8² / 2g = 3.3 m; at 40 m/s, 82 m.
        peak = max(box(state)["y"] for _, state in states) - (start["y"] + 0.5)
        assert 2.8 < peak < 3.5


def test_a_spinning_throw_lands_turned(start_service, tmp_path):
    with start_service(tmp_path) as url, open_socket(url, "vr_solver") as headset:
        start = ready(headset)
        throw(
            headset,
            lift(headset, start, 0.5),
            {"x": 0.0, "y": 2.0, "z": 0.0},
            angular_velocity={"x": 0.0, "y": 5.0, "z": 0.0},
        )
        final = until_rest(headset)[-1][1]
        assert abs(rotation(final)["w"]) < 0.999


def test_a_velocity_that_isnt_a_number_is_refused_and_the_box_stays_held(start_service, tmp_path):
    with start_service(tmp_path) as url, open_socket(url, "vr_solver") as headset:
        start = ready(headset)
        identity = lift(headset, start, 0.5)
        # Python's JSON writes Infinity, which browsers never send.
        throw(headset, identity, {"x": math.inf, "y": 0.0, "z": 0.0})
        assert error_code(headset) == "invalid_message"
        headset.send(json.dumps(grip(2, start, identity)))
        still = receive_until(
            headset,
            lambda event: (
                owned_by(event, "vr_solver") and event["state"]["manipulation"]["sequence"] == 2
            ),
        )["state"]
        assert still["manipulation"]["id"] == identity
