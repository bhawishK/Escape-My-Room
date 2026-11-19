"""Views the phone never filmed, for Difix's repair rounds (#215). Pure pose maths in the levelled
frame: floor at y = 0, +y up; cameras in COLMAP's convention (x right, y down, z forward)."""

import math

import numpy as np
import pytest

from backend.reconstruction.novel_views import (
    fix_schedule,
    forward_of,
    interpolate,
    looking,
    nearest_camera,
    target_views,
)

UP = np.array([0.0, 1.0, 0.0])


def camera(position, heading_degrees, tilt_degrees=0.0):
    return {"camera_to_world": looking(np.array(position, float), heading_degrees, tilt_degrees)}


def heading_of(pose):
    forward = forward_of(pose)
    return math.degrees(math.atan2(forward[0], -forward[2])) % 360


def test_a_view_looks_where_it_is_turned_and_stays_upright():
    pose = looking(np.array([1.0, 1.4, 2.0]), 90.0, -15.0)
    assert np.allclose(pose[:3, 3], [1.0, 1.4, 2.0])
    assert heading_of(pose) == pytest.approx(90.0)
    # Tilted down 15 degrees, and image "down" points down without roll.
    assert forward_of(pose)[1] == pytest.approx(-math.sin(math.radians(15)))
    image_down = pose[:3, 1]
    assert image_down @ UP < 0
    assert pose[:3, 0] @ UP == pytest.approx(0.0, abs=1e-9)
    assert np.allclose(pose[:3, :3] @ pose[:3, :3].T, np.eye(3))


def test_targets_look_where_no_filmed_camera_looked():
    # A walk along x, always facing -z (heading 0).
    filmed = [camera((x, 1.4, 0.0), 0.0) for x in np.linspace(-1, 1, 9)]
    targets = target_views(filmed, count=8)
    assert len(targets) == 8
    for pose in targets:
        # Facing away from what was filmed, not at it.
        assert abs(((heading_of(pose) + 180) % 360) - 180) > 90
        assert pose[1, 3] == pytest.approx(1.4)


def test_targets_stand_where_the_walk_went_and_are_all_different():
    filmed = [
        camera((x, 1.3, z), h) for x, z, h in ((0, 0, 0), (2, 0, 90), (2, 2, 180), (0, 2, 270))
    ]
    targets = target_views(filmed, count=12)
    positions = np.array([pose[:3, 3] for pose in targets])
    assert positions[:, 0].min() >= -1e-9 and positions[:, 0].max() <= 2 + 1e-9
    assert positions[:, 2].min() >= -1e-9 and positions[:, 2].max() <= 2 + 1e-9
    keys = {(round(p[0, 3], 3), round(p[2, 3], 3), round(heading_of(p))) for p in targets}
    assert len(keys) == len(targets)


def test_halfway_between_two_views_is_half_the_move_and_half_the_turn():
    start = looking(np.array([0.0, 1.4, 0.0]), 0.0)
    end = looking(np.array([2.0, 1.4, 0.0]), 90.0)
    middle = interpolate(start, end, 0.5)
    assert np.allclose(middle[:3, 3], [1.0, 1.4, 0.0])
    assert heading_of(middle) == pytest.approx(45.0)
    assert np.allclose(interpolate(start, end, 0.0), start)
    assert np.allclose(interpolate(start, end, 1.0), end)


def test_the_reference_is_the_filmed_camera_looking_most_the_same_way_from_nearby():
    filmed = [camera((0, 1.4, 0), 0.0), camera((0.3, 1.4, 0), 180.0), camera((3, 1.4, 0), 175.0)]
    wanted = looking(np.array([0.0, 1.4, 0.0]), 170.0)
    # 1 m counts as 45 degrees: 10 degrees off from 0.3 m away beats 5 degrees off from 3 m.
    assert nearest_camera(filmed, wanted) == 1


def test_repair_rounds_are_spread_over_the_middle_of_training():
    assert fix_schedule(20_000, 0) == []
    rounds = fix_schedule(20_000, 4)
    assert len(rounds) == 4
    assert rounds == sorted(rounds)
    assert rounds[0] >= 0.3 * 20_000 and rounds[-1] <= 0.8 * 20_000
