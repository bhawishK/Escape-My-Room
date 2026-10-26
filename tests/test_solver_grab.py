"""The headset grabs a free object without moving it, and neither person can take the other's."""

import json
import math

import pytest
from test_manipulation import Phone, box, error_code, open_socket, receive_until

from backend.grab import grab_offset, grabbed_point

IDENTITY = {"x": 0.0, "y": 0.0, "z": 0.0, "w": 1.0}
BOX = {"x": -0.5, "y": 0.0, "z": -0.4}


def test_an_unmoved_grip_keeps_the_box_where_it_was():
    identity = (0.0, 0.0, 0.0, 1.0)
    box_at = (BOX["x"], BOX["y"], BOX["z"])
    offset = grab_offset(box_at, identity, box_at)
    assert offset == pytest.approx((0.0, 0.0, 0.0))
    assert grabbed_point(box_at, identity, offset) == pytest.approx(box_at)


def test_turning_the_grip_carries_the_offset_with_it():
    identity = (0.0, 0.0, 0.0, 1.0)
    grip = (-0.7, 0.0, -0.4)
    box_at = (BOX["x"], BOX["y"], BOX["z"])
    offset = grab_offset(grip, identity, box_at)
    assert offset == pytest.approx((0.2, 0.0, 0.0))
    turned = (0.0, math.sin(math.pi / 4), 0.0, math.cos(math.pi / 4))
    assert grabbed_point(grip, turned, offset) == pytest.approx((-0.7, 0.0, -0.6))


def acquire(position, entity="box", orientation=None):
    return {
        "type": "acquire",
        "room_version": 1,
        "id": entity,
        "position": position,
        "orientation": orientation or IDENTITY,
    }


def ended(event):
    return event.get("type") == "state" and event["state"]["manipulation"] is None


def grip(sequence, position, manipulation_id, orientation=None):
    return {
        "type": "grip",
        "manipulation_id": manipulation_id,
        "sequence": sequence,
        "position": position,
        "orientation": orientation or IDENTITY,
    }


def owned_by(event, role):
    manipulation = (event.get("state") or {}).get("manipulation") or {}
    return manipulation.get("owner") == role


def restore(ws, position):
    """Put the box back so later tests still see the place this one started from."""
    ws.send(json.dumps({"type": "entity_transform", "id": "box", "position": position}))
    receive_until(ws, lambda event: event.get("type") == "state")


def test_the_headset_grabs_without_a_jump_then_moves_and_releases(service_url):
    with (
        open_socket(service_url, "mobile_master") as phone,
        open_socket(service_url, "vr_solver") as headset,
    ):
        start = box(json.loads(phone.recv(timeout=2))["state"])
        headset.recv(timeout=2)
        headset.send(json.dumps(acquire(start)))
        grabbed = receive_until(headset, lambda event: owned_by(event, "vr_solver"))["state"]
        assert grabbed["manipulation"]["entity"] == "box"
        assert box(grabbed) == pytest.approx(start)
        seen = receive_until(phone, lambda event: owned_by(event, "vr_solver"))["state"]
        assert seen["manipulation"] == grabbed["manipulation"]
        assert box(seen) == pytest.approx(start)

        identity = grabbed["manipulation"]["id"]
        moved_to = {"x": start["x"] + 0.3, "y": start["y"] + 0.2, "z": start["z"] - 0.1}
        headset.send(json.dumps(grip(1, moved_to, identity)))
        moved = receive_until(
            headset,
            lambda event: owned_by(event, "vr_solver")
            and event["state"]["manipulation"]["sequence"] == 1,
        )["state"]
        assert box(moved) == pytest.approx(moved_to)
        phone_seen = receive_until(
            phone,
            lambda event: owned_by(event, "vr_solver")
            and event["state"]["manipulation"]["sequence"] == 1,
        )["state"]
        assert box(phone_seen) == pytest.approx(moved_to)

        headset.send(json.dumps({"type": "release", "manipulation_id": identity}))
        released = receive_until(headset, ended)["state"]
        assert box(released) == pytest.approx(moved_to)
        phone_released = receive_until(phone, ended)["state"]
        assert box(phone_released) == pytest.approx(moved_to)
        restore(phone, start)


