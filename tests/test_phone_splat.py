"""A lighter splat for phones (#109): the most important splats of the room, with base colours only,
named in the manifest beside the full one so the phone draws less and 8th Wall keeps its pace."""

import importlib.util
import json
import math
import struct
from pathlib import Path

from fastapi.testclient import TestClient
from test_prepared_room import copy_room

from backend.app import create_app
from backend.splat_file import read_splat

ROOT = Path(__file__).resolve().parents[1]
TEST_ROOM = ROOT / "assets" / "splat-room"
# The notebook's layout: degree-1 colour, as the hallway room has.
FULL = ["x", "y", "z", "nx", "ny", "nz", "f_dc_0", "f_dc_1", "f_dc_2"]
FULL += [f"f_rest_{i}" for i in range(9)]
FULL += ["opacity", "scale_0", "scale_1", "scale_2", "rot_0", "rot_1", "rot_2", "rot_3"]
PHONE = ["x", "y", "z", "f_dc_0", "f_dc_1", "f_dc_2", "opacity"]
PHONE += ["scale_0", "scale_1", "scale_2", "rot_0", "rot_1", "rot_2", "rot_3"]


def build_room():
    spec = importlib.util.spec_from_file_location("splat_build_room", TEST_ROOM / "build_room.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_ply(path: Path, splats: list[dict[str, float]]) -> None:
    header = ["ply", "format binary_little_endian 1.0", f"element vertex {len(splats)}"]
    header += [f"property float {name}" for name in FULL] + ["end_header", ""]
    data = b"".join(struct.pack(f"<{len(FULL)}f", *(s.get(n, 0.0) for n in FULL)) for s in splats)
    path.write_bytes("\n".join(header).encode() + data)


def splat(x: float, opacity: float, size: float) -> dict[str, float]:
    """A splat at x, with an opacity before the sigmoid and a size before the log, as stored."""
    scale = math.log(size)
    return {
        "x": x,
        "f_dc_0": x,
        "f_rest_0": 0.5,
        "opacity": opacity,
        "rot_0": 1.0,
        "scale_0": scale,
        "scale_1": scale,
        "scale_2": scale,
    }


def test_the_phone_keeps_the_splats_that_show_most_with_base_colours_only(tmp_path):
    splats = [
        splat(1.0, opacity=4.0, size=0.05),  # opaque, middling: kept
        splat(2.0, opacity=-4.0, size=0.2),  # large but nearly see-through: dropped
        splat(3.0, opacity=4.0, size=0.2),  # opaque and large: kept first
        splat(4.0, opacity=4.0, size=0.005),  # opaque but tiny: dropped
        splat(5.0, opacity=0.0, size=0.1),  # half opaque, large: kept
    ]
    write_ply(tmp_path / "room.ply", splats)

    build_room().write_phone_splat(tmp_path / "room.ply", tmp_path / "room-phone.ply", 3)

    names, values = read_splat(tmp_path / "room-phone.ply")
    assert names == PHONE
    rows = [values[i : i + len(names)] for i in range(0, len(values), len(names))]
    assert sorted(row[0] for row in rows) == [1.0, 3.0, 5.0]
    # Each kept splat is copied exactly, colour and all.
    for row in rows:
        assert row[names.index("f_dc_0")] == row[0]
        assert row[names.index("rot_0")] == 1.0


def test_a_room_given_a_phone_splat_names_it_and_serves_it_to_phones(tmp_path):
    room = copy_room(TEST_ROOM, tmp_path / "room")
    full = json.loads((room / "manifest.json").read_text(encoding="utf-8"))
    total = len(read_splat(room / "room.ply")[1]) // 17

    build_room().add_phone_splat(room, total // 2)

    manifest = json.loads((room / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["splat"]["phone_asset"] == "room-phone.ply"
    assert manifest["room_version"] == full["room_version"] + 1
    names, values = read_splat(room / "room-phone.ply")
    assert len(values) // len(names) == total // 2
    client = TestClient(create_app(room))
    served = client.get("/api/room").json()
    assert served["splat_url"] == "/assets/prepared-room/room.ply"
    assert served["splat_phone_url"] == "/assets/prepared-room/room-phone.ply"
    assert client.get(served["splat_phone_url"]).content == (room / "room-phone.ply").read_bytes()


def test_a_room_without_a_phone_splat_gives_phones_the_full_one():
    served = TestClient(create_app(ROOT / "assets" / "multi-asset-room")).get("/api/room").json()
    assert served["splat_phone_url"] is None
