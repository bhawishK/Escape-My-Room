"""The room's layout as part of the pipeline (#270): SpatialLM's lines become furniture, the floor
to the walls and the walls with their door (#269) when a room is built; SpatialLM runs in its own
env, or the stage is skipped with why. Unit and build seams; a fake SpatialLM."""

import json
import shutil
import sys
from pathlib import Path

import numpy as np
import pytest

from backend.live_room import LiveRooms
from backend.prepared_room import load_prepared_room
from backend.room_layout import LayoutUnavailable, placed_points, run_spatiallm, write_points

ROOT = Path(__file__).resolve().parents[1]
SPLAT_ROOM = ROOT / "assets" / "splat-room"

# SpatialLM's lines for a 2.4 x 2 m room (z up): four walls 2.4 m high, a door on the wall at
# x = 1.2, and a bed 1.9 x 1.0 m along x against the wall at room z = -1 (SpatialLM y = 1).
LAYOUT = """wall_0=Wall(-1.2,1.0,0.0,1.2,1.0,0.0,2.4,0.0)
wall_1=Wall(1.2,1.0,0.0,1.2,-1.0,0.0,2.4,0.0)
wall_2=Wall(1.2,-1.0,0.0,-1.2,-1.0,0.0,2.4,0.0)
wall_3=Wall(-1.2,-1.0,0.0,-1.2,1.0,0.0,2.4,0.0)
door_0=Door(wall_1,1.2,0.0,1.0,0.8,2.0)
bbox_0=Bbox(bed,0.0,0.45,0.28,0.0,1.9,1.0,0.56)
bbox_1=Bbox(curtain,-1.1,0.0,1.2,0.0,0.1,1.5,2.0)
"""


def reconstruction(tmp_path: Path, layout: str | None = LAYOUT) -> Path:
    """A reconstruction's output as the pipeline leaves it: the splat, its report, its layout."""
    folder = tmp_path / "reconstruction"
    folder.mkdir()
    shutil.copy(SPLAT_ROOM / "room.ply", folder / "room.ply")
    (folder / "report.json").write_text(json.dumps({"cameras": []}), encoding="utf-8")
    if layout is not None:
        (folder / "layout.txt").write_text(layout, encoding="utf-8")
    return folder


def test_a_room_built_with_a_layout_has_its_furniture_floor_and_walls(tmp_path):
    rooms = LiveRooms(tmp_path / "data", SPLAT_ROOM)
    loaded, folder = rooms.build("job_ab", reconstruction(tmp_path), 7)
    ids = [entity.id for entity in loaded.entities]
    # The bed, not the curtain (soft things are left out).
    assert "layout_bed_1" in ids and not any("curtain" in id_ for id_ in ids)
    bed = next(e for e in loaded.entities if e.id == "layout_bed_1")
    assert bed.size.width == pytest.approx(1.9) and bed.size.depth == pytest.approx(1.0)
    # SpatialLM's (0, 0.45) is the room's (0, -0.45): y up, z = -y.
    assert bed.position.x == pytest.approx(0.0) and bed.position.z == pytest.approx(-0.45)
    assert bed.position.y == pytest.approx(0.0)
    floor = next(e for e in loaded.entities if e.id == "floor")
    assert floor.size.width == pytest.approx(2.4) and floor.size.depth == pytest.approx(2.0)
    # The walls with their door, for the dollhouse (#269).
    assert len(loaded.walls) == 5
    layout = json.loads((folder / "layout.json").read_text(encoding="utf-8"))
    assert layout["walls"]["height"] == 2.4
    assert [opening["kind"] for opening in layout["openings"]] == ["door"]


def test_a_room_built_without_a_layout_is_built_as_before(tmp_path):
    rooms = LiveRooms(tmp_path / "data", SPLAT_ROOM)
    loaded, folder = rooms.build("job_cd", reconstruction(tmp_path, layout=None), 8)
    assert not any(entity.id.startswith("layout_") for entity in loaded.entities)
    assert loaded.walls == [] and not (folder / "layout.json").exists()


