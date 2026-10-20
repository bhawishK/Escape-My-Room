"""The phone picks up its selected box, carries it in front, and drops it; WebSocket seam."""

import json
import math

import pytest
from websockets.sync.client import connect


def open_socket(url, role):
    return connect(f"{url.replace('http://', 'ws://')}/api/ws?role={role}")


def receive_until(ws, predicate):
    for _ in range(20):
        message = json.loads(ws.recv(timeout=2))
        if predicate(message):
            return message
    raise AssertionError("Expected message was not received")


class Phone:
    """A connected phone that has selected the box and walks by sending tracked poses."""

    def __init__(self, ws):
        self.ws = ws
        self.sequence = 0
        ws.recv(timeout=2)
        ws.send(json.dumps({"type": "select", "room_version": 1, "id": "box"}))
        ws.recv(timeout=2)

    def walk_to(self, x, z, heading=0.0):
        """Stand at (x, z) at phone height, facing `heading`: 0 toward the desk, positive left."""
        self.sequence += 1
        self.ws.send(
            json.dumps(
                {
                    "type": "pose",
                    "sequence": self.sequence,
                    "tracking_status": "tracked",
                    "reference_space": "room",
                    "position": {"x": x, "y": 1.5, "z": z},
                    "heading": heading,
                }
            )
        )
        return self.state()

    def stop_walking(self):
        self.sequence += 1
        return self.send(
            {
                "type": "pose",
                "sequence": self.sequence,
                "tracking_status": "inactive",
                "reference_space": None,
                "position": None,
                "heading": None,
            }
        )["state"]

    def pick_up(self):
        return self.send({"type": "acquire", "room_version": 1, "id": "box"})["state"]

    def drop(self, manipulation_id):
        return self.send({"type": "release", "manipulation_id": manipulation_id})["state"]

    def send(self, message):
        self.ws.send(json.dumps(message))
        return json.loads(self.ws.recv(timeout=2))

    def state(self):
        return receive_until(self.ws, lambda event: event["type"] == "state")["state"]


def box(state):
    return next(entity for entity in state["room"]["entities"] if entity["id"] == "box")[
        "position"
    ]


def test_picking_up_the_box_brings_it_in_front_of_the_phone(service_url):
    with open_socket(service_url, "mobile_master") as ws:
        phone = Phone(ws)
        phone.walk_to(0.0, 1.6)
        held = phone.pick_up()
        assert held["manipulation"]["entity"] == "box"
        assert held["manipulation"]["owner"] == "mobile_master"
        # 0.8 m ahead toward the desk, its bottom 0.6 m below the phone.
        assert box(held) == pytest.approx({"x": 0.0, "y": 0.9, "z": 0.8})
        phone.drop(held["manipulation"]["id"])


def test_the_carried_box_stays_in_front_as_the_phone_walks_and_turns(service_url):
    with open_socket(service_url, "mobile_master") as ws:
        phone = Phone(ws)
        phone.walk_to(0.0, 1.6)
        held = phone.pick_up()
        assert box(phone.walk_to(0.0, 1.0)) == pytest.approx({"x": 0.0, "y": 0.9, "z": 0.2})
        turned_left = box(phone.walk_to(0.0, 1.0, heading=math.pi / 2))
        assert turned_left == pytest.approx({"x": -0.8, "y": 0.9, "z": 1.0})
        phone.drop(held["manipulation"]["id"])


def test_letting_go_drops_the_box_to_the_floor_where_it_is(service_url):
    with open_socket(service_url, "mobile_master") as ws:
        phone = Phone(ws)
        resting = box(phone.walk_to(0.0, 1.6))
        held = phone.pick_up()
        first = held["manipulation"]["id"]
        phone.walk_to(0.5, 1.6)
        dropped = phone.drop(first)
        assert dropped["manipulation"] is None
        assert box(dropped) == pytest.approx({"x": 0.5, "y": resting["y"], "z": 0.8})
        # Walking without holding leaves the box where it fell.
        assert box(phone.walk_to(0.0, 1.0)) == box(dropped)
        again = phone.pick_up()
        assert again["manipulation"]["id"] > first
        phone.drop(again["manipulation"]["id"])


def error_code(ws):
    return receive_until(ws, lambda event: event["type"] == "error")["code"]


@pytest.mark.parametrize(
    ("acquire", "code"),
    [
        ({"room_version": 1, "id": "desk"}, "not_selected"),
        ({"room_version": 2, "id": "box"}, "room_version_mismatch"),
    ],
)
def test_a_refused_pick_up_leaves_the_box(service_url, acquire, code):
    with open_socket(service_url, "mobile_master") as ws:
        phone = Phone(ws)
        before = box(phone.walk_to(0.0, 1.6))
        ws.send(json.dumps({"type": "acquire"} | acquire))
        assert error_code(ws) == code
        after = phone.walk_to(0.0, 1.0)
        assert after["manipulation"] is None
        assert box(after) == before


