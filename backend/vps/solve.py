"""Where the camera stood, from a frame's pixels matched to the map's 3D points (#133).

RANSAC finds the pose most matches agree on, so wrong matches are left out, and the pose is then
refined on the matches it kept (the inliers). A pose is only given when enough matches agree.
"""

from dataclasses import dataclass
from typing import cast

import cv2
import numpy as np

# Matches that must agree before a pose is trusted, and how far (in pixels) a match may land from
# where the pose puts its 3D point and still count as agreeing.
MIN_INLIERS = 30
INLIER_PIXELS = 4.0


@dataclass(frozen=True)
class Solved:
    # In the map's frame, COLMAP's convention: x right, y down, z forward. None when not solved.
    camera_to_world: np.ndarray | None
    inliers: int
    # Why there is no pose, when there is none.
    reason: str | None


def solve_camera(pixels: np.ndarray, points: np.ndarray, K: np.ndarray) -> Solved:
    """The camera pose from pixel (x, y) to 3D point pairs, with the frame's intrinsics `K`."""
    if len(pixels) < MIN_INLIERS:
        return Solved(None, 0, f"only {len(pixels)} matches; {MIN_INLIERS} are needed")
    world = np.ascontiguousarray(points, dtype=np.float64)
    image = np.ascontiguousarray(pixels, dtype=np.float64)
    found, rotation, translation, inliers = cv2.solvePnPRansac(
        world,
        image,
        K,
        None,
        iterationsCount=2000,
        reprojectionError=INLIER_PIXELS,
        confidence=0.9999,
    )
    # OpenCV gives no inliers as None, despite what its type hints say.
    found_inliers = cast(np.ndarray | None, inliers)
    kept = np.zeros(0, dtype=int) if found_inliers is None else found_inliers.astype(int).ravel()
    count = len(kept)
    if not found or count < MIN_INLIERS:
        return Solved(None, count, f"only {count} matches agree; {MIN_INLIERS} are needed")
    rotation, translation = cv2.solvePnPRefineLM(
        world[kept], image[kept], K, None, rotation, translation
    )
    world_to_camera = np.eye(4)
    world_to_camera[:3, :3] = cv2.Rodrigues(rotation)[0]
    world_to_camera[:3, 3] = translation[:, 0]
    return Solved(np.linalg.inv(world_to_camera), count, None)
