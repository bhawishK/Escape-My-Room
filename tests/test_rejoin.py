"""Leaving the room ends that person's hold, and joining again sees the same room."""

import json

import pytest
from test_manipulation import Phone, box, error_code, open_socket, receive_until
from test_physics_fall import until_rest
from test_solver_grab import acquire, grip, restore
from websockets.exceptions import ConnectionClosed


def room_version(state):
    return state["room"]["room_version"]


def tracked_pose(sequence, x, z):
    return {
        "type": "pose",
        "sequence": sequence,
        "tracking_status": "tracked",
        "reference_space": "room",
        "position": {"x": x, "y": 1.5, "z": z},
        "heading": 0.0,
        "pitch": -0.8,
    }


def test_an_idle_phone_rejoins_the_same_room(service_url):
    with open_socket(service_url, "vr_solver") as headset:
        start = box(json.loads(headset.recv(timeout=2))["state"])
        with open_socket(service_url, "mobile_master") as phone:
            phone.recv(timeout=2)
        gone = receive_until(
            headset, lambda event: event.get("state", {}).get("mobile_connected") is False
        )["state"]
        assert gone["vr_connected"] is True
        assert gone["manipulation"] is None
        assert box(gone) == pytest.approx(start)
        with open_socket(service_url, "mobile_master") as phone:
            welcome = json.loads(phone.recv(timeout=2))["state"]
            assert welcome["vr_connected"] is True
            assert welcome["manipulation"] is None
            assert room_version(welcome) == room_version(gone)
            assert box(welcome) == pytest.approx(start)


def test_an_idle_headset_rejoins_the_same_room(service_url):
    with open_socket(service_url, "mobile_master") as phone:
        start = box(json.loads(phone.recv(timeout=2))["state"])
        with open_socket(service_url, "vr_solver") as headset:
            headset.recv(timeout=2)
        gone = receive_until(
            phone, lambda event: event.get("state", {}).get("vr_connected") is False
        )["state"]
        assert gone["mobile_connected"] is True
        assert gone["manipulation"] is None
        assert box(gone) == pytest.approx(start)
        with open_socket(service_url, "vr_solver") as headset:
            welcome = json.loads(headset.recv(timeout=2))["state"]
            assert welcome["mobile_connected"] is True
            assert welcome["manipulation"] is None
            assert room_version(welcome) == room_version(gone)
            assert box(welcome) == pytest.approx(start)


def test_the_phone_rejoins_without_the_old_hold(service_url):
    with open_socket(service_url, "vr_solver") as headset:
        start = box(json.loads(headset.recv(timeout=2))["state"])
        with open_socket(service_url, "mobile_master") as old:
            phone = Phone(old)
            phone.walk_to(0.0, 1.6)
            held = phone.pick_up()
            carried = box(held)
            old_id = held["manipulation"]["id"]
        receive_until(
            headset, lambda event: event.get("state", {}).get("mobile_connected") is False
        )
        with open_socket(service_url, "mobile_master") as phone_ws:
            welcome = json.loads(phone_ws.recv(timeout=2))["state"]
            assert welcome["manipulation"] is None
            assert welcome["vr_connected"] is True
            assert box(welcome) == pytest.approx(carried)
            phone_ws.send(json.dumps({"type": "release", "manipulation_id": old_id}))
            assert error_code(phone_ws) == "stale_manipulation"
            phone = Phone.__new__(Phone)
            phone.ws = phone_ws
            phone.sequence = 0
            again = phone.walk_to(0.4, 1.2)
            assert again["manipulation"] is None
            assert box(again) == pytest.approx(carried)
            phone.ws.send(json.dumps({"type": "select", "room_version": 1, "id": "box"}))
            phone.ws.recv(timeout=2)
            picked = phone.pick_up()
            assert picked["manipulation"]["id"] != old_id
            assert box(picked) != pytest.approx(carried)
            phone.drop(picked["manipulation"]["id"])
        restore(headset, start)