def test_the_phone_must_be_walking_to_pick_up(service_url):
    with open_socket(service_url, "mobile_master") as ws:
        Phone(ws)
        ws.send(json.dumps({"type": "acquire", "room_version": 1, "id": "box"}))
        assert error_code(ws) == "not_tracked"


def test_the_phone_must_have_selected_the_box(service_url):
    with open_socket(service_url, "mobile_master") as ws:
        phone = Phone(ws)
        phone.send({"type": "select", "room_version": 1, "id": None})
        phone.walk_to(0.0, 1.6)
        ws.send(json.dumps({"type": "acquire", "room_version": 1, "id": "box"}))
        assert error_code(ws) == "not_selected"


def test_the_headset_sees_the_hold_but_cannot_take_or_end_it(service_url):
    with (
        open_socket(service_url, "mobile_master") as ws,
        open_socket(service_url, "vr_solver") as headset,
    ):
        phone = Phone(ws)
        headset.recv(timeout=2)
        phone.walk_to(0.0, 1.6)
        held = phone.pick_up()
        seen = receive_until(
            headset, lambda event: event.get("state", {}).get("manipulation") is not None
        )["state"]
        assert seen["manipulation"] == held["manipulation"]
        assert box(seen) == box(held)
        identity = held["manipulation"]["id"]
        for message in (
            {"type": "acquire", "room_version": 1, "id": "box"},
            {"type": "release", "manipulation_id": identity},
        ):
            headset.send(json.dumps(message))
            assert error_code(headset) == "role_forbidden"
        carried = box(phone.walk_to(0.0, 1.0))
        headset.send(json.dumps({"type": "entity_transform", "id": "box", "position": carried}))
        assert error_code(headset) == "entity_controlled"
        phone.drop(identity)


def test_a_stale_release_or_second_pick_up_is_refused(service_url):
    with open_socket(service_url, "mobile_master") as ws:
        phone = Phone(ws)
        phone.walk_to(0.0, 1.6)
        identity = phone.pick_up()["manipulation"]["id"]
        ws.send(json.dumps({"type": "acquire", "room_version": 1, "id": "box"}))
        assert error_code(ws) == "already_held"
        ws.send(json.dumps({"type": "release", "manipulation_id": identity + 1}))
        assert error_code(ws) == "stale_manipulation"
        assert phone.walk_to(0.0, 1.0)["manipulation"]["id"] == identity
        phone.drop(identity)


def test_the_box_drops_when_the_phone_stops_walking(service_url):
    with open_socket(service_url, "mobile_master") as ws:
        phone = Phone(ws)
        resting = box(phone.walk_to(0.0, 1.6))
        phone.pick_up()
        phone.walk_to(0.0, 1.0)
        stopped = phone.stop_walking()
        assert stopped["manipulation"] is None
        assert box(stopped) == pytest.approx({"x": 0.0, "y": resting["y"], "z": 0.2})


def test_the_box_drops_when_the_phone_disconnects(service_url):
    with open_socket(service_url, "vr_solver") as headset:
        headset.recv(timeout=2)
        with open_socket(service_url, "mobile_master") as ws:
            phone = Phone(ws)
            resting = box(phone.walk_to(0.0, 1.6))
            phone.pick_up()
            phone.walk_to(0.0, 1.0)
        gone = receive_until(
            headset, lambda event: event.get("state", {}).get("mobile_connected") is False
        )["state"]
        assert gone["manipulation"] is None
        assert box(gone) == pytest.approx({"x": 0.0, "y": resting["y"], "z": 0.2})


def test_the_hold_reports_its_latest_movement(service_url):
    with open_socket(service_url, "mobile_master") as ws:
        phone = Phone(ws)
        phone.walk_to(0.0, 1.6)
        held = phone.pick_up()
        assert held["manipulation"]["sequence"] is None
        assert phone.walk_to(0.0, 1.0)["manipulation"]["sequence"] == phone.sequence
        phone.drop(held["manipulation"]["id"])


def test_the_selection_cannot_change_during_a_hold(service_url):
    with open_socket(service_url, "mobile_master") as ws:
        phone = Phone(ws)
        phone.walk_to(0.0, 1.6)
        held = phone.pick_up()
        reply = phone.send({"type": "select", "room_version": 1, "id": None})
        assert reply["id"] == "box"
        assert reply["rejected"]["code"] == "selection_held"
        phone.drop(held["manipulation"]["id"])
