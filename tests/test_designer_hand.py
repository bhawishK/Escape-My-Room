"""The designer's hand in the dollhouse, passed to the phone as a giant hand (#185).

WebSocket seam."""

import json
import time

from test_manipulation import error_code, open_socket, receive_until


def hand(sequence, position, length=None):
    return {"type": "designer_hand", "sequence": sequence, "position": position, "length": length}


def hands_received(ws, seconds):
    """Every designer_hand message the device is sent within `seconds`, in order."""
    seen = []
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            event = json.loads(ws.recv(timeout=max(0.01, deadline - time.monotonic())))
        except TimeoutError:
            break
        if event.get("type") == "designer_hand":
            seen.append(event)
    return seen


def test_the_headsets_hand_reaches_the_phone_and_never_the_shared_state(service_url):
    with (
        open_socket(service_url, "vr_solver") as headset,
        open_socket(service_url, "mobile_master") as phone,
    ):
        headset.recv(timeout=2)
        phone.recv(timeout=2)
        # A 19 cm hand in a twentieth-size dollhouse is 3.8 m long in the room.
        headset.send(json.dumps(hand(1, {"x": 0.5, "y": 1.2, "z": -0.4}, length=3.8)))

        passed = receive_until(phone, lambda event: event["type"] == "designer_hand")
        assert passed["position"] == {"x": 0.5, "y": 1.2, "z": -0.4}
        assert passed["length"] == 3.8
        # It isn't room state, and the headset isn't sent its own hand back.
        assert hands_received(headset, 0.3) == []

        headset.send(json.dumps(hand(2, None)))
        gone = receive_until(phone, lambda event: event["type"] == "designer_hand")
        assert gone["position"] is None


def test_hands_sent_faster_than_twenty_a_second_reach_the_phone_at_most_that_often(service_url):
    with (
        open_socket(service_url, "vr_solver") as headset,
        open_socket(service_url, "mobile_master") as phone,
    ):
        headset.recv(timeout=2)
        phone.recv(timeout=2)
        for sequence in range(1, 11):
            headset.send(json.dumps(hand(sequence, {"x": 0.1 * sequence, "y": 1.0, "z": 0.0})))
        # Taking the hand away always arrives, however soon after.
        headset.send(json.dumps(hand(11, None)))

        seen = hands_received(phone, 0.5)
        positions = [event["position"] for event in seen]
        assert 1 <= len([position for position in positions if position]) <= 2
        assert positions[-1] is None


def test_only_the_headset_sends_a_hand_and_its_sequence_must_grow(service_url):
    with (
        open_socket(service_url, "mobile_master") as phone,
        open_socket(service_url, "vr_solver") as headset,
    ):
        phone.recv(timeout=2)
        headset.recv(timeout=2)
        phone.send(json.dumps(hand(1, {"x": 0.0, "y": 1.0, "z": 0.0})))
        assert error_code(phone) == "role_forbidden"

        headset.send(json.dumps(hand(5, {"x": 0.0, "y": 1.0, "z": 0.0})))
        headset.send(json.dumps(hand(5, {"x": 0.0, "y": 1.0, "z": 0.0})))
        assert error_code(headset) == "stale_sequence"


def test_the_phone_is_told_the_hand_is_gone_when_the_headset_leaves(service_url):
    with open_socket(service_url, "mobile_master") as phone:
        phone.recv(timeout=2)
        with open_socket(service_url, "vr_solver") as headset:
            headset.recv(timeout=2)
            headset.send(json.dumps(hand(1, {"x": 0.5, "y": 1.2, "z": -0.4})))
            receive_until(phone, lambda event: event["type"] == "designer_hand")

        gone = receive_until(phone, lambda event: event["type"] == "designer_hand")
        assert gone["position"] is None


def test_a_headset_replaced_by_a_new_tab_takes_its_hand_off_the_phone(service_url):
    with open_socket(service_url, "mobile_master") as phone:
        phone.recv(timeout=2)
        with open_socket(service_url, "vr_solver") as old:
            old.recv(timeout=2)
            old.send(json.dumps(hand(1, {"x": 0.5, "y": 1.2, "z": -0.4})))
            receive_until(phone, lambda event: event["type"] == "designer_hand")
            with open_socket(service_url, "vr_solver") as new:
                new.recv(timeout=2)
                gone = receive_until(phone, lambda event: event["type"] == "designer_hand")
                assert gone["position"] is None
