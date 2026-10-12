"""Client-visible acceptance checks for Issue #1 (not hardware evidence)."""

import json

import httpx
import pytest
from websockets.exceptions import InvalidStatus
from websockets.sync.client import connect


def create_session(url):
    response = httpx.post(f"{url}/api/sessions")
    response.raise_for_status()
    return response.json()["session_id"]


def join(url, session_id, role="mobile_master", source="webxr"):
    response = httpx.post(
        f"{url}/api/sessions/{session_id}/participants",
        json={"role": role, "tracking_source": source},
    )
    response.raise_for_status()
    return response.json()


def socket_url(url, session_id, identity):
    return (
        f"{url.replace('http://', 'ws://')}/api/sessions/{session_id}/ws"
        f"?participant_id={identity['participant_id']}"
    )


def open_socket(url, session_id, identity):
    return connect(
        socket_url(url, session_id, identity),
        subprotocols=["escape-my-room", identity["connection_token"]],
    )


def receive_until(ws, predicate):
    for _ in range(20):
        message = json.loads(ws.recv(timeout=2))
        if predicate(message):
            return message
    raise AssertionError("Expected client-visible event was not received")


def pose(generation, sequence=1, position=None, **overrides):
    message = {
        "type": "pose",
        "connection_generation": generation,
        "sequence": sequence,
        "tracking_status": "tracked",
        "reference_space": "local",
        "position": position or {"x": 0.25, "y": -0.1, "z": -0.5},
    }
    return message | overrides


def test_phone_pose_reaches_python_and_both_views(service_url):
    session_id = create_session(service_url)
    master = join(service_url, session_id)
    solver = join(service_url, session_id, "vr_solver")
    with open_socket(service_url, session_id, master) as phone:
        welcome = json.loads(phone.recv(timeout=2))
        assert welcome["type"] == "welcome"
        assert welcome["participant_id"] == master["participant_id"]
        with open_socket(service_url, session_id, solver) as headset:
            solver_welcome = json.loads(headset.recv(timeout=2))
            assert {p["role"] for p in solver_welcome["state"]["participants"]} == {
                "mobile_master",
                "vr_solver",
            }
            phone.send(json.dumps(pose(welcome["connection_generation"])))
            for view in (phone, headset):
                state = receive_until(
                    view,
                    lambda msg: (
                        msg.get("state", {}).get("marker", {}).get("tracking_status") == "tracked"
                    ),
                )["state"]
                assert state["marker"]["position"] == {"x": 0.25, "y": -0.1, "z": -0.5}
                assert state["marker"]["source"] == "webxr"


def test_solver_cannot_publish_master_pose(service_url):
    session_id = create_session(service_url)
    solver = join(service_url, session_id, "vr_solver")
    with open_socket(service_url, session_id, solver) as headset:
        welcome = json.loads(headset.recv(timeout=2))
        headset.send(json.dumps(pose(welcome["connection_generation"])))
        rejection = json.loads(headset.recv(timeout=2))
        assert rejection["type"] == "error"
        assert rejection["code"] == "role_forbidden"


@pytest.mark.parametrize(
    "override,code",
    [
        ({"connection_generation": 999}, "stale_connection"),
        ({"sequence": 1}, "stale_sequence"),
        ({"tracking_status": "simulated"}, "source_mismatch"),
        ({"position": {"x": "0.5", "y": 0.0, "z": 0.0}}, "invalid_message"),
        ({"position": {"x": float("inf"), "y": 0.0, "z": 0.0}}, "invalid_message"),
        ({"participant_id": "someone-else"}, "invalid_message"),
    ],
)
def test_rejected_pose_does_not_replace_last_accepted_position(service_url, override, code):
    session_id = create_session(service_url)
    master = join(service_url, session_id)
    with open_socket(service_url, session_id, master) as phone:
        generation = json.loads(phone.recv(timeout=2))["connection_generation"]
        phone.send(json.dumps(pose(generation)))
        accepted = json.loads(phone.recv(timeout=2))
        phone.send(json.dumps(pose(generation, sequence=2) | override))
        rejection = json.loads(phone.recv(timeout=2))
        assert rejection["type"] == "error"
        assert rejection["code"] == code
        # A new viewer observes the unchanged authoritative position.
        solver = join(service_url, session_id, "vr_solver")
        with open_socket(service_url, session_id, solver) as headset:
            state = json.loads(headset.recv(timeout=2))["state"]
            assert state["marker"] == accepted["state"]["marker"]


