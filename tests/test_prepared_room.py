"""Prepared-room checks through the running service and the loader boundary."""

import json
import shutil
import struct
from collections.abc import Callable
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
MULTI = ROOT / "assets" / "multi-asset-room"
FRAME = {"units": "meters", "frame": "y_up_right_handed", "quaternion_order": "xyzw"}
IDENTITY = {"x": 0.0, "y": 0.0, "z": 0.0, "w": 1.0}


def entities(state):
    return {entity["id"]: entity for entity in state["room"]["entities"]}


def copy_room(source: Path, target: Path) -> Path:
    shutil.copytree(source, target, ignore=shutil.ignore_patterns("*.py"))
    return target


def edit_manifest(directory: Path, change: Callable[[dict], None]) -> None:
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    change(manifest)
    (directory / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


def edit_glb(path: Path, change: Callable[[dict], None]) -> None:
    data = path.read_bytes()
    json_length = struct.unpack_from("<I", data, 12)[0]
    document = json.loads(data[20 : 20 + json_length])
    change(document)
    text = json.dumps(document).encode("utf-8")
    text += b" " * (-len(text) % 4)
    binary = data[20 + json_length :]
    path.write_bytes(
        struct.pack("<4sII", b"glTF", 2, 20 + len(text) + len(binary))
        + struct.pack("<II", len(text), 0x4E4F534A)
        + text
        + binary
    )


def node(document: dict, name: str) -> dict:
    return next(item for item in document["nodes"] if item.get("name") == name)


def test_service_publishes_one_room_to_both_devices(service_url):
    with open_socket(service_url, "mobile_master") as phone, open_socket(
        service_url, "vr_solver"
    ) as headset:
        phone_room = json.loads(phone.recv(timeout=2))["state"]["room"]
        headset_room = json.loads(headset.recv(timeout=2))["state"]["room"]
        assert phone_room["available"] is True
        assert phone_room["room_version"] == headset_room["room_version"] == 1
        assert {key: phone_room[key] for key in FRAME} == FRAME
        assert entities({"room": phone_room}) == entities({"room": headset_room})
        for entity in phone_room["entities"]:
            assert entity["asset_url"] == "/assets/prepared-room/room.gltf"
            assert entity["rotation"] == IDENTITY
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
    model = httpx.get(f"{service_url}{body['entities'][0]['asset_url']}", timeout=2)
    assert model.status_code == 200
    assert len(model.json()["meshes"]) == 4
    geometry = httpx.get(f"{service_url}/assets/prepared-room/room.bin", timeout=2)
    assert geometry.status_code == 200
    assert geometry.content


def test_multi_asset_room_reaches_both_devices(multi_asset_service_url):
    url = multi_asset_service_url
    with open_socket(url, "mobile_master") as phone, open_socket(url, "vr_solver") as headset:
        phone_room = json.loads(phone.recv(timeout=2))["state"]["room"]
        headset_room = receive_until(
            headset, lambda event: event.get("state", {}).get("vr_connected") is True
        )["state"]["room"]
        assert phone_room["available"] is True
        assert phone_room["room_version"] == headset_room["room_version"] == 1
        assert {key: phone_room[key] for key in FRAME} == FRAME
        assert entities({"room": phone_room}) == entities({"room": headset_room})
        room = entities({"room": phone_room})
        assert list(room) == ["floor", "table", "mug", "book"]
        assert {name for name, entity in room.items() if entity["kind"] == "movable"} == {
            "mug",
            "book",
        }
        for name in ("floor", "table"):
            assert room[name]["selectable"] is False
        for name in ("mug", "book"):
            assert room[name]["selectable"] is True
        assert len({entity["asset_url"] for entity in room.values()}) == 4
        assert room["book"]["rotation"]["y"] == pytest.approx(0.258819, abs=1e-6)
        assert room["mug"]["label"] == "Mug"
        phone.send(json.dumps({"type": "room_loaded", "room_version": 1}))
        headset.send(json.dumps({"type": "room_loaded", "room_version": 1}))
        receive_until(
            headset,
            lambda event: event.get("state", {}).get("room", {}).get("loaded_by")
            == {"mobile_master": 1, "vr_solver": 1},
        )


def test_moving_one_generated_object_leaves_the_others(multi_asset_service_url):
    url = multi_asset_service_url
    with open_socket(url, "mobile_master") as phone, open_socket(url, "vr_solver") as headset:
        before = entities(json.loads(phone.recv(timeout=2))["state"])
        target = {"x": 0.1, "y": 0.75, "z": -0.8}
        phone.send(json.dumps({"type": "entity_transform", "id": "mug", "position": target}))
        for view in (phone, headset):
            moved = entities(
                receive_until(
                    view,
                    lambda event: any(
                        entity["id"] == "mug" and entity["position"] == target
                        for entity in event.get("state", {}).get("room", {}).get("entities", [])
                    ),
                )["state"]
            )
            assert moved["mug"]["rotation"] == before["mug"]["rotation"]
            for name in ("floor", "table", "book"):
                assert moved[name] == before[name]
        phone.send(
            json.dumps({"type": "entity_transform", "id": "table", "position": target})
        )
        assert receive_until(phone, lambda event: "code" in event)["code"] == "entity_not_movable"


def test_each_generated_asset_is_served(multi_asset_service_url):
    body = httpx.get(f"{multi_asset_service_url}/api/room", timeout=2).json()
    for entity in body["entities"]:
        asset = httpx.get(f"{multi_asset_service_url}{entity['asset_url']}", timeout=2)
        assert asset.status_code == 200
        assert asset.content[:4] == b"glTF"


@pytest.mark.parametrize(
    ("source", "asset", "message"),
    [
        (ASSETS, "room.gltf", "Prepared room asset room.gltf is missing."),
        (MULTI, "mug.glb", "Prepared room asset mug.glb is missing."),
    ],
)
def test_missing_asset_is_a_visible_room_failure(tmp_path, source, asset, message):
    directory = copy_room(source, tmp_path / "room")
    (directory / asset).unlink()
    client = TestClient(create_app(directory))
    response = client.get("/api/room")
    assert response.status_code == 503
    assert response.json()["detail"] == message
    with client.websocket_connect("/api/ws?role=vr_solver") as headset, client.websocket_connect(
        "/api/ws?role=mobile_master"
    ) as phone:
        phone_room = phone.receive_json()["state"]["room"]
        headset_room = headset.receive_json()["state"]["room"]
        assert phone_room["available"] is False
        assert headset_room["available"] is False
        assert phone_room["entities"] == []
        assert phone_room["error"] == headset_room["error"] == message


def test_manifest_position_must_match_the_model(tmp_path):
    directory = copy_room(ASSETS, tmp_path / "room")
    edit_manifest(directory, lambda manifest: manifest["entities"][1]["position"].update(x=2.5))
    with pytest.raises(PreparedRoomError, match="does not match the manifest position"):
        load_prepared_room(directory)


def test_legacy_room_still_needs_exactly_one_movable_entity(tmp_path):
    directory = copy_room(ASSETS, tmp_path / "room")
    edit_manifest(
        directory,
        lambda manifest: manifest["entities"][1].update(kind="movable", selectable=True),
    )
    with pytest.raises(PreparedRoomError, match="manifest is invalid"):
        load_prepared_room(directory)


def corrupt(path: Path) -> None:
    path.write_bytes(path.read_bytes()[:40])


def unplace_mug(document: dict) -> None:
    node(document, "mug")["translation"] = [0.25, 0.75, -0.95]


def nest_slab(directory: Path) -> None:
    def add(manifest: dict) -> None:
        floor = dict(manifest["entities"][0])
        manifest["entities"].append(floor | {"id": "slab", "node": "floor_slab"})

    edit_manifest(directory, add)


@pytest.mark.parametrize(
    ("damage", "message"),
    [
        (lambda d: corrupt(d / "book.glb"), "book.glb could not be read"),
        (lambda d: edit_glb(d / "mug.glb", unplace_mug), "node mug in mug.glb is transformed"),
        (
            lambda d: edit_glb(d / "mug.glb", lambda g: node(g, "mug_handle").pop("rotation")),
            "mug geometry does not match its size",
        ),
        (
            lambda d: edit_manifest(d, lambda m: m["entities"][3]["size"].update(width=0.3)),
            "book geometry does not match its size",
        ),
        (
            lambda d: edit_glb(d / "mug.glb", lambda g: g["meshes"][0].update(name="mug")),
            "mug.glb is missing mug",
        ),
        (lambda d: edit_manifest(d, lambda m: m["entities"][2].update(node="cup")), "missing mug"),
        (nest_slab, "slab is nested inside floor"),
        (
            lambda d: edit_manifest(d, lambda m: m["entities"][1].update(selectable=True)),
            "manifest is invalid",
        ),
        (lambda d: edit_manifest(d, lambda m: m.update(frame="z_up")), "manifest is invalid"),
        (
            lambda d: edit_manifest(d, lambda m: m["entities"][3]["rotation"].update(w=2.0)),
            "manifest is invalid",
        ),
        (
            lambda d: edit_manifest(d, lambda m: m["entities"][2].update(asset="../mug.glb")),
            "manifest is invalid",
        ),
    ],
)
def test_generated_room_rejects_assets_that_disagree_with_the_manifest(tmp_path, damage, message):
    directory = copy_room(MULTI, tmp_path / "room")
    damage(directory)
    with pytest.raises(PreparedRoomError, match=message):
        load_prepared_room(directory)


def test_generated_room_rotation_is_normalized(tmp_path):
    directory = copy_room(MULTI, tmp_path / "room")
    edit_manifest(
        directory,
        lambda manifest: manifest["entities"][3]["rotation"].update(y=0.2589, w=0.9661),
    )
    rotation = load_prepared_room(directory).entities[3].rotation
    assert rotation.x**2 + rotation.y**2 + rotation.z**2 + rotation.w**2 == pytest.approx(1.0)


DESK_MARKER = {
    "id": 0,
    "label": "Desk front",
    "size": 0.15,
    "position": {"x": 0.0, "y": 0.6, "z": -0.9},
    "rotation": IDENTITY,
}


def test_stand_in_room_places_its_tracking_marker_on_the_desk_front(service_url):
    body = httpx.get(f"{service_url}/api/room", timeout=2).json()
    assert body["markers"] == [DESK_MARKER]
    with open_socket(service_url, "vr_solver") as headset:
        assert json.loads(headset.recv(timeout=2))["state"]["room"]["markers"] == [DESK_MARKER]


def test_room_without_markers_publishes_none(multi_asset_service_url):
    assert httpx.get(f"{multi_asset_service_url}/api/room", timeout=2).json()["markers"] == []


def test_generated_room_can_place_markers(tmp_path):
    directory = copy_room(MULTI, tmp_path / "room")
    turned = {"x": 0.0, "y": 0.7071068, "z": 0.0, "w": 0.7071068}
    marker = DESK_MARKER | {"id": 7, "label": "Table side", "size": 0.1, "rotation": turned}
    edit_manifest(directory, lambda manifest: manifest.update(markers=[marker]))
    [loaded] = load_prepared_room(directory).markers
    assert (loaded.id, loaded.size, loaded.label) == (7, 0.1, "Table side")
    assert loaded.rotation.y == pytest.approx(0.7071068)


@pytest.mark.parametrize(
    "markers",
    [
        [DESK_MARKER, DESK_MARKER | {"label": "Again"}],
        [DESK_MARKER | {"id": 587}],
        [DESK_MARKER | {"id": -1}],
        [DESK_MARKER | {"size": 0.0}],
        [DESK_MARKER | {"size": 1.5}],
        [DESK_MARKER | {"rotation": {"x": 0.0, "y": 0.0, "z": 0.0, "w": 2.0}}],
        [DESK_MARKER | {"label": ""}],
    ],
)
def test_invalid_markers_make_the_room_unavailable(tmp_path, markers):
    for source in (ASSETS, MULTI):
        directory = copy_room(source, tmp_path / source.name)
        edit_manifest(directory, lambda manifest: manifest.update(markers=markers))
        with pytest.raises(PreparedRoomError, match="manifest is invalid"):
            load_prepared_room(directory)
