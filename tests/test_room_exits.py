"""The room's exits (#280): its doors and windows from the layout, each anchored on the floor just
inside it, sent with the room. Unit and HTTP seams."""

import json
import math
import shutil
from pathlib import Path

import httpx
import pytest

from backend.room_exits import CORNER, INSET, exits_from_layout, room_exits
from tests.test_room_walls import ROOM_10

X0, X1 = -1.3925, 2.5575
Z0, Z1 = -1.1654, 1.6596


def inside(point) -> bool:
    return X0 < point[0] < X1 and Z0 < point[1] < Z1


def test_room_10_s_door_and_two_windows_become_exits_door_first():
    exits = exits_from_layout(ROOM_10)
    assert [(e.id, e.kind) for e in exits] == [
        ("door_0", "door"),
        ("window_0", "window"),
        ("window_1", "window"),
    ]


def test_each_anchor_is_on_the_floor_just_inside_its_opening():
    door, window_0, window_1 = exits_from_layout(ROOM_10)
    # The door is on the +x wall: out is +x, and its anchor is INSET in from it.
    assert door.outward == (1.0, 0.0)
    assert door.centre == (X1, 1.09, 0.3096)
    assert door.anchor == pytest.approx((X1 - INSET, 0.3096))
    # window_0 is on the -x wall, window_1 on the -z wall.
    assert window_0.outward == (-1.0, 0.0)
    assert window_0.anchor == pytest.approx((X0 + INSET, 0.2346))
    assert window_1.outward == (0.0, -1.0)
    assert window_1.anchor == pytest.approx((1.3075, Z0 + INSET))
    for exit_ in (door, window_0, window_1):
        assert inside(exit_.anchor)
        assert math.hypot(*exit_.outward) == pytest.approx(1.0)


def test_an_opening_a_little_off_its_wall_is_put_on_it():
    layout = {
        "walls": {"x": [0, 4], "z": [0, 3]},
        "openings": [{"kind": "door", "centre": [2.0, 1.0, 3.08], "width": 0.9, "height": 2.0}],
    }
    (door,) = exits_from_layout(layout)
    assert door.centre[2] == 3.0 and door.outward == (0.0, 1.0)
    assert door.anchor == pytest.approx((2.0, 3.0 - INSET))
    assert door.id == "door_0"


def test_a_door_at_a_corner_has_its_anchor_off_the_corner():
    layout = {
        "walls": {"x": [0, 4], "z": [0, 3]},
        "openings": [{"kind": "door", "centre": [4.0, 1.0, 0.05], "width": 0.9, "height": 2.0}],
    }
    (door,) = exits_from_layout(layout)
    assert door.anchor == pytest.approx((4.0 - INSET, CORNER))


def test_a_narrow_room_keeps_the_anchor_no_further_in_than_its_middle():
    layout = {
        "walls": {"x": [0, 4], "z": [0, 0.5]},
        "openings": [{"kind": "door", "centre": [2.0, 1.0, 0.5], "width": 0.9, "height": 2.0}],
    }
    (door,) = exits_from_layout(layout)
    assert door.anchor == pytest.approx((2.0, 0.25))


@pytest.mark.parametrize(
    "layout",
    [
        {},
        {"walls": {"x": [0, 4], "z": [0, 3]}},
        {"walls": {"x": [0, 0], "z": [0, 3]}, "openings": []},
        {"walls": "none", "openings": [{"kind": "door"}]},
    ],
)
def test_a_layout_without_an_outline_or_openings_has_no_exits(layout):
    assert exits_from_layout(layout) == []


def test_openings_that_are_not_doors_or_windows_or_are_broken_are_left_out():
    layout = {
        "walls": {"x": [0, 4], "z": [0, 3]},
        "openings": [
            {"kind": "arch", "centre": [0, 1, 1], "width": 1, "height": 2},
            {"kind": "door", "centre": [0, 1], "width": 1, "height": 2},
            {"kind": "door", "centre": [0, 1, 1], "width": 0, "height": 2},
            "door",
            {"id": "w", "kind": "window", "centre": [0, 1, 1], "width": 1, "height": 1},
            {"id": "w", "kind": "window", "centre": [4, 1, 1], "width": 1, "height": 1},
        ],
    }
    exits = exits_from_layout(layout)
    assert [(e.id, e.centre[0]) for e in exits] == [("w", 0.0)]


def test_a_room_s_exits_reach_the_devices_with_the_room(start_service, tmp_path):
    room = Path(__file__).resolve().parents[1] / "assets" / "splat-room"
    copy = tmp_path / "room"
    shutil.copytree(room, copy)
    (copy / "layout.json").unlink()
    assert room_exits(copy) == []
    with start_service(tmp_path / "data", ESCAPE_ROOM_PREPARED_DIR=str(copy)) as url:
        assert httpx.get(f"{url}/api/room", timeout=5).json()["exits"] == []
    (copy / "layout.json").write_text(json.dumps(ROOM_10), encoding="utf-8")
    with start_service(tmp_path / "data2", ESCAPE_ROOM_PREPARED_DIR=str(copy)) as url:
        exits = httpx.get(f"{url}/api/room", timeout=5).json()["exits"]
        assert [e["id"] for e in exits] == ["door_0", "window_0", "window_1"]
        assert exits[0]["anchor"] == pytest.approx([X1 - INSET, 0.3096])
        assert exits[0]["outward"] == [1.0, 0.0]
