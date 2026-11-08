"""Motion delivery under slow networks: newest state wins, and release is final; WebSocket seam."""

import json
import math
import time

import pytest
from websockets.sync.client import connect


def open_socket(url, role):
    return connect(f"{url.replace('http://', 'ws://')}/api/ws?role={role}")


def receive_until(ws, predicate, timeout=5):
    deadline = time.monotonic() + timeout
    seen = []
    while time.monotonic() < deadline:
        message = json.loads(ws.recv(timeout=deadline - time.monotonic()))
        seen.append(message)
        if predicate(message):
            return message, seen
    raise AssertionError("Expected message was not received")


def pose(sequence, x, z):
    """The phone at (x, z), 1.5 m up, facing the desk and looking 45° down."""
    return {
        "type": "pose",
        "sequence": sequence,
        "tracking_status": "tracked",
        "reference_space": "room",
        "position": {"x": x, "y": 1.5, "z": z},
        "heading": 0.0,
        "pitch": -math.pi / 4,
    }


def box(state):
    return next(entity for entity in state["room"]["entities"] if entity["id"] == "box")["position"]


def held(event):
    return event.get("type") == "state" and event["state"]["manipulation"] is not None


def released(event):
    return event.get("type") == "state" and event["state"]["manipulation"] is None


def test_a_slow_headset_gets_the_newest_motion_and_the_exact_release(start_service, tmp_path):
    with start_service(tmp_path, ESCAPE_ROOM_SIMULATED_DELAY_MS="200") as url:
        with (
            open_socket(url, "vr_solver") as headset,
            open_socket(url, "mobile_master") as phone,
        ):
            phone.send(json.dumps({"type": "select", "room_version": 1, "id": "box"}))
            phone.send(json.dumps(pose(1, 0.0, 1.6)))
            phone.send(json.dumps({"type": "acquire", "room_version": 1, "id": "box"}))
            identity = receive_until(phone, held)[0]["state"]["manipulation"]["id"]
            receive_until(headset, held)
            # A hundred moves in a burst, far faster than 200 ms each can be delivered.
            for step in range(1, 101):
                phone.send(json.dumps(pose(1 + step, step * 0.005, 1.6)))
            phone.send(json.dumps({"type": "release", "manipulation_id": identity}))
            final, burst = receive_until(headset, released)
            phone_final = receive_until(phone, released)[0]
    # Released at x = 0.5, the box lies 1.5 m ahead of the phone, on the floor.
    assert box(final["state"]) == pytest.approx({"x": 0.5, "y": 0.0, "z": 0.1})
    assert box(phone_final["state"]) == box(final["state"])
    assert len(burst) <= 10


def test_motion_sent_after_release_cannot_move_the_box(start_service, tmp_path):
    with start_service(tmp_path, ESCAPE_ROOM_SIMULATED_DELAY_MS="100") as url:
        with open_socket(url, "mobile_master") as phone:
            phone.send(json.dumps({"type": "select", "room_version": 1, "id": "box"}))
            phone.send(json.dumps(pose(1, 0.0, 1.6)))
            phone.send(json.dumps({"type": "acquire", "room_version": 1, "id": "box"}))
            identity = receive_until(phone, held)[0]["state"]["manipulation"]["id"]
            phone.send(json.dumps(pose(2, 0.3, 1.6)))
            phone.send(json.dumps({"type": "release", "manipulation_id": identity}))
            # Late motion, still on its way when the release was accepted.
            phone.send(json.dumps(pose(3, -0.3, 1.0)))
            phone.send(json.dumps(pose(4, -0.6, 0.5)))
            last, _ = receive_until(
                phone,
                lambda event: released(event) and event["state"]["marker"]["position"]["x"] == -0.6,
            )
    assert box(last["state"]) == pytest.approx({"x": 0.3, "y": 0.0, "z": 0.1})


def test_the_state_records_the_induced_delay(start_service, tmp_path):
    with start_service(tmp_path, ESCAPE_ROOM_SIMULATED_DELAY_MS="150") as url:
        with open_socket(url, "vr_solver") as headset:
            welcome = json.loads(headset.recv(timeout=2))
    assert welcome["state"]["delivery"] == {"simulated_delay_ms": 150}


def test_the_induced_delay_holds_back_every_state_not_just_the_first(start_service, tmp_path):
    with start_service(tmp_path, ESCAPE_ROOM_SIMULATED_DELAY_MS="200") as url:
        with open_socket(url, "mobile_master") as phone:
            phone.send(json.dumps({"type": "select", "room_version": 1, "id": "box"}))
            phone.recv(timeout=2)
            sent_at = {}
            delays = []
            for sequence in range(1, 21):
                sent_at[sequence] = time.monotonic()
                phone.send(json.dumps(pose(sequence, sequence * 0.01, 1.6)))
                # Steady movement, ten times a second, reading whatever has arrived meanwhile.
                deadline = time.monotonic() + 0.1
                while (left := deadline - time.monotonic()) > 0:
                    try:
                        event = json.loads(phone.recv(timeout=left))
                    except TimeoutError:
                        break
                    # Only states carrying one of these poses count; the server also sends others,
                    # such as physics starting (#160).
                    if event.get("type") == "state" and event["state"]["marker"]["position"]:
                        x = event["state"]["marker"]["position"]["x"]
                        delays.append(time.monotonic() - sent_at[round(x / 0.01)])
    assert delays
    assert min(delays) >= 0.18
