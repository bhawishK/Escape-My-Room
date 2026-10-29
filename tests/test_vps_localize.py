"""Locating a frame against a positioning map (#133), end to end on a small synthetic map: the most
similar map frames are chosen by their global descriptors, keypoints are matched to theirs, and
the camera is solved from the matched 3D points. A stand-in matcher pairs equal descriptors, as
LightGlue would pair the same corner seen twice."""

import numpy as np
from test_vps_solve import K, camera_at

from backend.reconstruction.vps_map import StoredFrame, VpsMap
from backend.vps.localize import Localizer, Query

SIZE = (640, 480)


def project(camera_to_world: np.ndarray, world: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Pixels of the points in front of the camera and inside the picture, and which points."""
    world_to_camera = np.linalg.inv(camera_to_world)
    in_camera = world @ world_to_camera[:3, :3].T + world_to_camera[:3, 3]
    pixels = (in_camera @ K.T)[:, :2] / in_camera[:, 2:3]
    visible = (
        (in_camera[:, 2] > 0.5)
        & (pixels[:, 0] >= 0)
        & (pixels[:, 0] < SIZE[0])
        & (pixels[:, 1] >= 0)
        & (pixels[:, 1] < SIZE[1])
    )
    return pixels[visible], np.flatnonzero(visible)


class EqualDescriptors:
    """Pairs keypoints whose descriptors are the same: a stand-in for LightGlue."""

    model = "equal descriptors"

    def match(
        self,
        query: tuple[np.ndarray, np.ndarray, tuple[int, int]],
        map_frame: tuple[np.ndarray, np.ndarray, tuple[int, int]],
    ) -> np.ndarray:
        similarity = query[1] @ map_frame[1].T
        rows, columns = np.nonzero(similarity > 0.999)
        return np.column_stack([rows, columns])


def scene():
    """A wall of points 6 m along +z, seen by two map frames near the start and one far away."""
    rng = np.random.default_rng(6)
    wall = np.column_stack([rng.uniform(-4, 4, 600), rng.uniform(-2.4, 0, 600), np.full(600, 6.0)])
    elsewhere = wall + [0, 0, -40.0]  # the same pattern, 40 m back: only the far frame sees it
    world = np.vstack([wall, elsewhere])
    descriptors = rng.normal(size=(len(world), 32))
    descriptors /= np.linalg.norm(descriptors, axis=1, keepdims=True)
    frames, globals_ = [], []
    for name, camera, look in [
        ("near_left.jpg", camera_at((-1.0, -1.4, 0.0), 0), [1.0, 0.0]),
        ("near_right.jpg", camera_at((1.0, -1.4, 0.0), 0), [0.9, 0.1]),
        ("far.jpg", camera_at((0.0, -1.4, -46.0), 0), [0.0, 1.0]),
    ]:
        pixels, which = project(camera, world)
        frames.append(
            StoredFrame(
                name, K, camera, pixels, descriptors[which], np.ones(len(which)), world[which], SIZE
            )
        )
        globals_.append(look)
    return VpsMap("fake", "fake", frames, np.array(globals_)), world, descriptors


def test_a_frame_is_located_from_the_most_similar_map_frames() -> None:
    vps, world, descriptors = scene()
    truth = camera_at((0.3, -1.4, 0.5), 10)
    pixels, which = project(truth, world)
    query = Query(pixels, descriptors[which], np.array([0.95, 0.05]), K, SIZE)

    fix = Localizer(vps, EqualDescriptors(), top_frames=2).locate(query)

    assert fix.reason is None
    assert fix.frames == ["near_left.jpg", "near_right.jpg"]
    assert fix.camera_to_world is not None
    assert np.linalg.norm(fix.camera_to_world[:3, 3] - truth[:3, 3]) < 0.01
    assert fix.inliers >= 100


def test_a_frame_of_a_place_the_map_never_saw_is_not_located() -> None:
    vps, _, _ = scene()
    rng = np.random.default_rng(7)
    unseen = rng.normal(size=(300, 32))
    unseen /= np.linalg.norm(unseen, axis=1, keepdims=True)
    query = Query(rng.uniform([0, 0], SIZE, (300, 2)), unseen, np.array([0.7, 0.7]), K, SIZE)

    fix = Localizer(vps, EqualDescriptors(), top_frames=2).locate(query)

    assert fix.camera_to_world is None
    assert fix.reason is not None and "matches" in fix.reason
