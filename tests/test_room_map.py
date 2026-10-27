"""A 2D map of the room (#124): the room's splat seen from above, with its bounds in room metres,
made when the room is built and served with it."""

import io
import json
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image
from test_prepared_room import copy_room

from backend.app import create_app
from backend.room_map import make_map

ROOT = Path(__file__).resolve().parents[1]
TEST_ROOM = ROOT / "assets" / "splat-room"


def test_the_map_shows_the_room_from_above_with_its_bounds(tmp_path):
    room = copy_room(TEST_ROOM, tmp_path / "room")

    make_map(room)

    bounds = json.loads((room / "map.json").read_text(encoding="utf-8"))
    assert bounds["image"] == "map.png"
    # It covers the room's splats (a 3 m floor round the origin) with a margin, origin included.
    assert bounds["min_x"] < -1.5 < 1.5 < bounds["max_x"]
    assert bounds["min_z"] < -1.5 < 1.5 < bounds["max_z"]
    with Image.open(io.BytesIO((room / "map.png").read_bytes())) as image:
        rgb = image.convert("RGB")
    width, height = rgb.size
    assert max(width, height) == 512

    # The red block stands at z = -1, from x = -0.5 to 0.38: on the map, left to right across
    # its middle, a third of the way down (the map's top is -z).
    def at(x: float, z: float) -> tuple[int, int, int]:
        u = (x - bounds["min_x"]) / (bounds["max_x"] - bounds["min_x"])
        v = (z - bounds["min_z"]) / (bounds["max_z"] - bounds["min_z"])
        return rgb.getpixel((int(u * (width - 1)), int(v * (height - 1))))  # type: ignore[return-value]

    red = [at(x, -1.0) for x in (-0.4, -0.06, 0.3)]
    assert all(r > 150 and g < 90 and b < 90 for r, g, b in red), red
    # Away from it, the checkered floor.
    r, g, b = at(-0.06, 0.5)
    assert not (r > 150 and g < 90)


def test_the_room_serves_its_map_and_a_room_without_one_says_so(tmp_path):
    room = copy_room(TEST_ROOM, tmp_path / "room")
    make_map(room)
    served = TestClient(create_app(room)).get("/api/room").json()
    assert served["map"]["url"] == "/assets/prepared-room/map.png"
    assert served["map"]["min_x"] < served["map"]["max_x"]

    plain = TestClient(create_app(ROOT / "assets" / "multi-asset-room")).get("/api/room").json()
    assert plain["map"] is None
