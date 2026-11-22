"""Hazards in the shared session (#229, part of #221): the headset adds, starts, stops and removes
a finished hazard; both devices see it in their state, with the same start time on the server's
clock. WebSocket seam, real service; the hazard is one already made, kept on disk.
"""

import json
import time
from pathlib import Path
from typing import Any

import httpx
from test_manipulation import error_code, open_socket, receive_until

from backend.furniture_generation import fixture_splat
from backend.hazard_generation import HazardAsset, HazardTarget
from backend.hazard_placement import Placement

ASSET = "hz_0123abcd"


def made_hazard(
    data: Path, asset_id: str = ASSET, frames: int = 4, entity: str = "box"
) -> HazardAsset:
    """A finished hazard, kept where hazard jobs keep theirs, on a room object (default: box)."""
    asset = HazardAsset(
        id=asset_id,
        target=HazardTarget(entity=entity),
        hazard="catches fire",
        frames=frames,
        frames_per_second=16.0,
        frame_url=f"/api/hazards/{asset_id}/frames/{{n}}.spz",
        check=[0.7, 0.7, 0.7],
        size_bytes=1000,
        placement=Placement(position=(0.1, 0.0, -0.5), turn=0.5, scale=2.0, hide=entity),
        seconds=frames / 16.0,
    )
    kept = data / "hazards" / "hazards" / asset_id
    (kept / "frames").mkdir(parents=True)
    for number in range(frames):
        (kept / "frames" / f"{number:03d}.spz").write_bytes(fixture_splat(number))
    (kept / "hazard.json").write_text(asset.model_dump_json(), encoding="utf-8")
    return asset


def send(ws, message_type: str, **fields: Any) -> None:
    ws.send(json.dumps({"type": message_type} | fields))


def hazards_in(ws, predicate) -> list[dict[str, Any]]:
    """The hazards of the first state that matches."""
    event = receive_until(
        ws,
        lambda event: (
            event["type"] in ("welcome", "state") and predicate(event["state"]["room"]["hazards"])
        ),
    )
    return event["state"]["room"]["hazards"]


def test_a_hazard_the_headset_adds_is_in_both_devices_state_and_its_frames_are_served(
    start_service, tmp_path
):
    asset = made_hazard(tmp_path)
    with (
        start_service(tmp_path) as url,
        open_socket(url, "vr_solver") as headset,
        open_socket(url, "mobile_master") as phone,
    ):
        hazards_in(phone, lambda hazards: hazards == [])
        send(headset, "add_hazard", room_version=1, asset=ASSET)
        for device in (headset, phone):
            (hazard,) = hazards_in(device, lambda hazards: len(hazards) == 1)
            assert hazard["id"] == "hazard_1"
            assert hazard["asset"] == ASSET
            assert hazard["hazard"] == "catches fire"
            assert hazard["frames"] == 4 and hazard["frames_per_second"] == 16.0
            assert hazard["placement"] == asset.placement.model_dump(mode="json")  # type: ignore[union-attr]
            assert hazard["hide"] == "box"
            assert hazard["playing"] is False and hazard["started_at"] is None
        frame = httpx.get(url + hazard["frame_url"].format(n=3), timeout=5)
        assert frame.status_code == 200


def test_start_gives_both_devices_the_same_start_time_a_moment_ahead(start_service, tmp_path):
    made_hazard(tmp_path)
    with (
        start_service(tmp_path) as url,
        open_socket(url, "vr_solver") as headset,
        open_socket(url, "mobile_master") as phone,
    ):
        send(headset, "add_hazard", room_version=1, asset=ASSET)
        hazards_in(phone, lambda hazards: len(hazards) == 1)
        asked = time.time() * 1000
        send(headset, "start_hazard", room_version=1, id="hazard_1")
        starts = []
        for device in (headset, phone):
            event = receive_until(
                device,
                lambda event: (
                    event["type"] == "state"
                    and any(hazard["playing"] for hazard in event["state"]["room"]["hazards"])
                ),
            )
            (hazard,) = event["state"]["room"]["hazards"]
            starts.append(hazard["started_at"])
            # Each state carries the server's clock, so a device can set its own against it.
            assert abs(event["state"]["server_time_ms"] - time.time() * 1000) < 2000
        assert starts[0] == starts[1]
        # Far enough ahead for both devices to have the frames ready, and not much more.
        assert asked + 500 <= starts[0] <= asked + 3000


def test_stop_and_remove_clear_it(start_service, tmp_path):
    made_hazard(tmp_path)
    with (
        start_service(tmp_path) as url,
        open_socket(url, "vr_solver") as headset,
        open_socket(url, "mobile_master") as phone,
    ):
        send(headset, "add_hazard", room_version=1, asset=ASSET)
        send(headset, "start_hazard", room_version=1, id="hazard_1")
        hazards_in(phone, lambda hazards: len(hazards) == 1 and hazards[0]["playing"])
        send(headset, "stop_hazard", room_version=1, id="hazard_1")
        (stopped,) = hazards_in(
            phone, lambda hazards: len(hazards) == 1 and not hazards[0]["playing"]
        )
        assert stopped["started_at"] is None
        send(headset, "remove_hazard", room_version=1, id="hazard_1")
        hazards_in(phone, lambda hazards: hazards == [])
        hazards_in(headset, lambda hazards: hazards == [])


def test_the_phone_cannot_add_start_stop_or_remove_one(start_service, tmp_path):
    made_hazard(tmp_path)
    with (
        start_service(tmp_path) as url,
        open_socket(url, "vr_solver") as headset,
        open_socket(url, "mobile_master") as phone,
    ):
        send(phone, "add_hazard", room_version=1, asset=ASSET)
        assert error_code(phone) == "role_forbidden"
        send(headset, "add_hazard", room_version=1, asset=ASSET)
        hazards_in(phone, lambda hazards: len(hazards) == 1)
        for message_type in ("start_hazard", "stop_hazard", "remove_hazard"):
            send(phone, message_type, room_version=1, id="hazard_1")
            assert error_code(phone) == "role_forbidden"
        send(headset, "stop_hazard", room_version=1, id="hazard_1")
        (hazard,) = hazards_in(headset, lambda hazards: len(hazards) == 1)
        assert hazard["playing"] is False


def test_unknown_hazards_and_an_old_room_are_refused(start_service, tmp_path):
    made_hazard(tmp_path)
    with start_service(tmp_path) as url, open_socket(url, "vr_solver") as headset:
        send(headset, "add_hazard", room_version=1, asset="hz_ffffffff")
        assert error_code(headset) == "unknown_hazard"
        send(headset, "add_hazard", room_version=1, asset="../../secret")
        assert error_code(headset) in ("unknown_hazard", "invalid_message")
        send(headset, "start_hazard", room_version=1, id="hazard_9")
        assert error_code(headset) == "unknown_hazard"
        send(headset, "add_hazard", room_version=2, asset=ASSET)
        assert error_code(headset) == "room_version_mismatch"