def test_points_are_placed_as_the_room_builder_places_them():
    from backend.live_room import build_room

    module = build_room()
    place = {"rotation": (0.0, 0.3826834, 0.0, 0.9238795), "scale": 0.5, "lift": 0.7}
    points = np.array([[1.0, 2.0, 3.0], [-0.5, 0.1, 0.9]])
    ours = placed_points(points, place["rotation"], place["scale"], (0.0, place["lift"], 0.0))
    theirs = np.array([module.placed(place, tuple(point)) for point in points])
    assert ours == pytest.approx(theirs, abs=1e-6)


def test_spatiallm_s_point_cloud_is_z_up_and_without_far_strays(tmp_path):
    rng = np.random.default_rng(0)
    points = rng.uniform(-1, 1, size=(500, 3))
    points[0] = [50.0, 0.0, 0.0]  # a stray far outside
    count = write_points(tmp_path / "cloud.ply", points, np.full((500, 3), 0.5))
    assert count == 499
    data = (tmp_path / "cloud.ply").read_bytes()
    end = data.index(b"end_header\n") + len(b"end_header\n")
    rows = np.frombuffer(
        data[end:],
        dtype=[("x", "<f4"), ("y", "<f4"), ("z", "<f4"), ("r", "u1"), ("g", "u1"), ("b", "u1")],
    )
    # Room (x, y, z) with y up is (x, -z, y) for SpatialLM.
    kept = points[1:]
    assert np.allclose(rows["z"], kept[:, 1], atol=1e-6)
    assert np.allclose(rows["y"], -kept[:, 2], atol=1e-6)


def test_without_spatiallm_the_layout_is_unavailable_with_why(tmp_path, monkeypatch):
    monkeypatch.delenv("ESCAPE_ROOM_SPATIALLM_PYTHON", raising=False)
    with pytest.raises(LayoutUnavailable, match="isn't installed"):
        run_spatiallm(tmp_path / "cloud.ply", tmp_path / "layout.txt", folder=tmp_path / "none")


def test_spatiallm_is_run_in_its_own_folder_and_its_layout_written(tmp_path, monkeypatch):
    folder = tmp_path / "spatiallm"
    folder.mkdir()
    # A fake SpatialLM: checks its arguments, then writes the layout.
    (folder / "inference.py").write_text(
        "import sys\n"
        "args = sys.argv[1:]\n"
        "model = args[args.index('--model_path') + 1]\n"
        "assert model == 'manycore-research/SpatialLM1.1-Qwen-0.5B'\n"
        "open(args[args.index('--output') + 1], 'w').write(" + repr(LAYOUT) + ")\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("ESCAPE_ROOM_SPATIALLM_PYTHON", sys.executable)
    cloud = tmp_path / "cloud.ply"
    write_points(cloud, np.zeros((10, 3)), np.zeros((10, 3)))
    run_spatiallm(cloud, tmp_path / "layout.txt", folder=folder)
    assert (tmp_path / "layout.txt").read_text(encoding="utf-8") == LAYOUT


def test_a_spatiallm_that_fails_says_so(tmp_path, monkeypatch):
    folder = tmp_path / "spatiallm"
    folder.mkdir()
    (folder / "inference.py").write_text("raise SystemExit('out of memory')\n", encoding="utf-8")
    monkeypatch.setenv("ESCAPE_ROOM_SPATIALLM_PYTHON", sys.executable)
    with pytest.raises(LayoutUnavailable, match="out of memory"):
        run_spatiallm(tmp_path / "cloud.ply", tmp_path / "layout.txt", folder=folder)


def test_a_built_room_with_a_layout_still_loads_as_a_prepared_room(tmp_path):
    rooms = LiveRooms(tmp_path / "data", SPLAT_ROOM)
    _, folder = rooms.build("job_ef", reconstruction(tmp_path), 9)
    again = load_prepared_room(folder)
    assert again.room_version == 9 and len(again.walls) == 5
