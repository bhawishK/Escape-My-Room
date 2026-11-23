"""Drills on new objects (#233, part of #221): something not in the room, such as a space heater,
is drawn, given a true-to-size mesh as its body, set on fire, and placed where it's asked for:
the body as furniture, the fire on it. Without its 3D animation, the body stands alone and the
drill says why. WebSocket and HTTP seams, real service, fixture generator."""

import json
from typing import Any

import httpx
from test_drill import send, state_where
from test_hazard_generation import GENERATOR, splat_room
from test_manipulation import open_socket


def prepare(ws, **target: Any) -> None:
    send(ws, "prepare_drill", room_version=1, **target)


def ready(ws) -> dict[str, Any]:
    return state_where(
        ws, lambda s: (s["drill"] or {}).get("state") in ("ready", "failed"), tries=400
    )


def test_a_new_object_is_made_placed_near_what_is_named_and_set_on_fire(start_service, tmp_path):
    room = splat_room(tmp_path)
    with (
        start_service(tmp_path / "data", **GENERATOR, ESCAPE_ROOM_PREPARED_DIR=str(room)) as url,
        open_socket(url, "vr_solver") as headset,
    ):
        prepare(headset, description="a space heater", near="block")
        preparing = state_where(headset, lambda s: (s["drill"] or {}).get("state") == "preparing")
        assert preparing["drill"]["entity"] is None
        assert preparing["drill"]["description"] == "a space heater"

        done = ready(headset)
        drill = done["drill"]
        assert drill["state"] == "ready", drill
        (hazard,) = done["room"]["hazards"]
        body = next(e for e in done["room"]["entities"] if e["id"] == hazard["hide"])
        # Its body is placed as furniture, true to size, near the block.
        assert body["furniture"] and body["furniture"].startswith("hzb_")
        block = next(e for e in done["room"]["entities"] if e["id"] == "block")
        apart = (
            (body["position"]["x"] - block["position"]["x"]) ** 2
            + (body["position"]["z"] - block["position"]["z"]) ** 2
        ) ** 0.5
        assert 0.4 < apart < 2.0
        # The fire is moved onto it.
        x, _, z = hazard["placement"]["position"]
        assert abs(x - body["position"]["x"]) < 1.0 and abs(z - body["position"]["z"]) < 1.0
        # Its mesh is served, and not offered among the furniture.
        assert (
            httpx.get(f"{url}/api/hazards/{hazard['asset']}/body.glb", timeout=5).status_code == 200
        )
        listed = [
            item["id"] for item in httpx.get(f"{url}/api/furniture", timeout=5).json()["items"]
        ]
        assert body["furniture"] not in listed

        # Called off, the body goes with the fire.
        send(headset, "cancel_drill", room_version=1)
        gone = state_where(headset, lambda s: s["drill"] is None)
        assert not any(e["id"] == body["id"] for e in gone["room"]["entities"])
        assert gone["room"]["hazards"] == []

        # Asked for again, the same new object's fire is ready at once.
        prepare(headset, description="A space heater", near="block")
        again = state_where(headset, lambda s: (s["drill"] or {}).get("state") == "ready", tries=40)
        assert again["drill"]["job"] is None
        assert again["room"]["hazards"][0]["asset"] == hazard["asset"]


def test_without_its_animation_the_body_stands_alone_and_the_drill_says_why(
    start_service, tmp_path
):
    room = splat_room(tmp_path)
    with (
        start_service(
            tmp_path / "data",
            **GENERATOR,
            ESCAPE_ROOM_FIXTURE_GENERATOR_FAIL="animate",
            ESCAPE_ROOM_PREPARED_DIR=str(room),
        ) as url,
        open_socket(url, "vr_solver") as headset,
    ):
        prepare(headset, description="a space heater")
        done = ready(headset)
        drill = done["drill"]
        assert drill["state"] == "ready"
        assert drill["error"].startswith("Only its shape is shown")
        assert done["room"]["hazards"] == []
        assert any((e.get("furniture") or "").startswith("hzb_") for e in done["room"]["entities"])


def test_a_drill_names_a_room_object_or_a_new_one_not_both(start_service, tmp_path):
    room = splat_room(tmp_path)
    with (
        start_service(tmp_path / "data", **GENERATOR, ESCAPE_ROOM_PREPARED_DIR=str(room)) as url,
        open_socket(url, "vr_solver") as headset,
    ):
        prepare(headset, entity="block", description="a space heater")
        message = json.loads(headset.recv(timeout=5))
        while message["type"] != "error":
            message = json.loads(headset.recv(timeout=5))
        assert message["code"] == "invalid_message"
