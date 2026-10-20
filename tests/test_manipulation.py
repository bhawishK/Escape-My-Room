"""The phone holds the selected box and carries it by walking, over the public WebSocket seam."""

import json

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

    def walk_to(self, x, z):
        self.sequence += 1
        self.ws.send(
            json.dumps(
                {
                    "type": "pose",
                    "sequence": self.sequence,
                    "tracking_status": "tracked",
                    "reference_space": "room",
                    "position": {"x": x, "y": 1.5, "z": z},
                }
            )
        )
        return self.state()

    def send(self, message):
        self.ws.send(json.dumps(message))
        return json.loads(self.ws.recv(timeout=2))

    def state(self):
        return receive_until(self.ws, lambda event: event["type"] == "state")["state"]


def box(state):
    return next(entity for entity in state["room"]["entities"] if entity["id"] == "box")[
        "position"
    ]


def test_holding_the_box_carries_it_with_the_phone(service_url):
    with open_socket(service_url, "mobile_master") as ws:
        phone = Phone(ws)
        start = box(phone.walk_to(0.0, 1.6))
        held = phone.send({"type": "acquire", "room_version": 1, "id": "box"})
        assert held["state"]["manipulation"]["entity"] == "box"
        assert held["state"]["manipulation"]["owner"] == "mobile_master"
        moved = box(phone.walk_to(0.0, 1.0))
        assert moved == pytest.approx({"x": start["x"], "y": start["y"], "z": start["z"] - 0.6})


def test_release_leaves_the_box_and_a_new_hold_starts_where_it_is(service_url):
    with open_socket(service_url, "mobile_master") as ws:
        phone = Phone(ws)
        phone.walk_to(0.0, 1.6)
        held = phone.send({"type": "acquire", "room_version": 1, "id": "box"})["state"]
        first = held["manipulation"]["id"]
        phone.walk_to(0.6, 1.6)
        released = phone.send({"type": "release", "manipulation_id": first})["state"]
        assert released["manipulation"] is None
        placed = box(released)
        # Walking without a hold leaves the box where it was released.
        assert box(phone.walk_to(0.0, 1.0)) == placed
        again = phone.send({"type": "acquire", "room_version": 1, "id": "box"})["state"]
        assert again["manipulation"]["id"] > first
        assert box(again) == placed
        carried = box(phone.walk_to(0.0, 0.4))
        assert carried == pytest.approx({**placed, "z": placed["z"] - 0.6})
        phone.send({"type": "release", "manipulation_id": again["manipulation"]["id"]})


def error_code(ws):
    return receive_until(ws, lambda event: event["type"] == "error")["code"]


@pytest.mark.parametrize(
    ("acquire", "code"),
    [
        ({"room_version": 1, "id": "desk"}, "not_selected"),
        ({"room_version": 2, "id": "box"}, "room_version_mismatch"),
    ],
)
def test_a_refused_hold_does_not_carry_the_box(service_url, acquire, code):
    with open_socket(service_url, "mobile_master") as ws:
        phone = Phone(ws)
        before = box(phone.walk_to(0.0, 1.6))
        ws.send(json.dumps({"type": "acquire"} | acquire))
        assert error_code(ws) == code
        after = phone.walk_to(0.0, 1.0)
        assert after["manipulation"] is None
        assert box(after) == before


def test_the_phone_must_be_walking_to_hold(service_url):
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
    with open_socket(service_url, "mobile_master") as ws, open_socket(
        service_url, "vr_solver"
    ) as headset:
        phone = Phone(ws)
        headset.recv(timeout=2)
        phone.walk_to(0.0, 1.6)
        held = phone.send({"type": "acquire", "room_version": 1, "id": "box"})["state"]
        seen = receive_until(
            headset, lambda event: event.get("state", {}).get("manipulation") is not None
        )["state"]
        assert seen["manipulation"] == held["manipulation"]
        identity = held["manipulation"]["id"]
        for message in (
            {"type": "acquire", "room_version": 1, "id": "box"},
            {"type": "release", "manipulation_id": identity},
        ):
            headset.send(json.dumps(message))
            assert error_code(headset) == "role_forbidden"
        moved = box(phone.walk_to(0.0, 1.0))
        headset.send(json.dumps({"type": "entity_transform", "id": "box", "position": moved}))
        assert error_code(headset) == "entity_controlled"
        released = phone.send({"type": "release", "manipulation_id": identity})["state"]
        assert box(released) == moved


