"""The commander's pointed spot, passed to the phone to draw a path to (#248).

Like the giant hand (#185): the headset sends where its pointing finger meets the floor, in room
metres; the phone is told, never the shared state. WebSocket seam."""

import json

from test_designer_hand import hands_received
from test_manipulation import error_code, open_socket, receive_until


def guide(sequence, spot):
    return {"type": "guide", "sequence": sequence, "spot": spot}


def test_the_pointed_spot_reaches_the_phone_and_clears(service_url):
    with (
        open_socket(service_url, "vr_solver") as headset,
        open_socket(service_url, "mobile_master") as phone,
    ):
        headset.recv(timeout=2)
        phone.recv(timeout=2)
        headset.send(json.dumps(guide(1, {"x": 1.5, "y": 0.0, "z": -0.8})))
        passed = receive_until(phone, lambda event: event["type"] == "guide")
        assert passed["spot"] == {"x": 1.5, "y": 0.0, "z": -0.8}

        headset.send(json.dumps(guide(2, None)))
        gone = receive_until(phone, lambda event: event["type"] == "guide")
        assert gone["spot"] is None
        # Not room state: the headset isn't sent it back, nor a hand.
        assert hands_received(headset, 0.3) == []


def test_only_the_headset_guides_and_its_sequence_must_grow(service_url):
    with (
        open_socket(service_url, "vr_solver") as headset,
        open_socket(service_url, "mobile_master") as phone,
    ):
        headset.recv(timeout=2)
        phone.recv(timeout=2)
        phone.send(json.dumps(guide(1, {"x": 0.0, "y": 0.0, "z": 0.0})))
        assert error_code(phone) == "role_forbidden"
        headset.send(json.dumps(guide(5, {"x": 0.0, "y": 0.0, "z": 0.0})))
        receive_until(phone, lambda event: event["type"] == "guide")
        headset.send(json.dumps(guide(5, None)))
        assert error_code(headset) == "stale_sequence"


def test_the_phone_is_told_the_spot_is_gone_when_the_headset_leaves(service_url):
    with open_socket(service_url, "mobile_master") as phone:
        phone.recv(timeout=2)
        with open_socket(service_url, "vr_solver") as headset:
            headset.recv(timeout=2)
            headset.send(json.dumps(guide(1, {"x": 1.0, "y": 0.0, "z": 1.0})))
            receive_until(phone, lambda event: event["type"] == "guide" and event["spot"])
        gone = receive_until(phone, lambda event: event["type"] == "guide")
        assert gone["spot"] is None