def test_two_sessions_keep_their_marker_and_participants_isolated(service_url):
    first = create_session(service_url)
    second = create_session(service_url)
    master_a = join(service_url, first)
    master_b = join(service_url, second, source="simulator")
    with open_socket(service_url, first, master_a) as a:
        gen_a = json.loads(a.recv(timeout=2))["connection_generation"]
        with open_socket(service_url, second, master_b) as b:
            gen_b = json.loads(b.recv(timeout=2))["connection_generation"]
            a.send(json.dumps(pose(gen_a)))
            assert json.loads(a.recv(timeout=2))["state"]["session_id"] == first
            b.send(
                json.dumps(
                    pose(
                        gen_b, position={"x": 2.0, "y": 0.0, "z": -1.0}, tracking_status="simulated"
                    )
                )
            )
            state_b = json.loads(b.recv(timeout=2))["state"]
            assert state_b["marker"]["position"] == {"x": 2.0, "y": 0.0, "z": -1.0}
            assert state_b["marker"]["source"] == "simulator"
            assert {p["participant_id"] for p in state_b["participants"]} == {
                master_b["participant_id"],
            }


def test_socket_credentials_cannot_cross_sessions(service_url):
    first = create_session(service_url)
    second = create_session(service_url)
    master = join(service_url, first)
    with pytest.raises(InvalidStatus) as denied:
        with open_socket(service_url, second, master):
            pass
    assert denied.value.response.status_code == 403


def test_missing_session_invalid_role_and_duplicate_role_have_actionable_errors(service_url):
    missing = httpx.post(
        f"{service_url}/api/sessions/not-a-session/participants", json={"role": "vr_solver"}
    )
    assert missing.status_code == 404
    session = create_session(service_url)
    invalid = httpx.post(
        f"{service_url}/api/sessions/{session}/participants", json={"role": "admin"}
    )
    assert invalid.status_code == 422
    join(service_url, session)
    duplicate = httpx.post(
        f"{service_url}/api/sessions/{session}/participants", json={"role": "mobile_master"}
    )
    assert duplicate.status_code == 409
    assert "occupied" in duplicate.json()["detail"]


def test_stopped_tracking_and_disconnect_remove_usable_marker(service_url):
    session = create_session(service_url)
    master = join(service_url, session)
    solver = join(service_url, session, "vr_solver")
    with open_socket(service_url, session, solver) as headset:
        headset.recv(timeout=2)
        with open_socket(service_url, session, master) as phone:
            gen = json.loads(phone.recv(timeout=2))["connection_generation"]
            phone.send(json.dumps(pose(gen)))
            receive_until(
                headset,
                lambda e: e.get("state", {}).get("marker", {}).get("tracking_status") == "tracked",
            )
            phone.recv(timeout=2)
            phone.send(
                json.dumps(
                    pose(gen, sequence=2, position=None)
                    | {
                        "tracking_status": "inactive",
                        "position": None,
                    }
                )
            )
            state = receive_until(
                headset,
                lambda e: e.get("state", {}).get("marker", {}).get("tracking_status") == "inactive",
            )["state"]
            assert state["marker"]["position"] is None
        disconnected = receive_until(
            headset, lambda e: e.get("state", {}).get("marker", {}).get("tracking_status") == "lost"
        )["state"]
        assert disconnected["marker"]["position"] is None
        assert [p["role"] for p in disconnected["participants"]] == ["vr_solver"]


def test_binary_message_is_rejected_without_killing_connection(service_url):
    session = create_session(service_url)
    master = join(service_url, session)
    with open_socket(service_url, session, master) as phone:
        generation = json.loads(phone.recv(timeout=2))["connection_generation"]
        phone.send(b"not-json-text")
        assert json.loads(phone.recv(timeout=2))["code"] == "invalid_message"
        phone.send(json.dumps(pose(generation)))
        assert json.loads(phone.recv(timeout=2))["state"]["marker"]["tracking_status"] == "tracked"


def test_replacement_connection_has_new_generation_and_no_old_usable_pose(service_url):
    session = create_session(service_url)
    master = join(service_url, session)
    with open_socket(service_url, session, master) as first:
        generation = json.loads(first.recv(timeout=2))["connection_generation"]
        first.send(json.dumps(pose(generation)))
        first.recv(timeout=2)
        with open_socket(service_url, session, master) as replacement:
            welcome = json.loads(replacement.recv(timeout=2))
            assert welcome["connection_generation"] == generation + 1
            assert welcome["state"]["marker"]["position"] is None
            replacement.send(json.dumps(pose(generation)))
            assert json.loads(replacement.recv(timeout=2))["code"] == "stale_connection"
            replacement.send(json.dumps(pose(welcome["connection_generation"])))
            assert json.loads(replacement.recv(timeout=2))["state"]["marker"]["position"] == {
                "x": 0.25,
                "y": -0.1,
                "z": -0.5,
            }
