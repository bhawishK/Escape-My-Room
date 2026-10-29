"""Solving where the camera stood (#133): from a frame's 2D keypoints matched to the map's 3D
points, some of them wrong, to the camera's pose in the map, or a reason there is none."""

import numpy as np

from backend.vps.solve import solve_camera

K = np.array([[800.0, 0, 320], [0, 800.0, 240], [0, 0, 1]])


def camera_at(position: tuple[float, float, float], yaw_degrees: float) -> np.ndarray:
    """A COLMAP camera (x right, y down, z forward) held level, turned `yaw` from facing +z."""
    yaw = np.radians(yaw_degrees)
    forward = np.array([np.sin(yaw), 0.0, np.cos(yaw)])
    down = np.array([0.0, 1.0, 0.0])
    right = np.cross(down, forward)
    camera_to_world = np.eye(4)
    camera_to_world[:3, :3] = np.column_stack([right, down, forward])
    camera_to_world[:3, 3] = position
    return camera_to_world


def seen(camera_to_world: np.ndarray, count: int, rng: np.random.Generator):
    """`count` points 2–6 m in front of the camera, and the pixels they show at."""
    in_camera = np.column_stack(
        [rng.uniform(-1.5, 1.5, count), rng.uniform(-1, 1, count), rng.uniform(2, 6, count)]
    )
    world = in_camera @ camera_to_world[:3, :3].T + camera_to_world[:3, 3]
    pixels = (in_camera @ K.T)[:, :2] / in_camera[:, 2:3]
    return pixels, world


def test_the_camera_is_found_through_wrong_matches() -> None:
    rng = np.random.default_rng(3)
    truth = camera_at((1.0, -1.4, 2.0), yaw_degrees=35)
    pixels, world = seen(truth, 140, rng)
    # 60 of the 200 matches are wrong: real map points paired with random pixels.
    wrong = rng.uniform([0, 0], [640, 480], (60, 2))
    pixels = np.vstack([pixels, wrong])
    world = np.vstack([world, world[rng.integers(0, 140, 60)]])

    solved = solve_camera(pixels, world, K)

    assert solved.reason is None
    assert solved.camera_to_world is not None
    assert np.linalg.norm(solved.camera_to_world[:3, 3] - truth[:3, 3]) < 0.005
    turned = solved.camera_to_world[:3, :3].T @ truth[:3, :3]
    assert np.degrees(np.arccos(np.clip((np.trace(turned) - 1) / 2, -1, 1))) < 0.2
    assert 135 <= solved.inliers <= 145


def test_too_few_agreeing_matches_give_no_pose_and_say_why() -> None:
    rng = np.random.default_rng(4)
    pixels, world = seen(camera_at((0.0, -1.4, 0.0), 0), 12, rng)
    # Mostly wrong matches, as for a frame of a place the map never saw.
    pixels = np.vstack([pixels, rng.uniform([0, 0], [640, 480], (80, 2))])
    world = np.vstack([world, rng.uniform(-3, 3, (80, 3)) + [0, 0, 6]])

    solved = solve_camera(pixels, world, K)

    assert solved.camera_to_world is None
    assert solved.reason is not None and solved.reason.endswith("30 are needed")
    assert solved.inliers < 30
