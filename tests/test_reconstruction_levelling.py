"""Levelling (#135): COLMAP's frame has any tilt, scale and origin; the room comes out with the
floor at y = 0, +y up, and the phone at the height it was held."""

import numpy as np

from backend.reconstruction.levelling import apply_transform, level_room


def room_points(rng: np.random.Generator) -> np.ndarray:
    """A 4 m x 4 m floor and two walls, in room metres."""
    floor = np.column_stack([rng.uniform(-2, 2, 600), np.zeros(600), rng.uniform(-2, 2, 600)])
    wall = np.column_stack([rng.uniform(-2, 2, 300), rng.uniform(0, 2.5, 300), np.full(300, -2.0)])
    side = np.column_stack([np.full(300, 2.0), rng.uniform(0, 2.5, 300), rng.uniform(-2, 2, 300)])
    return np.vstack([floor, wall, side])


def camera(x: float, z: float, yaw: float, height: float = 1.4) -> dict:
    """A COLMAP camera (x right, y down, z forward) held upright, facing `yaw` from -z."""
    forward = np.array([np.sin(yaw), 0.0, -np.cos(yaw)])
    down = np.array([0.0, -1.0, 0.0])
    right = np.cross(down, forward)
    camera_to_world = np.eye(4)
    camera_to_world[:3, :3] = np.column_stack([right, down, forward])
    camera_to_world[:3, 3] = [x, height, z]
    K = np.array([[500.0, 0, 320], [0, 500.0, 240], [0, 0, 1]])
    return {"name": f"{x}-{z}", "K": K, "camera_to_world": camera_to_world}


def colmap_frame(points: np.ndarray, cameras: list[dict]) -> tuple[np.ndarray, list[dict]]:
    """The same scene as COLMAP might give it: half size, tilted 25 degrees, moved."""
    angle = np.radians(25)
    tilt = np.array(
        [[1, 0, 0], [0, np.cos(angle), -np.sin(angle)], [0, np.sin(angle), np.cos(angle)]]
    )
    similarity = np.eye(4)
    similarity[:3, :3] = 0.5 * tilt
    similarity[:3, 3] = [3.0, -1.0, 7.0]
    return apply_transform(similarity, cameras, points)[::-1]


def project(cam: dict, point: np.ndarray) -> np.ndarray:
    world_to_camera = np.linalg.inv(cam["camera_to_world"])
    in_camera = world_to_camera[:3, :3] @ point + world_to_camera[:3, 3]
    pixel = cam["K"] @ in_camera
    return pixel[:2] / pixel[2]


def test_the_floor_goes_to_zero_and_the_phone_to_its_held_height() -> None:
    rng = np.random.default_rng(1)
    cameras = [camera(x, z, yaw) for x, z, yaw in [(-1, 1, 0.2), (0, 0.5, -0.4), (1, 1, 0.1)]]
    points, cameras = colmap_frame(room_points(rng), cameras)

    transform, report = level_room(points, cameras, 1.4)
    levelled_cameras, levelled = apply_transform(transform, cameras, points)

    floor = levelled[:600]
    assert np.abs(floor[:, 1]).max() < 0.01
    heights = [c["camera_to_world"][1, 3] for c in levelled_cameras]
    assert np.allclose(heights, 1.4, atol=0.01)
    ups = [-c["camera_to_world"][:3, 1] for c in levelled_cameras]
    assert np.allclose(ups, [0, 1, 0], atol=0.01)
    assert abs(report["scale"] - 2.0) < 0.02
    assert report["floor"] == "lowest horizontal plane"


def test_points_stay_on_the_same_pixels_after_levelling() -> None:
    rng = np.random.default_rng(2)
    cameras = [camera(x, z, yaw) for x, z, yaw in [(-1, 1, 0.2), (1, 1, 0.1)]]
    points, cameras = colmap_frame(room_points(rng), cameras)

    transform, _ = level_room(points, cameras, 1.4)
    moved_cameras, moved = apply_transform(transform, cameras, points)

    for before, after in zip(cameras, moved_cameras, strict=True):
        for index in (0, 650, 1000):
            assert np.allclose(project(before, points[index]), project(after, moved[index]))
