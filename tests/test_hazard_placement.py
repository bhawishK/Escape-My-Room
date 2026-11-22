"""Where a hazard's 4D frames go in the room (#228).

`bed-4d-first-frame.ply` is spike #220's first L4GM frame of bed 2 in room 10, which the spike
placed by hand at ×2.4, along the far wall, standing on the floor.
"""

import math
from pathlib import Path

import numpy as np
import pytest

from backend.hazard_placement import Box, footprint, place, solid, true_size_box, turned_about_y
from backend.splat_frames import read_frame

FIXTURES = Path(__file__).parent / "fixtures" / "hazard"
# Room 10's bed 2, from its SpatialLM layout: 1.92 m along the far wall (x), turned half round.
BED_2 = Box(x=0.1325, y=0.0, z=-0.7654, yaw=-math.pi, width=1.921875, depth=1.03125)


def first_frame() -> dict[str, np.ndarray]:
    return read_frame((FIXTURES / "bed-4d-first-frame.ply").read_bytes())


def in_room(splats: dict[str, np.ndarray], placement) -> np.ndarray:
    """The solid splats where the placement puts them, as three.js does: scale, turn, move."""
    xyz = turned_about_y(solid(splats) * placement.scale, placement.turn)
    return xyz + np.array(placement.position)


def test_the_spikes_bed_comes_out_of_its_box_and_its_extent():
    # Bed 2 was pictured from its open side, +z.
    placement = place(first_frame(), BED_2, facing=(0.0, 1.0), hide="layout_bed_2")
    assert placement.scale == pytest.approx(2.4, rel=0.08)
    assert placement.turn == pytest.approx(0.0, abs=1e-9)
    assert placement.hide == "layout_bed_2"
    shape = footprint(in_room(first_frame(), placement))
    # Along the far wall, on the box's centre and standing on the floor.
    assert shape.long == pytest.approx(BED_2.width, rel=0.01)
    assert abs(shape.axis[0]) > 0.9
    assert shape.centre == pytest.approx((BED_2.x, BED_2.z), abs=0.02)
    assert shape.base == pytest.approx(0.0, abs=0.01)


def test_a_turned_box_gives_a_turned_placement():
    turned = Box(x=1.0, y=0.4, z=2.0, yaw=-math.pi / 2, width=1.921875, depth=1.03125)
    # Its long side now runs along z; it is pictured from +x, its open side.
    placement = place(first_frame(), turned, facing=(1.0, 0.0))
    assert placement.turn == pytest.approx(math.pi / 2)
    assert placement.hide is None
    shape = footprint(in_room(first_frame(), placement))
    assert shape.long == pytest.approx(turned.width, rel=0.01)
    assert abs(shape.axis[1]) > 0.9
    assert shape.centre == pytest.approx((1.0, 2.0), abs=0.02)
    assert shape.base == pytest.approx(0.4, abs=0.01)


def test_the_front_faces_where_the_picture_was_taken_from():
    # L4GM puts the picture's camera at +z (#228's measure on the live bed); so +z turns to face it.
    for facing in [(0.0, 1.0), (1.0, 0.0), (0.0, -1.0), (-0.6, 0.8)]:
        placement = place(first_frame(), BED_2, facing=facing)
        front = (math.sin(placement.turn), math.cos(placement.turn))
        assert front == pytest.approx(facing, abs=1e-6)


def test_a_new_object_is_true_to_size_on_the_floor():
    box = true_size_box("a 2 m long sofa", at=(0.5, -1.0))
    assert (box.x, box.y, box.z) == (0.5, 0.0, -1.0)
    placement = place(first_frame(), box, facing=(0.0, 1.0))
    shape = footprint(in_room(first_frame(), placement))
    assert shape.long == pytest.approx(2.0, rel=0.01)
    assert shape.base == pytest.approx(0.0, abs=0.01)


def test_a_new_object_sized_by_its_height_stands_that_tall():
    box = true_size_box("a 90 cm tall space heater", at=(0.0, 0.0))
    placement = place(first_frame(), box, facing=(0.0, 1.0))
    shape = footprint(in_room(first_frame(), placement))
    assert shape.height == pytest.approx(0.9, rel=0.01)
