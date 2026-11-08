"""Late and repeated grabs leave one hold, and both devices see that same result."""

import json

import pytest
from test_manipulation import Phone, box, error_code, open_socket, receive_until
from test_physics_fall import until_rest
from test_solver_grab import acquire, grip, restore


def drain(ws):
    """Read whatever is already queued so the next messages are from the commands under test."""
    while True:
        try:
            ws.recv(timeout=0.05)
        except TimeoutError:
            return


def held_at(event, x):
    position = ((event.get("state") or {}).get("marker") or {}).get("position") or {}
    return event.get("type") == "state" and position.get("x") == x


def ended(event):
    return event.get("type") == "state" and event["state"]["manipulation"] is None


def gripped(event):
    manipulation = (event.get("state") or {}).get("manipulation") or {}
    return owned(event, "vr_solver") and manipulation.get("sequence") == 1


def owned(event, role):
    manipulation = (event.get("state") or {}).get("manipulation") or {}
    return event.get("type") == "state" and manipulation.get("owner") == role


def burst(ws):
    """The error, if any, and the newest hold seen while the replies to one burst arrive."""
    code = None
    state = None
    for _ in range(12):
        try:
            message = json.loads(ws.recv(timeout=0.5))
        except TimeoutError:
            break
        if message.get("type") == "error":
            code = message["code"]
        elif message.get("type") == "state":
            state = message["state"]
    return code, state


def test_both_asking_at_once_leaves_one_owner_on_both_screens(service_url):
    with (
        open_socket(service_url, "mobile_master") as phone_ws,
        open_socket(service_url, "vr_solver") as headset,
    ):
        phone = Phone(phone_ws)
        headset.recv(timeout=2)
        start = box(phone.walk_to(0.0, 1.6))
        drain(headset)
        phone_ws.send(json.dumps({"type": "acquire", "room_version": 1, "id": "box"}))
        headset.send(json.dumps(acquire(start)))
        phone_code, phone_state = burst(phone_ws)
        headset_code, headset_state = burst(headset)
        assert phone_state is not None and headset_state is not None
        assert phone_state["manipulation"]["id"] == headset_state["manipulation"]["id"]
        assert phone_state["manipulation"]["owner"] == headset_state["manipulation"]["owner"]
        assert box(phone_state) == pytest.approx(box(headset_state))
        codes = {phone_code, headset_code}
        assert codes == {None, "controlled_by_other"}
        owner = phone_state["manipulation"]["owner"]
        winner = phone_ws if owner == "mobile_master" else headset
        hold_id = phone_state["manipulation"]["id"]
        winner.send(json.dumps({"type": "release", "manipulation_id": hold_id}))
        receive_until(winner, ended)
        restore(winner, start)


def test_an_earlier_hold_cannot_move_or_end_the_new_one(service_url):
    with (
        open_socket(service_url, "mobile_master") as phone_ws,
        open_socket(service_url, "vr_solver") as headset,
    ):
        phone = Phone(phone_ws)
        start = box(json.loads(headset.recv(timeout=2))["state"])
        phone.walk_to(0.0, 1.6)
        headset.send(json.dumps(acquire(start)))
        grabbed = receive_until(headset, lambda event: owned(event, "vr_solver"))["state"]
        old_id = grabbed["manipulation"]["id"]
        lifted = {"x": start["x"] + 0.3, "y": start["y"] + 0.4, "z": start["z"]}
        headset.send(json.dumps(grip(1, lifted, old_id)))
        receive_until(headset, gripped)
        headset.send(json.dumps({"type": "release", "manipulation_id": old_id}))
        receive_until(headset, ended)
        # Let go in the air, it falls (#161); the phone picks it up once it has settled.
        until_rest(headset)
        drain(phone_ws)
        held = phone.pick_up()
        new_id = held["manipulation"]["id"]
        assert new_id != old_id
        headset.send(json.dumps(grip(2, {"x": 3.0, "y": 2.0, "z": 3.0}, old_id)))
        assert error_code(headset) == "stale_manipulation"
        headset.send(json.dumps({"type": "release", "manipulation_id": old_id}))
        assert error_code(headset) == "stale_manipulation"
        phone_ws.send(json.dumps({"type": "release", "manipulation_id": old_id}))
        assert error_code(phone_ws) == "stale_manipulation"
        still = phone.walk_to(0.4, 1.2)
        assert still["manipulation"]["id"] == new_id
        assert still["manipulation"]["owner"] == "mobile_master"
        seen = receive_until(headset, lambda event: held_at(event, 0.4))["state"]
        assert seen["manipulation"]["id"] == new_id
        assert box(seen) == pytest.approx(box(still))
        phone.drop(new_id)
        restore(phone_ws, start)


def test_repeating_acquire_and_release_leaves_the_same_object(service_url):
    with (
        open_socket(service_url, "mobile_master") as phone_ws,
        open_socket(service_url, "vr_solver") as headset,
    ):
        phone = Phone(phone_ws)
        start = box(json.loads(headset.recv(timeout=2))["state"])
        phone.walk_to(0.0, 1.6)
        held = phone.pick_up()
        identity = held["manipulation"]["id"]
        phone_ws.send(json.dumps({"type": "acquire", "room_version": 1, "id": "box"}))
        assert error_code(phone_ws) == "already_held"
        headset.send(json.dumps(acquire({"x": 1.0, "y": 1.0, "z": 1.0})))
        assert error_code(headset) == "controlled_by_other"
        again = phone.walk_to(0.2, 1.4)
        assert again["manipulation"]["id"] == identity
        seen = receive_until(headset, lambda event: held_at(event, 0.2))["state"]
        assert seen["manipulation"]["id"] == identity
        assert box(seen) == pytest.approx(box(again))
        dropped = phone.drop(identity)
        dropped_at = box(dropped)
        assert dropped["manipulation"] is None
        settled = receive_until(headset, ended)["state"]
        assert box(settled) == pytest.approx(dropped_at)
        phone_ws.send(json.dumps({"type": "release", "manipulation_id": identity}))
        assert error_code(phone_ws) == "stale_manipulation"
        headset.send(json.dumps({"type": "release", "manipulation_id": identity}))
        assert error_code(headset) == "stale_manipulation"
        restore(phone_ws, start)


def test_a_phone_pose_cannot_move_or_drop_the_headsets_hold(service_url):
    with (
        open_socket(service_url, "mobile_master") as phone_ws,
        open_socket(service_url, "vr_solver") as headset,
    ):
        phone = Phone(phone_ws)
        start = box(json.loads(headset.recv(timeout=2))["state"])
        headset.send(json.dumps(acquire(start)))
        grabbed = receive_until(headset, lambda event: owned(event, "vr_solver"))["state"]
        identity = grabbed["manipulation"]["id"]
        lifted = {"x": start["x"], "y": start["y"] + 0.6, "z": start["z"]}
        headset.send(json.dumps(grip(1, lifted, identity)))
        receive_until(headset, gripped)
        drain(phone_ws)
        moved = phone.walk_to(-0.4, 1.0)
        assert moved["manipulation"]["owner"] == "vr_solver"
        assert box(moved) == pytest.approx(lifted)
        lost = phone.stop_walking()
        assert lost["manipulation"]["id"] == identity
        assert box(lost) == pytest.approx(lifted)
        headset.send(json.dumps({"type": "release", "manipulation_id": identity}))
        receive_until(headset, ended)
        restore(headset, start)