def test_a_stale_release_or_second_hold_is_refused(service_url):
    with open_socket(service_url, "mobile_master") as ws:
        phone = Phone(ws)
        phone.walk_to(0.0, 1.6)
        held = phone.send({"type": "acquire", "room_version": 1, "id": "box"})["state"]
        identity = held["manipulation"]["id"]
        ws.send(json.dumps({"type": "acquire", "room_version": 1, "id": "box"}))
        assert error_code(ws) == "already_held"
        ws.send(json.dumps({"type": "release", "manipulation_id": identity + 1}))
        assert error_code(ws) == "stale_manipulation"
        assert phone.walk_to(0.0, 1.0)["manipulation"]["id"] == identity
        phone.send({"type": "release", "manipulation_id": identity})


def test_the_gain_scales_how_far_the_box_moves(start_service, tmp_path):
    with start_service(tmp_path, ESCAPE_ROOM_MANIPULATION_GAIN="2.0") as url:
        with open_socket(url, "mobile_master") as ws:
            phone = Phone(ws)
            start = box(phone.walk_to(0.0, 1.6))
            phone.send({"type": "acquire", "room_version": 1, "id": "box"})
            moved = box(phone.walk_to(0.3, 1.6))
            assert moved == pytest.approx({**start, "x": start["x"] + 0.6})


def test_the_hold_ends_when_the_phone_stops_walking(service_url):
    with open_socket(service_url, "mobile_master") as ws:
        phone = Phone(ws)
        phone.walk_to(0.0, 1.6)
        phone.send({"type": "acquire", "room_version": 1, "id": "box"})
        moved = box(phone.walk_to(0.0, 1.0))
        phone.sequence += 1
        stopped = phone.send(
            {
                "type": "pose",
                "sequence": phone.sequence,
                "tracking_status": "inactive",
                "reference_space": None,
                "position": None,
            }
        )["state"]
        assert stopped["manipulation"] is None
        assert box(stopped) == moved
        assert box(phone.walk_to(0.0, 1.6)) == moved


def test_the_hold_ends_when_the_phone_disconnects(service_url):
    with open_socket(service_url, "vr_solver") as headset:
        headset.recv(timeout=2)
        with open_socket(service_url, "mobile_master") as ws:
            phone = Phone(ws)
            phone.walk_to(0.0, 1.6)
            phone.send({"type": "acquire", "room_version": 1, "id": "box"})
            moved = box(phone.walk_to(0.0, 1.0))
        gone = receive_until(
            headset, lambda event: event.get("state", {}).get("mobile_connected") is False
        )["state"]
        assert gone["manipulation"] is None
        assert box(gone) == moved


def test_the_hold_reports_its_mapping_and_latest_movement(start_service, tmp_path):
    with start_service(tmp_path, ESCAPE_ROOM_MANIPULATION_GAIN="1.5") as url:
        with open_socket(url, "mobile_master") as ws:
            phone = Phone(ws)
            phone.walk_to(0.0, 1.6)
            held = phone.send({"type": "acquire", "room_version": 1, "id": "box"})["state"]
            assert held["manipulation"]["gain"] == 1.5
            assert held["manipulation"]["sequence"] is None
            moved = phone.walk_to(0.0, 1.0)
            assert moved["manipulation"]["sequence"] == phone.sequence


def test_the_box_keeps_its_height_when_the_phone_rises(service_url):
    with open_socket(service_url, "mobile_master") as ws:
        phone = Phone(ws)
        start = box(phone.walk_to(0.0, 1.6))
        phone.send({"type": "acquire", "room_version": 1, "id": "box"})
        phone.sequence += 1
        risen = phone.send(
            {
                "type": "pose",
                "sequence": phone.sequence,
                "tracking_status": "tracked",
                "reference_space": "room",
                "position": {"x": 0.0, "y": 2.0, "z": 1.6},
            }
        )["state"]
        assert box(risen)["y"] == start["y"]


def test_the_selection_cannot_change_during_a_hold(service_url):
    with open_socket(service_url, "mobile_master") as ws:
        phone = Phone(ws)
        phone.walk_to(0.0, 1.6)
        phone.send({"type": "acquire", "room_version": 1, "id": "box"})
        reply = phone.send({"type": "select", "room_version": 1, "id": None})
        assert reply["id"] == "box"
        assert reply["rejected"]["code"] == "selection_held"