def test_the_headset_rejoins_without_the_old_hold(service_url):
    with open_socket(service_url, "mobile_master") as phone:
        start = box(json.loads(phone.recv(timeout=2))["state"])
        with open_socket(service_url, "vr_solver") as headset:
            headset.recv(timeout=2)
            headset.send(json.dumps(acquire(start)))
            grabbed = receive_until(
                headset,
                lambda event: (
                    ((event.get("state") or {}).get("manipulation") or {}).get("owner")
                    == "vr_solver"
                ),
            )["state"]
            old_id = grabbed["manipulation"]["id"]
            lifted = {"x": start["x"], "y": start["y"] + 0.5, "z": start["z"]}
            headset.send(json.dumps(grip(1, lifted, old_id)))
            receive_until(
                phone,
                lambda event: (
                    ((event.get("state") or {}).get("manipulation") or {}).get("sequence") == 1
                ),
            )
        left = receive_until(
            phone, lambda event: event.get("state", {}).get("vr_connected") is False
        )["state"]
        assert left["manipulation"] is None
        assert left["mobile_connected"] is True
        # Let go in the air as the headset left, the box falls and settles on the floor (#161).
        rested = box(until_rest(phone)[-1][1])
        assert rested["y"] == pytest.approx(start["y"], abs=0.01)
        with open_socket(service_url, "vr_solver") as headset:
            welcome = json.loads(headset.recv(timeout=2))["state"]
            assert welcome["manipulation"] is None
            assert welcome["mobile_connected"] is True
            assert box(welcome) == rested
            headset.send(json.dumps({"type": "release", "manipulation_id": old_id}))
            assert error_code(headset) == "stale_manipulation"
            headset.send(json.dumps(grip(1, {"x": 2.0, "y": 2.0, "z": 2.0}, old_id)))
            assert error_code(headset) == "stale_manipulation"
            headset.send(json.dumps(acquire({"x": 1.0, "y": 1.0, "z": 1.0})))
            fresh = receive_until(
                phone,
                lambda event: (
                    ((event.get("state") or {}).get("manipulation") or {}).get("owner")
                    == "vr_solver"
                ),
            )["state"]
            fresh_id = fresh["manipulation"]["id"]
            assert fresh_id != old_id
            assert box(fresh) == rested
            headset.send(json.dumps({"type": "release", "manipulation_id": fresh_id}))

            def released(event):
                return event.get("type") == "state" and event["state"]["manipulation"] is None

            receive_until(phone, released)
        restore(phone, start)


def at_marker_x(event, x):
    position = ((event.get("state") or {}).get("marker") or {}).get("position") or {}
    return position.get("x") == x


def test_a_replaced_socket_cannot_move_the_box(service_url):
    with open_socket(service_url, "vr_solver") as headset:
        start = box(json.loads(headset.recv(timeout=2))["state"])
        old = open_socket(service_url, "mobile_master")
        new = None
        try:
            phone = Phone(old)
            phone.walk_to(0.0, 1.6)
            held = phone.pick_up()
            carried = box(held)
            old_id = held["manipulation"]["id"]
            new = open_socket(service_url, "mobile_master")
            welcome = json.loads(new.recv(timeout=2))["state"]
            assert welcome["manipulation"] is None
            assert box(welcome) == pytest.approx(carried)
            try:
                old.send(json.dumps(tracked_pose(50, 3.0, 3.0)))
                old.send(json.dumps({"type": "release", "manipulation_id": old_id}))
            except ConnectionClosed:
                pass
            new.send(json.dumps(tracked_pose(1, 0.2, 1.0)))
            seen = receive_until(headset, lambda event: at_marker_x(event, 0.2))["state"]
            assert seen["manipulation"] is None
            assert box(seen) == pytest.approx(carried)
            assert seen["marker"]["position"]["x"] == 0.2
        finally:
            if new is not None:
                new.close()
            old.close()
        restore(headset, start)
