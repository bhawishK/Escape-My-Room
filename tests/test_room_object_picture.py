"""A picture of an object in the room, cut from the room's own splat (#223, part of #221).

The splats inside the object's box are rendered on white with Spark, looking at its open side a
little from above: the spike #220 picture the hazard's video starts from. The committed test room
(`assets/splat-room`) has a red block standing near its far edge; here it is given an entity box.
Its small box stands where there are only floor splats, so it can't be pictured."""

import importlib.util
import io
import json
import math
import shutil
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from backend.prepared_room import SceneEntity, load_prepared_room
from backend.room_object_picture import PictureRefused, object_picture, open_side

ROOM = Path(__file__).resolve().parents[1] / "assets" / "splat-room"
_spec = importlib.util.spec_from_file_location(
    "multi_asset_room", ROOM.parent / "multi-asset-room" / "build_room.py"
)
BUILDER = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(BUILDER)
BLOCK = {"id": "block", "x": -0.06, "z": -1.0, "width": 1.0, "height": 0.78, "depth": 0.3}


def entity(
    id_: str, x: float, z: float, width: float, depth: float, height: float = 0.5, yaw: float = 0.0
):
    return {
        "id": id_,
        "label": id_.capitalize(),
        "asset": "box.glb",
        "node": "Box",
        "kind": "static",
        "selectable": False,
        "size": {"width": width, "height": height, "depth": depth},
        "position": {"x": x, "y": 0.0, "z": z},
        "rotation": {"x": 0.0, "y": math.sin(yaw / 2), "z": 0.0, "w": math.cos(yaw / 2)},
    }


def floor(width: float = 4.0, depth: float = 4.0):
    piece = entity("floor", 0.0, 0.0, width, depth, height=0.02)
    piece["position"]["y"] = -0.02
    return piece


def entities(*pieces):
    """Manifest entities as the loaded room has them: each asset as its URL."""
    loaded = []
    for piece in pieces:
        fields = {key: value for key, value in piece.items() if key != "asset"}
        loaded.append(
            SceneEntity.model_validate(fields | {"asset_url": f"/assets/test/{piece['asset']}"})
        )
    return loaded


def test_the_open_side_faces_away_from_the_wall_it_stands_against():
    # A bed against the far wall (-z), long along x: seen from +z.
    bed = entity("bed", 0.0, -1.45, 1.9, 1.0)
    direction = open_side(entities(floor(), bed), "bed")
    assert direction == pytest.approx((0.0, 1.0), abs=1e-6)


def test_the_long_side_is_preferred_when_two_sides_are_open():
    # In the corner (-x, -z), a desk long along x: its long +z side, not its short +x side.
    desk = entity("desk", -1.25, -1.6, 1.4, 0.7)
    direction = open_side(entities(floor(), desk), "desk")
    assert direction == pytest.approx((0.0, 1.0), abs=1e-6)


def test_another_piece_in_front_turns_the_view_to_a_clear_side():
    # A sofa in the middle with a table just in front of it (+z): seen from behind (-z) instead.
    sofa = entity("sofa", 0.0, 0.0, 2.0, 0.9)
    table = entity("table", 0.0, 0.85, 1.2, 0.6)
    direction = open_side(entities(floor(), sofa, table), "sofa")
    assert direction == pytest.approx((0.0, -1.0), abs=1e-6)


def test_a_turned_object_is_seen_square_on_to_its_turned_side():
    # Turned a quarter, a bed against the right wall (+x) has its long side facing -x.
    bed = entity("bed", 1.45, 0.0, 1.9, 1.0, yaw=math.pi / 2)
    direction = open_side(entities(floor(), bed), "bed")
    assert direction == pytest.approx((-1.0, 0.0), abs=1e-6)


def room_with(tmp_path: Path, *extra) -> Path:
    room = tmp_path / "room"
    shutil.copytree(ROOM, room, ignore=shutil.ignore_patterns("__pycache__"))
    for piece in extra:
        # Each added piece has a box model of its own size, as the room loader checks.
        size = piece["size"]
        BUILDER.write_glb(
            room / piece["asset"],
            piece["id"],
            [
                BUILDER.part(
                    f"{piece['id']}_box", (size["width"], size["height"], size["depth"]), "#888888"
                )
            ],
        )
        piece["node"] = piece["id"]
    manifest = json.loads((room / "manifest.json").read_text())
    manifest["entities"] += list(extra)
    (room / "manifest.json").write_text(json.dumps(manifest))
    return room


def test_a_filmed_object_is_pictured_whole_on_white_from_its_open_side(tmp_path):
    block = entity("block", BLOCK["x"], BLOCK["z"], BLOCK["width"], BLOCK["depth"], BLOCK["height"])
    block["asset"] = "block.glb"
    room = room_with(tmp_path, block)
    picture = object_picture(room, load_prepared_room(room).entities, "block")

    image = np.asarray(Image.open(io.BytesIO(picture.png)).convert("RGB")).astype(int)
    assert image.shape == (768, 768, 3)
    red = (image[..., 0] > 140) & (image[..., 1] < 90) & (image[..., 2] < 90)
    white = (image > 245).all(axis=2)
    # The block fills the picture's width or height, with a margin, centred on white: drawn
    # small, the video model zooms in and invents another object.
    ys, xs = np.nonzero(red)
    longer = max(np.ptp(xs), np.ptp(ys)) / 768
    assert 0.6 < longer < 0.85
    assert white.mean() > 0.1
    assert abs(xs.mean() / 768 - 0.5) < 0.1 and abs(ys.mean() / 768 - 0.5) < 0.1
    # Seen from a corner of the room's side of it (+z), 45 degrees round, from 35 degrees up: a
    # flat object seen square on and low is a band the video model can't read (#251).
    eye = np.array(picture.view.position)
    middle = np.array(picture.view.look_at)
    across = eye - middle
    assert eye[2] > BLOCK["z"]
    assert abs(math.degrees(math.atan2(abs(across[0]), across[2]))) == pytest.approx(45, abs=1)
    up = math.degrees(math.atan2(across[1], math.hypot(across[0], across[2])))
    assert up == pytest.approx(35, abs=1)
    assert picture.splats > 0


def test_an_object_with_too_little_of_the_splat_is_refused_with_the_reason(tmp_path):
    room = room_with(tmp_path)
    with pytest.raises(PictureRefused, match="Too little of the room's video shows the box"):
        object_picture(room, load_prepared_room(room).entities, "box")
