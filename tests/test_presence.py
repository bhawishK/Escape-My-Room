"""Each participant's place stays separate from the other person and from the furniture."""

import json
import math

from test_alignment import HEADSET_POSE, PHONE_POSE, alignment_from_pose
from test_session_flow import open_socket, receive_until

from backend.alignment import room_heading, xr_to_room
from backend.protocol import Position, PresenceMessage
from backend.sessions import PrototypeRoom


def presence(sequence=1, **overrides):
    return {
        "type": "presence",
        "sequence": sequence,
        "tracking_status": "tracked",
        "position": {"x": 0.0, "y": 1.5, "z": 1.6},
        "heading": 0.0,
    } | overrides


def participant(event, role):
    return event["state"]["participants"][role]


def test_confirmed_headsets_stand_on_the_floor_center_facing_the_desk():
    for position, orientation in (PHONE_POSE, HEADSET_POSE):
        alignment = alignment_from_pose(position, orientation)
        room = xr_to_room(alignment, position)
        assert abs(room.x) < 1e-9
        assert abs(room.z) < 1e-9
        assert abs(room.y - position.y) < 1e-9
        assert abs(room_heading(alignment, orientation)) < 1e-9


def test_a_left_turn_after_alignment_is_a_positive_heading():
    alignment = alignment_from_pose(*HEADSET_POSE)
    turned = (0.0, math.sin(0.4), 0.0, math.cos(0.4))
    assert abs(room_heading(alignment, turned) - 0.3) < 1e-9


def test_each_person_sees_the_other_and_cannot_replace_them(service_url):
    phone_place = presence(position={"x": 0.0, "y": 1.5, "z": 1.6}, heading=0.2)
    headset_place = presence(position={"x": 0.4, "y": 1.6, "z": -0.3}, heading=-0.5)
    with open_socket(service_url, "mobile_master") as phone:
        phone.recv(timeout=2)
        with open_socket(service_url, "vr_solver") as headset:
            headset.recv(timeout=2)
            phone.send(json.dumps(phone_place))
            seen = receive_until(
                headset,
                lambda event: participant(event, "mobile_master")["tracking_status"] == "tracked",
            )
            assert participant(seen, "mobile_master")["position"] == phone_place["position"]
            assert participant(seen, "mobile_master")["heading"] == phone_place["heading"]
            assert participant(seen, "vr_solver")["tracking_status"] == "inactive"
            headset.send(json.dumps(headset_place))
            both = receive_until(
                phone,
                lambda event: participant(event, "vr_solver")["tracking_status"] == "tracked",
            )
            assert participant(both, "vr_solver")["position"] == headset_place["position"]
            assert participant(both, "mobile_master")["position"] == phone_place["position"]


def test_presence_does_not_move_furniture_and_furniture_does_not_move_presence(service_url):
    with open_socket(service_url, "mobile_master") as phone:
        welcome = json.loads(phone.recv(timeout=2))["state"]
        box = next(entity for entity in welcome["room"]["entities"] if entity["id"] == "box")
        phone.send(json.dumps(presence()))
        message = json.loads(phone.recv(timeout=2))
        assert message.get("type") == "state", message
        placed = message["state"]
        still = next(entity for entity in placed["room"]["entities"] if entity["id"] == "box")
        assert still["position"] == box["position"]
        moved = {"x": box["position"]["x"] + 0.2, "y": 0.0, "z": box["position"]["z"]}
        phone.send(json.dumps({"type": "entity_transform", "id": "box", "position": moved}))
        after = receive_until(
            phone,
            lambda event: next(
                entity["position"]
                for entity in event.get("state", {}).get("room", {}).get("entities", [])
                if entity.get("id") == "box"
            )
            == moved,
        )["state"]
        assert after["participants"]["mobile_master"]["position"] == presence()["position"]
        assert after["participants"]["mobile_master"]["heading"] == 0.0


def test_leaving_clears_only_that_person(service_url):
    with open_socket(service_url, "vr_solver") as headset:
        headset.recv(timeout=2)
        headset.send(json.dumps(presence(position={"x": 0.2, "y": 1.6, "z": 0.0}, heading=0.4)))
        with open_socket(service_url, "mobile_master") as phone:
            phone.recv(timeout=2)
            phone.send(json.dumps(presence()))
            receive_until(
                headset,
                lambda event: participant(event, "mobile_master")["tracking_status"] == "tracked",
            )
        gone = receive_until(
            headset,
            lambda event: participant(event, "mobile_master")["tracking_status"] == "lost",
        )["state"]
        assert gone["participants"]["mobile_master"]["position"] is None
        assert gone["participants"]["vr_solver"]["tracking_status"] == "tracked"
        assert gone["participants"]["vr_solver"]["heading"] == 0.4


def test_a_tracked_presence_without_a_heading_is_rejected(service_url):
    with open_socket(service_url, "mobile_master") as phone:
        phone.recv(timeout=2)
        phone.send(json.dumps(presence(heading=None)))
        rejection = json.loads(phone.recv(timeout=2))
        assert rejection["type"] == "error"
        assert rejection["code"] == "invalid_message"


def test_a_quiet_person_turns_faint_without_another_message(service_url):
    with open_socket(service_url, "mobile_master") as phone:
        phone.recv(timeout=2)
        phone.send(json.dumps(presence()))
        tracked = receive_until(
            phone,
            lambda event: event.get("type") == "state"
            and participant(event, "mobile_master")["tracking_status"] == "tracked",
        )
        stale = json.loads(phone.recv(timeout=3))
    assert participant(stale, "mobile_master")["tracking_status"] == "stale"
    assert participant(stale, "mobile_master")["position"] == participant(tracked, "mobile_master")[
        "position"
    ]
    assert participant(stale, "mobile_master")["heading"] == 0.0


def test_a_quiet_participant_keeps_their_place_but_is_marked_stale():
    room = PrototypeRoom()
    room.accept_presence(
        "mobile_master",
        PresenceMessage(
            type="presence",
            sequence=1,
            tracking_status="tracked",
            position=Position(x=0.0, y=1.5, z=1.6),
            heading=0.2,
        ),
    )
    seen = room.presence_seen["mobile_master"]
    assert room.expire_presence(seen + 1.5) is False
    assert room.expire_presence(seen + 1.5 + 1e-6) is True
    stale = room.presence["mobile_master"]
    assert stale.tracking_status == "stale"
    assert stale.position is not None
    assert stale.position.x == 0.0
    assert stale.heading == 0.2
    assert room.expire_presence(seen + 5) is False