def test_neither_person_can_take_or_move_the_others_object(service_url):
    with (
        open_socket(service_url, "mobile_master") as ws,
        open_socket(service_url, "vr_solver") as headset,
    ):
        phone = Phone(ws)
        headset.recv(timeout=2)
        phone.walk_to(0.0, 1.6)
        held = phone.pick_up()
        resting = box(held)
        identity = held["manipulation"]["id"]
        headset.send(json.dumps(acquire({"x": 1.0, "y": 1.0, "z": 1.0})))
        assert error_code(headset) == "controlled_by_other"
        headset.send(json.dumps(grip(1, {"x": 1.0, "y": 1.0, "z": 1.0}, identity)))
        assert error_code(headset) == "controlled_by_other"
        headset.send(json.dumps({"type": "release", "manipulation_id": identity}))
        assert error_code(headset) == "controlled_by_other"
        assert box(phone.walk_to(0.0, 1.0))["z"] < resting["z"]
        phone.drop(identity)

        headset.send(json.dumps(acquire(box(held))))
        grabbed = receive_until(headset, lambda event: owned_by(event, "vr_solver"))["state"]
        place = box(grabbed)
        ws.send(json.dumps({"type": "acquire", "room_version": 1, "id": "box"}))
        assert error_code(ws) == "controlled_by_other"
        phone.walk_to(0.4, 1.2)
        stayed = receive_until(
            headset,
            lambda event: event.get("type") == "state"
            and (event["state"]["marker"]["position"] or {}).get("x") == 0.4,
        )["state"]
        assert stayed["manipulation"]["id"] == grabbed["manipulation"]["id"]
        assert box(stayed) == pytest.approx(place)
        ws.send(json.dumps({"type": "release", "manipulation_id": stayed["manipulation"]["id"]}))
        assert error_code(ws) == "controlled_by_other"
        assert box(phone.walk_to(-0.2, 1.4)) == pytest.approx(place)
        headset.send(json.dumps({
            "type": "release", "manipulation_id": stayed["manipulation"]["id"],
        }))
        receive_until(headset, ended)
        restore(ws, BOX)


def test_a_headset_grab_refuses_a_fixed_object_or_a_missing_grip(service_url):
    with open_socket(service_url, "vr_solver") as headset:
        headset.recv(timeout=2)
        headset.send(json.dumps(acquire(BOX, entity="desk")))
        assert error_code(headset) == "entity_not_selectable"
        headset.send(json.dumps({"type": "acquire", "room_version": 1, "id": "box"}))
        assert error_code(headset) == "no_grip"


def test_the_phone_cannot_send_a_grip(service_url):
    with open_socket(service_url, "mobile_master") as phone:
        phone.recv(timeout=2)
        phone.send(json.dumps(grip(1, BOX, 1)))
        assert error_code(phone) == "role_forbidden"


def test_disconnecting_ends_only_that_persons_hold(service_url):
    with open_socket(service_url, "mobile_master") as phone:
        start = box(json.loads(phone.recv(timeout=2))["state"])
        with open_socket(service_url, "vr_solver") as headset:
            headset.recv(timeout=2)
            headset.send(json.dumps(acquire(start)))
            grabbed = receive_until(headset, lambda event: owned_by(event, "vr_solver"))["state"]
            identity = grabbed["manipulation"]["id"]
            lifted = {"x": start["x"] + 0.3, "y": start["y"] + 0.5, "z": start["z"]}
            headset.send(json.dumps(grip(1, lifted, identity)))
            receive_until(
                phone,
                lambda event: owned_by(event, "vr_solver")
                and event["state"]["manipulation"]["sequence"] == 1,
            )
        left = receive_until(
            phone,
            lambda event: event.get("type") == "state" and event["state"]["vr_connected"] is False,
        )["state"]
        assert left["manipulation"] is None
        assert box(left) == pytest.approx(lifted)
        restore(phone, start)

    with open_socket(service_url, "vr_solver") as headset:
        start = box(json.loads(headset.recv(timeout=2))["state"])
        headset.send(json.dumps(acquire(start)))
        receive_until(headset, lambda event: owned_by(event, "vr_solver"))
        with open_socket(service_url, "mobile_master") as phone:
            phone.recv(timeout=2)
        stayed = receive_until(
            headset,
            lambda event: event.get("type") == "state" and not event["state"]["mobile_connected"],
        )["state"]
        assert stayed["manipulation"]["owner"] == "vr_solver"
        assert box(stayed) == pytest.approx(start)
        headset.send(
            json.dumps({"type": "release", "manipulation_id": stayed["manipulation"]["id"]})
        )
        receive_until(headset, ended)
        restore(headset, start)
