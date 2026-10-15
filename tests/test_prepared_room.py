"""Prepared-room checks through the running service and the loader boundary."""

import json
import shutil
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from test_session_flow import open_socket, receive_until
from websockets.exceptions import ConnectionClosed

from backend.app import create_app
from backend.prepared_room import PreparedRoomError, load_prepared_room

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets" / "prepared-room"


def entities(state):
    return {entity["id"]: entity for entity in state["room"]["entities"]}


def test_service_publishes_one_room_to_both_devices(service_url):
    with open_socket(service_url, "mobile_master") as phone, open_socket(
        service_url, "vr_solver"
    ) as headset:
        phone_room = json.loads(phone.recv(timeout=2))["state"]["room"]
        headset_room = json.loads(headset.recv(timeout=2))["state"]["room"]
        assert phone_room["available"] is True
        assert phone_room["room_version"] == headset_room["room_version"] == 1
        assert phone_room["asset_url"] == "/assets/prepared-room/room.gltf"
        assert entities({"room": phone_room}) == entities({"room": headset_room})
        assert entities({"room": phone_room})["box"]["kind"] == "movable"
        assert entities({"room": phone_room})["box"]["selectable"] is True
        for name in ("floor", "desk", "cabinet"):
            assert entities({"room": phone_room})[name]["kind"] == "static"
            assert entities({"room": phone_room})[name]["selectable"] is False
        phone.send(json.dumps({"type": "room_loaded", "room_version": 1}))
        headset.send(json.dumps({"type": "room_loaded", "room_version": 1}))
        agreed = receive_until(
            headset,
            lambda event: event.get("state", {}).get("room", {}).get("loaded_by")
            == {"mobile_master": 1, "vr_solver": 1},
        )["state"]
        assert agreed["room"]["room_version"] == 1


def test_moving_the_box_does_not_move_the_room(service_url):
    with open_socket(service_url, "mobile_master") as phone, open_socket(
        service_url, "vr_solver"
    ) as headset:
        before = entities(json.loads(phone.recv(timeout=2))["state"])
        headset.recv(timeout=2)
        phone.send(
            json.dumps(
                {
                    "type": "entity_transform",
                    "id": "box",
                    "position": {"x": 0.25, "y": 0.0, "z": 0.1},
                }
            )
        )
        for view in (phone, headset):
            moved = entities(
                receive_until(
                    view,
                    lambda event: any(
                        entity["id"] == "box" and entity["position"]["x"] == 0.25
                        for entity in event.get("state", {}).get("room", {}).get("entities", [])
                    ),
                )["state"]
            )
            assert moved["box"]["position"] == {"x": 0.25, "y": 0.0, "z": 0.1}
            for name in ("floor", "desk", "cabinet"):
                assert moved[name]["position"] == before[name]["position"]


def test_static_furniture_move_is_rejected(service_url):
    with open_socket(service_url, "mobile_master") as phone, open_socket(
        service_url, "vr_solver"
    ) as headset:
        original = entities(json.loads(phone.recv(timeout=2))["state"])
        headset.recv(timeout=2)
        phone.send(
            json.dumps(
                {
                    "type": "entity_transform",
                    "id": "desk",
                    "position": {"x": 3.0, "y": 0.0, "z": 0.0},
                }
            )
        )
        assert (
            receive_until(phone, lambda event: event.get("code") == "entity_not_movable")["code"]
            == "entity_not_movable"
        )
        headset.send(json.dumps({"type": "room_loaded", "room_version": 1}))
        def solver_loaded(event):
            loaded = event.get("state", {}).get("room", {}).get("loaded_by", {})
            return loaded.get("vr_solver") == 1

        confirmed = entities(receive_until(headset, solver_loaded)["state"])
        assert confirmed["desk"]["position"] == original["desk"]["position"]
        assert confirmed["box"]["position"] == original["box"]["position"]


def test_wrong_room_version_is_removed_from_the_session(service_url):
    with open_socket(service_url, "mobile_master") as phone, open_socket(
        service_url, "vr_solver"
    ) as headset:
        phone.recv(timeout=2)
        headset.recv(timeout=2)
        phone.send(json.dumps({"type": "room_loaded", "room_version": 99}))
        assert (
            receive_until(phone, lambda event: event.get("code") == "room_version_mismatch")["code"]
            == "room_version_mismatch"
        )
        with pytest.raises(ConnectionClosed):
            phone.recv(timeout=2)
        remaining = receive_until(
            headset, lambda event: event.get("state", {}).get("mobile_connected") is False
        )["state"]
        assert remaining["vr_connected"] is True
        assert remaining["room"]["room_version"] == 1
        assert remaining["room"]["available"] is True


def test_room_asset_is_served(service_url):
    description = httpx.get(f"{service_url}/api/room", timeout=2)
    assert description.status_code == 200
    body = description.json()
    assert body["room_version"] == 1
    model = httpx.get(f"{service_url}{body['asset_url']}", timeout=2)
    assert model.status_code == 200
    assert len(model.json()["meshes"]) == 4
    geometry = httpx.get(f"{service_url}/assets/prepared-room/room.bin", timeout=2)
    assert geometry.status_code == 200
    assert geometry.content


def test_missing_asset_is_a_visible_room_failure(tmp_path):
    manifest = json.loads((ASSETS / "manifest.json").read_text(encoding="utf-8"))
    manifest["asset"] = "missing.gltf"
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    client = TestClient(create_app(tmp_path))
    response = client.get("/api/room")
    assert response.status_code == 503
    assert response.json()["detail"] == "Prepared room asset is missing."
    with client.websocket_connect("/api/ws?role=vr_solver") as headset, client.websocket_connect(
        "/api/ws?role=mobile_master"
    ) as phone:
        phone_room = phone.receive_json()["state"]["room"]
        headset_room = headset.receive_json()["state"]["room"]
        assert phone_room["available"] is False
        assert headset_room["available"] is False
        assert phone_room["error"] == headset_room["error"] == "Prepared room asset is missing."


def test_manifest_position_must_match_the_model(tmp_path):
    for name in ("manifest.json", "room.gltf", "room.bin"):
        shutil.copy(ASSETS / name, tmp_path / name)
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    manifest["entities"][1]["position"]["x"] = 2.5
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(PreparedRoomError, match="does not match the manifest position"):
        load_prepared_room(tmp_path)
