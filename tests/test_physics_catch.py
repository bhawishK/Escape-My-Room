"""Either person catches a moving box (#163); WebSocket seam, real Havok worker."""

import json
import time

import pytest
from test_manipulation import box, error_code, open_socket, receive_until
from test_physics_fall import ready, until_rest
from test_physics_throw import centre_height, lift, throw
from test_solver_grab import acquire, grip, owned_by

HALF_BOX = 0.1


def falling_past(ws, height):
    """The first state with the box moving and below `height`: in mid-fall."""
    return receive_until(
        ws,
        lambda event: (
            event.get("type") == "state"
            and "box" in event["state"]["physics"]["moving"]
            and box(event["state"])["y"] < height
        ),
    )["state"]


def states_for(ws, seconds):
    """Every state that arrives in the next `seconds`."""
    seen = []
    deadline = time.monotonic() + seconds
    while (left := deadline - time.monotonic()) > 0:
        try:
            event = json.loads(ws.recv(timeout=left))
        except TimeoutError:
            break
        if event.get("type") == "state":
            seen.append(event["state"])
    return seen


def ready_to_catch(phone):
    """The phone has the box selected and stands tracked, 1.5 m up, looking 45° down."""
    phone.send(json.dumps({"type": "select", "room_version": 1, "id": "box"}))
    phone.send(
        json.dumps(
            {
                "type": "pose",
                "sequence": 1,
                "tracking_status": "tracked",
                "reference_space": "room",
                "position": {"x": 0.0, "y": 1.5, "z": 1.6},
                "heading": 0.0,
                "pitch": -0.7853981633974483,
            }
        )
    )


def test_the_headset_catches_a_falling_box_which_then_follows_its_grip(start_service, tmp_path):
    with (
        start_service(tmp_path) as url,
        open_socket(url, "vr_solver") as headset,
        open_socket(url, "mobile_master") as phone,
    ):
        start = ready(headset)
        identity = lift(headset, start, 1.5)
        headset.send(json.dumps({"type": "release", "manipulation_id": identity}))
        caught_at = box(falling_past(headset, start["y"] + 1.2))

        headset.send(json.dumps(acquire(caught_at)))
        caught = receive_until(headset, lambda event: owned_by(event, "vr_solver"))["state"]
        held = box(caught)
        assert held["y"] > start["y"] + 0.5
        assert "box" not in caught["physics"]["moving"]
        # It no longer falls: nothing moves it but the hand.
        assert all(box(state) == held for state in states_for(headset, 0.4))
        moved = {"x": held["x"] + 0.2, "y": held["y"], "z": held["z"]}
        # Grip sequences keep counting up on this socket: lifting sent 1.
        headset.send(json.dumps(grip(2, moved, caught["manipulation"]["id"])))
        followed = receive_until(
            headset,
            lambda event: (
                owned_by(event, "vr_solver") and event["state"]["manipulation"]["sequence"] == 2
            ),
        )["state"]
        assert box(followed) == pytest.approx(moved, abs=0.02)

        # The phone can't take it from the headset's hand.
        phone.send(json.dumps({"type": "select", "room_version": 1, "id": "box"}))
        phone.send(json.dumps({"type": "acquire", "room_version": 1, "id": "box"}))
        assert error_code(phone) in ("controlled_by_other", "not_tracked")


def test_a_caught_box_let_go_again_falls_and_settles(start_service, tmp_path):
    with start_service(tmp_path) as url, open_socket(url, "vr_solver") as headset:
        start = ready(headset)
        identity = lift(headset, start, 1.5)
        headset.send(json.dumps({"type": "release", "manipulation_id": identity}))
        caught_at = box(falling_past(headset, start["y"] + 1.2))
        headset.send(json.dumps(acquire(caught_at)))
        caught = receive_until(headset, lambda event: owned_by(event, "vr_solver"))["state"]

        headset.send(
            json.dumps({"type": "release", "manipulation_id": caught["manipulation"]["id"]})
        )
        final = until_rest(headset)[-1][1]
        assert centre_height(final) == pytest.approx(start["y"] + HALF_BOX, abs=0.01)


def test_the_phone_catches_a_falling_box_and_carries_it_on_the_floor(start_service, tmp_path):
    with (
        start_service(tmp_path) as url,
        open_socket(url, "vr_solver") as headset,
        open_socket(url, "mobile_master") as phone,
    ):
        start = ready(headset)
        ready_to_catch(phone)
        identity = lift(headset, start, 1.5)
        headset.send(json.dumps({"type": "release", "manipulation_id": identity}))
        falling_past(headset, start["y"] + 1.2)

        phone.send(json.dumps({"type": "acquire", "room_version": 1, "id": "box"}))
        carried = receive_until(phone, lambda event: owned_by(event, "mobile_master"))["state"]
        # Carried as ever: on the floor where the screen's centre meets it, not in the air.
        assert box(carried) == pytest.approx({"x": 0.0, "y": start["y"], "z": 0.1}, abs=1e-6)
        assert all(box(state)["y"] == pytest.approx(start["y"]) for state in states_for(phone, 0.4))

        phone.send(
            json.dumps({"type": "release", "manipulation_id": carried["manipulation"]["id"]})
        )
        dropped = receive_until(
            phone, lambda event: event.get("type") == "state" and not event["state"]["manipulation"]
        )["state"]
        assert box(dropped)["y"] == pytest.approx(start["y"])


def test_the_phone_catches_a_thrown_box_mid_flight_and_the_headset_cant_take_it(
    start_service, tmp_path
):
    with (
        start_service(tmp_path) as url,
        open_socket(url, "vr_solver") as headset,
        open_socket(url, "mobile_master") as phone,
    ):
        start = ready(headset)
        ready_to_catch(phone)
        throw(headset, lift(headset, start, 1.0), {"x": 0.5, "y": 3.0, "z": 0.0})
        # Rising or falling, it is in the air and moving.
        receive_until(
            headset,
            lambda event: (
                event.get("type") == "state"
                and "box" in event["state"]["physics"]["moving"]
                and box(event["state"])["y"] > start["y"] + 1.2
            ),
        )

        phone.send(json.dumps({"type": "acquire", "room_version": 1, "id": "box"}))
        carried = receive_until(phone, lambda event: owned_by(event, "mobile_master"))["state"]
        assert box(carried)["y"] == pytest.approx(start["y"])
        headset.send(json.dumps(acquire(box(carried))))
        assert error_code(headset) == "controlled_by_other"
