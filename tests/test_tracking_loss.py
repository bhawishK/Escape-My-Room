"""When the phone's tracking fails mid-hold, the box stays put and is let go; WebSocket seam."""

import json
import math
import time

from websockets.sync.client import connect


def open_socket(url, role):
    return connect(f"{url.replace('http://', 'ws://')}/api/ws?role={role}")


def receive_until(ws, predicate, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        message = json.loads(ws.recv(timeout=deadline - time.monotonic()))
        if predicate(message):
            return message
    raise AssertionError("Expected message was not received")


def state_where(predicate):
    return lambda event: event.get("type") == "state" and predicate(event["state"])


def hold_ended_by(reason):
    return state_where(lambda state: (state["last_hold_end"] or {}).get("reason") == reason)


def box(state):
    return next(entity for entity in state["room"]["entities"] if entity["id"] == "box")[
        "position"
    ]


class Phone:
    """A connected phone that has selected the box, aiming 45° down from 1.5 m up."""

    def __init__(self, ws):
        self.ws = ws
        self.sequence = 0
        ws.recv(timeout=2)
        self.send({"type": "select", "room_version": 1, "id": "box"})

    def send(self, message):
        self.ws.send(json.dumps(message))
        return json.loads(self.ws.recv(timeout=2))

    def aim_from(self, x, z):
        self.sequence += 1
        return self.send(
            {
                "type": "pose",
                "sequence": self.sequence,
                "tracking_status": "tracked",
                "reference_space": "room",
                "position": {"x": x, "y": 1.5, "z": z},
                "heading": 0.0,
                "pitch": -math.pi / 4,
            }
        )["state"]

    def lose_tracking(self):
        self.sequence += 1
        return self.send(
            {
                "type": "pose",
                "sequence": self.sequence,
                "tracking_status": "lost",
                "reference_space": None,
                "position": None,
            }
        )["state"]

    def pick_up(self):
        return self.send({"type": "acquire", "room_version": 1, "id": "box"})


def test_lost_tracking_ends_the_hold_where_the_box_is(service_url):
    with (
        open_socket(service_url, "vr_solver") as headset,
        open_socket(service_url, "mobile_master") as ws,
    ):
        headset.recv(timeout=2)
        phone = Phone(ws)
        phone.aim_from(0.0, 1.6)
        phone.pick_up()
        placed = box(phone.aim_from(0.4, 1.6))
        lost = phone.lose_tracking()
        assert lost["manipulation"] is None
        assert box(lost) == placed
        seen = receive_until(
            headset, state_where(lambda state: state["marker"]["tracking_status"] == "lost")
        )
        assert seen["state"]["last_hold_end"] == {"entity": "box", "reason": "tracking_lost"}
        assert seen["state"]["manipulation"] is None
        assert box(seen["state"]) == placed


def test_a_phone_without_tracking_cannot_pick_up_until_tracked_again(service_url):
    with open_socket(service_url, "mobile_master") as ws:
        phone = Phone(ws)
        phone.aim_from(0.0, 1.6)
        phone.lose_tracking()
        assert phone.pick_up()["code"] == "not_tracked"
        phone.aim_from(0.0, 1.6)
        again = phone.pick_up()["state"]["manipulation"]
        assert again is not None
        phone.send({"type": "release", "manipulation_id": again["id"]})


def test_a_silent_phone_loses_its_hold_where_the_box_is(start_service, tmp_path):
    with start_service(tmp_path, ESCAPE_ROOM_HOLD_TIMEOUT_MS="500") as url:
        with (
            open_socket(url, "vr_solver") as headset,
            open_socket(url, "mobile_master") as ws,
        ):
            headset.recv(timeout=2)
            phone = Phone(ws)
            phone.aim_from(0.0, 1.6)
            phone.pick_up()
            placed = box(phone.aim_from(0.4, 1.6))
            # The phone stops sending, as a frozen or backgrounded page would.
            seen = receive_until(
                headset,
                hold_ended_by("silent"),
            )
            assert seen["state"]["manipulation"] is None
            assert box(seen["state"]) == placed


def test_an_interrupted_phone_lets_go_and_the_headset_can_tell(service_url):
    with (
        open_socket(service_url, "vr_solver") as headset,
        open_socket(service_url, "mobile_master") as ws,
    ):
        headset.recv(timeout=2)
        phone = Phone(ws)
        phone.aim_from(0.0, 1.6)
        identity = phone.pick_up()["state"]["manipulation"]["id"]
        placed = box(phone.aim_from(0.3, 1.6))
        # The page was hidden mid-hold, so the phone let go without the person choosing to.
        let_go = phone.send(
            {"type": "release", "manipulation_id": identity, "reason": "interrupted"}
        )["state"]
        assert let_go["manipulation"] is None
        assert box(let_go) == placed
        seen = receive_until(
            headset,
            hold_ended_by("interrupted"),
        )
        assert box(seen["state"]) == placed
