"""How far off located cameras are, against a reference path in another frame (#133).

The reference is the test video's own COLMAP reconstruction: right in shape, but with its own
scale, turn and origin. It is carried onto the located path by the similarity that fits them best
(Umeyama's method), and the errors are then measured in the map's units: metres, as far as the
map's scale is right.
"""

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class Accuracy:
    frames: int
    # How much larger the map is than the reference reconstruction.
    scale: float
    median_position_error: float
    p90_position_error: float
    median_rotation_error_degrees: float


def similarity(source: np.ndarray, target: np.ndarray) -> tuple[float, np.ndarray, np.ndarray]:
    """The scale, rotation and translation that best carry `source` points onto `target` ones."""
    source_mean, target_mean = source.mean(axis=0), target.mean(axis=0)
    centred_source, centred_target = source - source_mean, target - target_mean
    u, singular, vt = np.linalg.svd(centred_target.T @ centred_source / len(source))
    flip = np.diag([1.0, 1.0, np.sign(np.linalg.det(u) * np.linalg.det(vt))])
    rotation = u @ flip @ vt
    scale = float(np.trace(np.diag(singular) @ flip) / (centred_source**2).sum(axis=1).mean())
    return scale, rotation, target_mean - scale * rotation @ source_mean


def angle_degrees(rotation: np.ndarray) -> float:
    return float(np.degrees(np.arccos(np.clip((np.trace(rotation) - 1) / 2, -1.0, 1.0))))


def compare(located: list[np.ndarray], reference: list[np.ndarray]) -> Accuracy:
    """Located and reference camera-to-world poses of the same frames, in the same order."""
    found = np.array([pose[:3, 3] for pose in located])
    known = np.array([pose[:3, 3] for pose in reference])
    scale, rotation, translation = similarity(known, found)
    carried = known @ (scale * rotation).T + translation
    position_errors = np.linalg.norm(found - carried, axis=1)
    rotation_errors = [
        angle_degrees(mine[:3, :3].T @ rotation @ theirs[:3, :3])
        for mine, theirs in zip(located, reference, strict=True)
    ]
    return Accuracy(
        frames=len(located),
        scale=scale,
        median_position_error=float(np.median(position_errors)),
        p90_position_error=float(np.percentile(position_errors, 90)),
        median_rotation_error_degrees=float(np.median(rotation_errors)),
    )
