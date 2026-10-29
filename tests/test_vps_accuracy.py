"""How far off the located cameras are (#133): the test video's own COLMAP path has its own scale,
turn and origin, so it is aligned to the located path by a similarity before errors are measured,
in the map's units."""

import numpy as np

from backend.vps.accuracy import compare


def turn(axis: np.ndarray, degrees: float) -> np.ndarray:
    axis = axis / np.linalg.norm(axis)
    x, y, z = axis
    k = np.array([[0, -z, y], [z, 0, -x], [-y, x, 0]])
    angle = np.radians(degrees)
    return np.eye(3) + np.sin(angle) * k + (1 - np.cos(angle)) * k @ k


def pose(rotation: np.ndarray, position: np.ndarray) -> np.ndarray:
    camera_to_world = np.eye(4)
    camera_to_world[:3, :3] = rotation
    camera_to_world[:3, 3] = position
    return camera_to_world


def test_errors_are_measured_after_aligning_the_reference_path() -> None:
    rng = np.random.default_rng(5)
    # A walk down a 6 m hallway and back, turning to face the way it goes.
    truth = [
        pose(
            turn(np.array([0, 1.0, 0]), 180 * (i >= 30)), np.array([0.2 * (i % 30), -1.4, i // 30])
        )
        for i in range(60)
    ]
    # The test video's own frame: a third of the size, turned 40 degrees and moved.
    move = turn(np.array([1.0, 2, 3]), 40)
    reference = [pose(move @ t[:3, :3], 0.3 * move @ t[:3, 3] + [5, -2, 1]) for t in truth]
    # Located 2 cm off on each axis, and turned 1 degree.
    located = [
        pose(t[:3, :3] @ turn(rng.normal(size=3), 1.0), t[:3, 3] + rng.normal(0, 0.02, 3))
        for t in truth
    ]

    report = compare(located, reference)

    # The median length of a 3D error of 2 cm on each axis is about 3.1 cm.
    assert 0.02 < report.median_position_error < 0.045
    assert 0.9 < report.median_rotation_error_degrees < 1.1
    assert abs(report.scale - 1 / 0.3) < 0.03
    assert report.frames == 60
