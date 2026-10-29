"""The positioning map (#135 for #133): every map frame's keypoints, each with the 3D point it
shows, found from the trained splat's depth at that keypoint, and a global descriptor to find the
frame."""

from pathlib import Path

import numpy as np

from backend.reconstruction.vps_map import MapFrame, build_vps_map, read_vps_map

WIDTH, HEIGHT = 64, 48
K = np.array([[60.0, 0, 32], [0, 60.0, 24], [0, 0, 1]])


def looking_down_at_the_floor() -> MapFrame:
    """A camera 1.4 m above the floor at (1, 1.4, 2), pitched 40 degrees down, facing -z."""
    pitch = np.radians(40)
    forward = np.array([0.0, -np.sin(pitch), -np.cos(pitch)])
    down = np.array([0.0, -np.cos(pitch), np.sin(pitch)])
    right = np.cross(down, forward)
    camera_to_world = np.eye(4)
    camera_to_world[:3, :3] = np.column_stack([right, down, forward])
    camera_to_world[:3, 3] = [1.0, 1.4, 2.0]
    return MapFrame("frame_0001.jpg", Path("frame_0001.jpg"), K, camera_to_world, WIDTH, HEIGHT)


def floor_depth(frame: MapFrame) -> tuple[np.ndarray, np.ndarray]:
    """The depth of the floor at each pixel centre, worked out by intersecting its ray with y = 0.
    The top rows are see-through: nothing of the splat there."""
    us, vs = np.meshgrid(np.arange(WIDTH) + 0.5, np.arange(HEIGHT) + 0.5)
    rays = np.linalg.inv(K) @ np.stack([us.ravel(), vs.ravel(), np.ones(us.size)])
    world = frame.camera_to_world[:3, :3] @ rays
    centre_y = frame.camera_to_world[1, 3]
    depth = (-centre_y / world[1]).reshape(HEIGHT, WIDTH)  # z in the camera, as rays have z = 1
    alpha = np.ones((HEIGHT, WIDTH))
    alpha[:4] = 0.2
    return depth, alpha


class FakeExtractor:
    local_model = "fake-superpoint"
    global_model = "fake-dinov2"

    def local(self, image: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        keypoints = np.array([[10.5, 30.5], [40.5, 20.5], [20.5, 1.5]])  # the last is see-through
        descriptors = np.arange(3 * 4, dtype=np.float32).reshape(3, 4)
        return keypoints, descriptors, np.array([0.9, 0.8, 0.7])

    def global_descriptor(self, image: Path) -> np.ndarray:
        return np.array([0.6, 0.8], dtype=np.float32)


def test_keypoints_get_the_floor_points_they_show(tmp_path: Path) -> None:
    frame = looking_down_at_the_floor()

    report = build_vps_map([frame], floor_depth, FakeExtractor(), tmp_path)

    vps = read_vps_map(tmp_path)
    [stored] = vps.frames
    assert stored.name == "frame_0001.jpg"
    assert len(stored.keypoints) == 2
    assert np.allclose(stored.points3d[:, 1], 0.0, atol=1e-6)
    # The first keypoint's ray, worked by hand: pixel (10.5, 30.5) is 21.5 px left of centre and
    # 6.5 px below, so it meets the floor 1.4 / (sin 40 + cos 40 * 6.5 / 60) away along z.
    pitch = np.radians(40)
    z = 1.4 / (np.sin(pitch) + np.cos(pitch) * 6.5 / 60)
    expected_x = 1.0 + z * (10.5 - 32) / 60
    assert abs(stored.points3d[0, 0] - expected_x) < 1e-6
    assert np.array_equal(stored.descriptors, np.arange(8, dtype=np.float32).reshape(2, 4))
    assert np.allclose(stored.camera_to_world, frame.camera_to_world)
    assert vps.global_descriptors.shape == (1, 2)
    assert report == {
        "frames": 1,
        "keypoints": 3,
        "keypoints_with_depth": 2,
        "local_model": "fake-superpoint",
        "global_model": "fake-dinov2",
    }
