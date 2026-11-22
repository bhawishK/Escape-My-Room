"""Preparing a drill from the headset (#234, part of #221): the commander chooses a room object; a
fire already made for it in this room is put into the session at once, else one is made and put
in when it's ready. Both devices see that a drill is being prepared; only the headset sees what.
WebSocket seam, real service, fixture generator."""

import json
from pathlib import Path
from typing import Any

from test_hazard_generation import GENERATOR, splat_room
from test_manipulation import error_code, open_socket
from test_session_hazards import made_hazard

from backend.hazard_generation import HazardAsset


def send(ws, message_type: str, **fields: Any) -> None:
    ws.send(json.dumps({"type": message_type} | fields))


def state_where(ws, predicate, tries: int = 200) -> dict[str, Any]:
    """The first state that matches; preparing a fire with the fixture generator takes seconds."""
    for _ in range(tries):
        message = json.loads(ws.recv(timeout=30))
        if message["type"] in ("welcome", "state") and predicate(message["state"]):
            return message["state"]
    raise AssertionError("No matching state arrived.")


def cache(data: Path, room: Path, entity: str) -> HazardAsset:
    """A fire already made for `entity` in this room, kept with the server's hazards."""
    asset = made_hazard(data, entity=entity)
    kept = data / "hazards" / "hazards" / asset.id / "hazard.json"
    cached = asset.model_copy(update={"room": room.name})
    kept.write_text(cached.model_dump_json(), encoding="utf-8")
    return cached


def test_a_fire_already_made_for_the_object_is_ready_at_once(start_service, tmp_path):
    room = splat_room(tmp_path)
    data = tmp_path / "data"
    cached = cache(data, room, "block")
    with (
        start_service(data, **GENERATOR, ESCAPE_ROOM_PREPARED_DIR=str(room)) as url,
        open_socket(url, "vr_solver") as headset,
        open_socket(url, "mobile_master") as phone,
    ):
        send(headset, "prepare_drill", room_version=1, entity="block")
        ready = state_where(headset, lambda s: (s["drill"] or {}).get("state") == "ready")
        drill = ready["drill"]
        assert drill["entity"] == "block" and drill["hazard"] == "catches fire"
        assert drill["job"] is None
        (hazard,) = ready["room"]["hazards"]
        assert hazard["id"] == drill["hazard_id"] and hazard["asset"] == cached.id
        assert hazard["playing"] is False
        # The phone knows a drill is coming, not what it will be.
        seen = state_where(phone, lambda s: (s["drill"] or {}).get("state") == "ready")
        assert seen["drill"] == {"state": "ready"}

        send(headset, "start_hazard", room_version=1, id=drill["hazard_id"])
        state_where(phone, lambda s: any(h["playing"] for h in s["room"]["hazards"]))


def test_without_one_a_fire_is_made_and_put_in_when_ready(start_service, tmp_path):
    room = splat_room(tmp_path)
    with (
        start_service(tmp_path / "data", **GENERATOR, ESCAPE_ROOM_PREPARED_DIR=str(room)) as url,
        open_socket(url, "vr_solver") as headset,
        open_socket(url, "mobile_master") as phone,
    ):
        send(headset, "prepare_drill", room_version=1, entity="block")
        preparing = state_where(headset, lambda s: (s["drill"] or {}).get("state") == "preparing")
        assert preparing["drill"]["job"]
        assert preparing["room"]["hazards"] == []
        assert state_where(phone, lambda s: s["drill"] is not None)["drill"] == {
            "state": "preparing"
        }

        ready = state_where(headset, lambda s: (s["drill"] or {}).get("state") == "ready")
        (hazard,) = ready["room"]["hazards"]
        assert hazard["id"] == ready["drill"]["hazard_id"] and hazard["hide"] == "block"

        # Made in this room, it is kept for the next drill on the same object.
        send(headset, "cancel_drill", room_version=1)
        state_where(headset, lambda s: s["drill"] is None and s["room"]["hazards"] == [])
        send(headset, "prepare_drill", room_version=1, entity="block")
        again = state_where(headset, lambda s: (s["drill"] or {}).get("state") == "ready", tries=20)
        assert again["drill"]["job"] is None
        assert again["room"]["hazards"][0]["asset"] == hazard["asset"]


def test_a_new_drill_replaces_the_one_before(start_service, tmp_path):
    room = splat_room(tmp_path)
    data = tmp_path / "data"
    cache(data, room, "block")
    with (
        start_service(data, **GENERATOR, ESCAPE_ROOM_PREPARED_DIR=str(room)) as url,
        open_socket(url, "vr_solver") as headset,
    ):
        send(headset, "prepare_drill", room_version=1, entity="block")
        first = state_where(headset, lambda s: (s["drill"] or {}).get("state") == "ready")
        send(headset, "prepare_drill", room_version=1, entity="block")
        second = state_where(
            headset,
            lambda s: (
                (s["drill"] or {}).get("state") == "ready"
                and s["drill"]["hazard_id"] != first["drill"]["hazard_id"]
            ),
        )
        assert len(second["room"]["hazards"]) == 1


def test_only_the_headset_prepares_a_drill_and_only_for_an_object_in_the_room(
    start_service, tmp_path
):
    room = splat_room(tmp_path)
    with (
        start_service(tmp_path / "data", **GENERATOR, ESCAPE_ROOM_PREPARED_DIR=str(room)) as url,
        open_socket(url, "vr_solver") as headset,
        open_socket(url, "mobile_master") as phone,
    ):
        send(phone, "prepare_drill", room_version=1, entity="block")
        assert error_code(phone) == "role_forbidden"
        send(headset, "prepare_drill", room_version=1, entity="no_such_thing")
        assert error_code(headset) == "unknown_entity"
        send(headset, "prepare_drill", room_version=2, entity="block")
        assert error_code(headset) == "room_version_mismatch"
