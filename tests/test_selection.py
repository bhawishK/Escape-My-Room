"""The phone's private object selection, checked over the public WebSocket seam."""

import json

import pytest
from websockets.sync.client import connect


def open_socket(url, role):
    return connect(f"{url.replace('http://', 'ws://')}/api/ws?role={role}")


def select(entity_id, room_version=1):
    return json.dumps({"type": "select", "room_version": room_version, "id": entity_id})


def test_phone_selects_the_movable_box(service_url):
    with open_socket(service_url, "mobile_master") as phone:
        phone.recv(timeout=2)
        phone.send(select("box"))
        assert json.loads(phone.recv(timeout=2)) == {
            "type": "selection",
            "id": "box",
            "rejected": None,
        }


@pytest.mark.parametrize(
    ("entity_id", "room_version", "code"),
    [
        ("desk", 1, "entity_not_selectable"),
        ("floor", 1, "entity_not_selectable"),
        ("ghost", 1, "unknown_entity"),
        ("box", 2, "room_version_mismatch"),
    ],
)
def test_ineligible_selection_is_refused_and_keeps_the_current_one(
    service_url, entity_id, room_version, code
):
    with open_socket(service_url, "mobile_master") as phone:
        phone.recv(timeout=2)
        phone.send(select("box"))
        phone.recv(timeout=2)
        phone.send(select(entity_id, room_version))
        reply = json.loads(phone.recv(timeout=2))
        assert reply["type"] == "selection"
        assert reply["id"] == "box"
        assert reply["rejected"]["code"] == code
        assert reply["rejected"]["message"]


def test_phone_deselects(service_url):
    with open_socket(service_url, "mobile_master") as phone:
        phone.recv(timeout=2)
        phone.send(select("box"))
        phone.recv(timeout=2)
        phone.send(select(None))
        assert json.loads(phone.recv(timeout=2)) == {
            "type": "selection",
            "id": None,
            "rejected": None,
        }


def box_position(state):
    return next(entity for entity in state["room"]["entities"] if entity["id"] == "box")[
        "position"
    ]


def test_selection_stays_private_and_moves_nothing(service_url):
    with open_socket(service_url, "vr_solver") as headset:
        before = json.loads(headset.recv(timeout=2))["state"]
        with open_socket(service_url, "mobile_master") as phone:
            phone.recv(timeout=2)
            joined = json.loads(headset.recv(timeout=2))["state"]
            phone.send(select("box"))
            phone.recv(timeout=2)
            with pytest.raises(TimeoutError):
                headset.recv(timeout=0.5)
            # The next shared state, sent while the box is selected, says nothing about it.
            phone.send(json.dumps({"type": "room_loaded", "room_version": 1}))
            shared = json.loads(headset.recv(timeout=2))["state"]
    assert "selection" not in json.dumps(shared)
    assert shared["revision"] == joined["revision"] + 1
    assert box_position(shared) == box_position(before)


def test_headset_cannot_select(service_url):
    with open_socket(service_url, "vr_solver") as headset:
        headset.recv(timeout=2)
        headset.send(select("box"))
        assert json.loads(headset.recv(timeout=2))["code"] == "role_forbidden"


def test_reconnecting_phone_starts_without_a_selection(service_url):
    with open_socket(service_url, "mobile_master") as phone:
        phone.recv(timeout=2)
        phone.send(select("box"))
        phone.recv(timeout=2)
    with open_socket(service_url, "mobile_master") as phone:
        phone.recv(timeout=2)
        phone.send(select("ghost"))
        assert json.loads(phone.recv(timeout=2))["id"] is None
