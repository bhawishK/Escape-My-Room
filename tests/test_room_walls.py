"""Walls from a room's layout (#269): four walls round its outline, a door's wall split round it,
sent with the room. Unit and HTTP seams."""

import json
import math
import shutil
from pathlib import Path

import httpx
import pytest

from backend.room_walls import room_walls, walls_from_layout

# Room 10's layout: 3.95 x 2.83 m, 2.52 m high, a door 1.64 m wide on its +x wall, two windows.
ROOM_10 = {
    "walls": {"x": [-1.3925, 2.5575], "z": [-1.1654, 1.6596], "height": 2.52},
    "openings": [
        {
            "id": "door_0",
            "kind": "door",
            "centre": [2.5575, 1.09, 0.3096],
            "width": 1.64,
            "height": 2.26,
        },
        {
            "id": "window_0",
            "kind": "window",
            "centre": [-1.3925, 1.34, 0.2346],
            "width": 2.72,
            "height": 1.98,
        },
        {
            "id": "window_1",
            "kind": "window",
            "centre": [1.3075, 1.34, -1.1654],
            "width": 2.5,
            "height": 1.98,
        },
    ],
}


def length(segment) -> float:
    return math.dist(segment.start, segment.end)


def test_room_10_gets_its_four_walls_with_a_doorway_where_the_door_is():
    walls = walls_from_layout(ROOM_10)
    # Three whole walls and the door's wall in two pieces.
    assert len(walls) == 5
    assert all(wall.height == 2.52 for wall in walls)
    on_door_wall = [
        w
        for w in walls
        if w.start[0] == pytest.approx(2.5575) and w.end[0] == pytest.approx(2.5575)
    ]
    assert len(on_door_wall) == 2
    zs = sorted(z for wall in on_door_wall for z in (wall.start[1], wall.end[1]))
    # The gap runs 0.82 m either side of the door's centre.
    assert zs[1] == pytest.approx(0.3096 - 0.82, abs=1e-3)
    assert zs[2] == pytest.approx(0.3096 + 0.82, abs=1e-3)
    # The walls go all the way round but for the doorway.
    perimeter = 2 * (3.95 + 2.825)
    assert sum(length(wall) for wall in walls) == pytest.approx(perimeter - 1.64, abs=1e-2)


def test_windows_are_kept_as_wall():
    no_door = {**ROOM_10, "openings": [o for o in ROOM_10["openings"] if o["kind"] == "window"]}
    assert len(walls_from_layout(no_door)) == 4


def test_a_layout_without_an_outline_has_no_walls():
    assert walls_from_layout({}) == []
    assert walls_from_layout({"walls": {"x": [0, 0], "z": [0, 1], "height": 2}}) == []
    assert walls_from_layout({"walls": "nothing"}) == []


def test_a_door_at_a_corner_leaves_no_sliver_of_wall():
    corner = {
        "walls": {"x": [0, 4], "z": [0, 3], "height": 2.5},
        "openings": [{"kind": "door", "centre": [0.4, 1.0, 0.0], "width": 0.8}],
    }
    walls = walls_from_layout(corner)
    # The door's wall keeps only its piece past the door.
    door_wall = [w for w in walls if w.start[1] == 0 and w.end[1] == 0]
    assert len(door_wall) == 1 and door_wall[0].start == (0.8, 0.0)


def test_a_room_s_walls_reach_the_devices_with_the_room(start_service, tmp_path):
    room = Path(__file__).resolve().parents[1] / "assets" / "splat-room"
    copy = tmp_path / "room"
    shutil.copytree(room, copy)
    (copy / "layout.json").unlink()
    with start_service(tmp_path / "data", ESCAPE_ROOM_PREPARED_DIR=str(copy)) as url:
        assert httpx.get(f"{url}/api/room", timeout=5).json()["walls"] == []
    (copy / "layout.json").write_text(json.dumps(ROOM_10), encoding="utf-8")
    assert len(room_walls(copy)) == 5
    with start_service(tmp_path / "data2", ESCAPE_ROOM_PREPARED_DIR=str(copy)) as url:
        walls = httpx.get(f"{url}/api/room", timeout=5).json()["walls"]
        assert len(walls) == 5 and walls[0]["height"] == 2.52
