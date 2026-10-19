"""Public WebSocket checks for the single shared prototype room; not hardware evidence."""

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
    raise AssertionError("Expected public state was not received")


def pose(sequence=1, **overrides):
    return {
        "type": "pose",
        "sequence": sequence,
        "tracking_status": "tracked",
        "reference_space": "room",
        "position": {"x": 0.25, "y": -0.1, "z": -0.5},
    } | overrides


def test_phone_and_vr_connect_directly_and_share_accepted_state(service_url):
    with open_socket(service_url, "mobile_master") as phone:
        welcome = json.loads(phone.recv(timeout=2))
        assert welcome["type"] == "welcome"
        assert welcome["state"]["mobile_connected"] is True
        with open_socket(service_url, "vr_solver") as headset:
            state = json.loads(headset.recv(timeout=2))["state"]
            assert state["mobile_connected"] is True
            assert state["vr_connected"] is True
            phone.send(json.dumps(pose()))
            for view in (phone, headset):
                accepted = receive_until(
                    view,
                    lambda event: (
                        event.get("state", {}).get("marker", {}).get("tracking_status") == "tracked"
                    ),
                )["state"]
                assert accepted["marker"]["position"] == {"x": 0.25, "y": -0.1, "z": -0.5}


def test_vr_cannot_overwrite_phone_pose(service_url):
    with open_socket(service_url, "vr_solver") as headset:
        headset.recv(timeout=2)
        headset.send(json.dumps(pose()))
        rejection = json.loads(headset.recv(timeout=2))
        assert rejection["type"] == "error"
        assert rejection["code"] == "role_forbidden"


def test_old_pose_does_not_replace_current_position(service_url):
    with open_socket(service_url, "mobile_master") as phone:
        phone.recv(timeout=2)
        phone.send(json.dumps(pose()))
        phone.recv(timeout=2)
        phone.send(json.dumps(pose(position={"x": 4.0, "y": 0.0, "z": 0.0})))
        assert json.loads(phone.recv(timeout=2))["code"] == "stale_sequence"
        with open_socket(service_url, "vr_solver") as headset:
            assert json.loads(headset.recv(timeout=2))["state"]["marker"]["position"] == {
                "x": 0.25,
                "y": -0.1,
                "z": -0.5,
            }


@pytest.mark.parametrize(
    "override",
    [
        {"tracking_status": "simulated"},
        {"tracking_status": "emulated", "position": None},
        {"reference_space": "local"},
        {"reference_space": "local-floor"},
        {"position": {"x": "0.5", "y": 0.0, "z": 0.0}},
        {"position": {"x": float("inf"), "y": 0.0, "z": 0.0}},
        {"position": {"x": 101.0, "y": 0.0, "z": 0.0}},
        {"tracking_status": "lost"},
    ],
)
def test_invalid_or_simulated_pose_preserves_last_accepted_position(service_url, override):
    with open_socket(service_url, "mobile_master") as phone:
        phone.recv(timeout=2)
        phone.send(json.dumps(pose()))
        phone.recv(timeout=2)
        phone.send(json.dumps(pose(sequence=2, **override)))
        assert json.loads(phone.recv(timeout=2))["code"] == "invalid_message"
        with open_socket(service_url, "vr_solver") as headset:
            assert json.loads(headset.recv(timeout=2))["state"]["marker"]["position"] == {
                "x": 0.25,
                "y": -0.1,
                "z": -0.5,
            }


@pytest.mark.parametrize("raw", [b"not-json-text", "{malformed"])
def test_bad_frame_does_not_kill_connection(service_url, raw):
    with open_socket(service_url, "mobile_master") as phone:
        phone.recv(timeout=2)
        phone.send(raw)
        assert json.loads(phone.recv(timeout=2))["code"] == "invalid_message"
        phone.send(json.dumps(pose()))
        assert json.loads(phone.recv(timeout=2))["state"]["marker"]["tracking_status"] == "tracked"


def test_phone_disconnect_clears_marker_and_can_reconnect_directly(service_url):
    with open_socket(service_url, "vr_solver") as headset:
        headset.recv(timeout=2)
        with open_socket(service_url, "mobile_master") as phone:
            phone.recv(timeout=2)
            phone.send(json.dumps(pose()))
            receive_until(
                headset,
                lambda e: e.get("state", {}).get("marker", {}).get("tracking_status") == "tracked",
            )
        gone = receive_until(
            headset, lambda e: e.get("state", {}).get("mobile_connected") is False
        )["state"]
        assert gone["vr_connected"] is True
        assert gone["marker"]["position"] is None
        with open_socket(service_url, "mobile_master") as phone:
            assert json.loads(phone.recv(timeout=2))["state"]["marker"]["position"] is None
            phone.send(json.dumps(pose()))
            assert (
                json.loads(phone.recv(timeout=2))["state"]["marker"]["tracking_status"] == "tracked"
            )


def test_new_vr_tab_replaces_old_without_clearing_connected_status(service_url):
    with open_socket(service_url, "mobile_master") as phone:
        phone.recv(timeout=2)
        with open_socket(service_url, "vr_solver") as old_vr:
            old_vr.recv(timeout=2)
            with open_socket(service_url, "vr_solver") as new_vr:
                assert json.loads(new_vr.recv(timeout=2))["state"]["vr_connected"] is True
                phone.send(json.dumps(pose()))
                current = receive_until(
                    new_vr,
                    lambda e: (
                        e.get("state", {}).get("marker", {}).get("tracking_status") == "tracked"
                    ),
                )["state"]
                assert current["vr_connected"] is True
            assert (
                receive_until(phone, lambda e: e.get("state", {}).get("vr_connected") is False)[
                    "state"
                ]["mobile_connected"]
                is True
            )
