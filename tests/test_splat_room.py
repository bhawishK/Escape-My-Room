"""A prepared room whose look is a Gaussian splat, served to both devices beside its entities."""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from test_prepared_room import MULTI, copy_room, edit_manifest

from backend.app import create_app

PLY = b"ply\nformat binary_little_endian 1.0\nelement vertex 0\nproperty float x\nend_header\n"


def splat_room(tmp_path: Path, name: str = "room.ply", data: bytes = PLY) -> Path:
    directory = copy_room(MULTI, tmp_path / "room")
    (directory / name).write_bytes(data)
    edit_manifest(directory, lambda manifest: manifest.update(splat={"asset": "room.ply"}))
    return directory


def test_both_devices_receive_the_splat_with_the_room(tmp_path):
    client = TestClient(create_app(splat_room(tmp_path)))

    room = client.get("/api/room").json()
    assert room["splat_url"] == "/assets/prepared-room/room.ply"
    assert client.get(room["splat_url"]).content == PLY
    # The entities still come with it: the floor bounds walking and the objects can be moved.
    assert {entity["id"] for entity in room["entities"]} == {"floor", "table", "mug", "book"}
    with (
        client.websocket_connect("/api/ws?role=vr_solver") as headset,
        client.websocket_connect("/api/ws?role=mobile_master") as phone,
    ):
        assert phone.receive_json()["state"]["room"]["splat_url"] == room["splat_url"]
        assert headset.receive_json()["state"]["room"]["splat_url"] == room["splat_url"]


def test_a_room_without_a_splat_says_so():
    room = TestClient(create_app(MULTI)).get("/api/room").json()
    assert room["splat_url"] is None
    assert room["splat_placement"] is None


def test_the_splat_is_placed_as_the_manifest_says(tmp_path):
    """A splat trained tilted or at another scale is levelled by its placement, not retrained."""
    directory = splat_room(tmp_path)
    turn = {"x": 0.0, "y": 0.0, "z": 0.25881905, "w": 0.96592583}  # 30 degrees about z
    placement = {"position": {"x": 0.0, "y": 0.4, "z": 0.0}, "rotation": turn, "scale": 0.8}
    edit_manifest(directory, lambda manifest: manifest["splat"].update(placement))
    client = TestClient(create_app(directory))

    room = client.get("/api/room").json()
    assert room["splat_placement"]["position"] == placement["position"]
    assert room["splat_placement"]["scale"] == 0.8
    for axis, value in turn.items():
        assert room["splat_placement"]["rotation"][axis] == pytest.approx(value)
    with client.websocket_connect("/api/ws?role=mobile_master") as phone:
        assert phone.receive_json()["state"]["room"]["splat_placement"] == room["splat_placement"]


def test_an_unplaced_splat_sits_as_it_was_trained(tmp_path):
    room = TestClient(create_app(splat_room(tmp_path))).get("/api/room").json()
    assert room["splat_placement"] == {
        "position": {"x": 0.0, "y": 0.0, "z": 0.0},
        "rotation": {"x": 0.0, "y": 0.0, "z": 0.0, "w": 1.0},
        "scale": 1.0,
    }


@pytest.mark.parametrize(
    ("name", "data", "message"),
    [
        ("other.ply", PLY, "Prepared room splat room.ply is missing."),
        ("room.ply", b"glTF not a splat", "Prepared room splat room.ply is not a PLY splat."),
    ],
)
def test_a_missing_or_wrong_splat_is_a_visible_room_failure(tmp_path, name, data, message):
    client = TestClient(create_app(splat_room(tmp_path, name, data)))
    response = client.get("/api/room")
    assert response.status_code == 503
    assert response.json()["detail"] == message


def test_the_splat_must_be_a_plain_file_name(tmp_path):
    directory = splat_room(tmp_path)
    edit_manifest(directory, lambda manifest: manifest.update(splat={"asset": "../room.ply"}))
    response = TestClient(create_app(directory)).get("/api/room")
    assert response.status_code == 503
    assert response.json()["detail"] == "Prepared room manifest is invalid."
    assert json.loads((directory / "manifest.json").read_text())["splat"]["asset"] == "../room.ply"
