"""A room's landmarks reach the phone (#120): the objects it can calibrate by standing at two."""

import json
from pathlib import Path

from fastapi.testclient import TestClient
from test_prepared_room import copy_room

from backend.app import create_app

ROOT = Path(__file__).resolve().parents[1]
PREPARED = ROOT / "assets" / "prepared-room"


def landmark(id_: str, label: str, centre: list[float]) -> dict[str, object]:
    """One landmark as `backend.landmarks.save_landmarks` writes it."""
    return {"id": id_, "label": label, "centre": centre, "seen": 2, "aliases": [], "views": [1, 2]}


def test_the_rooms_landmarks_reach_both_devices_on_the_floor(tmp_path):
    room = copy_room(PREPARED, tmp_path / "room")
    marks = [
        landmark("sink", "sink", [-3.5, 1.0, -3.5]),
        landmark("waste_bin", "waste bin", [-0.47, 0.1, -1.57]),
    ]
    (room / "landmarks.json").write_text(json.dumps({"landmarks": marks}), encoding="utf-8")
    client = TestClient(create_app(room))

    served = client.get("/api/room").json()
    assert served["landmarks"] == [
        {"id": "sink", "label": "sink", "aliases": [], "x": -3.5, "z": -3.5},
        {"id": "waste_bin", "label": "waste bin", "aliases": [], "x": -0.47, "z": -1.57},
    ]
    with client.websocket_connect("/api/ws?role=mobile_master") as phone:
        assert phone.receive_json()["state"]["room"]["landmarks"] == served["landmarks"]


def test_a_room_without_a_landmark_map_has_no_landmarks():
    assert (
        TestClient(create_app(ROOT / "assets" / "multi-asset-room"))
        .get("/api/room")
        .json()["landmarks"]
        == []
    )


def test_an_unreadable_landmark_map_is_a_visible_room_failure(tmp_path):
    room = copy_room(PREPARED, tmp_path / "room")
    (room / "landmarks.json").write_text('{"landmarks": [{"id": "sink"}]}', encoding="utf-8")

    response = TestClient(create_app(room)).get("/api/room")
    assert response.status_code == 503
    assert "landmarks.json" in response.text
