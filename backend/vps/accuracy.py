"""How far off located cameras are, against a reference path in another frame (#133).

The reference is the test video's own COLMAP reconstruction: right in shape, but with its own
scale, turn and origin. It is carried onto the located path by a similarity (Umeyama's method)
fitted to the frames that agree with each other, so a few wrong fixes are counted as wrong rather
than pulling every other frame off; errors are then measured in the map's units: metres, as far as
the map's scale is right. Rotation errors use their own alignment, the turn that best carries the
agreeing reference cameras' rotations onto the located ones: when the located frames lie along
one line, their positions leave the similarity's turn about that line open.
"""

from dataclasses import dataclass

import numpy as np

# How close (in metres) a located camera must land to count as agreeing while the alignment is
# fitted, and how far off a fix must be to count as wrong.
AGREE_M = 0.15
WRONG_M = 0.5
TRIES = 1000


@dataclass(frozen=True)
class Accuracy:
    frames: int
    # How much larger the map is than the reference reconstruction.
    scale: float
    median_position_error: float
    p90_position_error: float
    median_rotation_error_degrees: float
    # Fixes more than WRONG_M off, and every frame's position error, in the order given.
    wrong: int
    position_errors: tuple[float, ...]


def similarity(source: np.ndarray, target: np.ndarray) -> tuple[float, np.ndarray, np.ndarray]:
    """The scale, rotation and translation that best carry `source` points onto `target` ones."""
    source_mean, target_mean = source.mean(axis=0), target.mean(axis=0)
    centred_source, centred_target = source - source_mean, target - target_mean
    u, singular, vt = np.linalg.svd(centred_target.T @ centred_source / len(source))
    flip = np.diag([1.0, 1.0, np.sign(np.linalg.det(u) * np.linalg.det(vt))])
    rotation = u @ flip @ vt
    scale = float(np.trace(np.diag(singular) @ flip) / (centred_source**2).sum(axis=1).mean())
    return scale, rotation, target_mean - scale * rotation @ source_mean


def distances(
    fit: tuple[float, np.ndarray, np.ndarray], source: np.ndarray, target: np.ndarray
) -> np.ndarray:
    scale, rotation, translation = fit
    return np.linalg.norm(target - (source @ (scale * rotation).T + translation), axis=1)


def agreeing_similarity(
    source: np.ndarray, target: np.ndarray
) -> tuple[tuple[float, np.ndarray, np.ndarray], np.ndarray]:
    """The similarity most points agree with (RANSAC over triples), refitted on those points,
    and which points agree."""
    rng = np.random.default_rng(0)
    agreeing = np.zeros(len(source), dtype=bool)
    for _ in range(TRIES):
        chosen = rng.choice(len(source), 3, replace=False)
        trial = distances(similarity(source[chosen], target[chosen]), source, target) < AGREE_M
        if trial.sum() > agreeing.sum():
            agreeing = trial
    if agreeing.sum() < 3:
        agreeing = np.ones(len(source), dtype=bool)
    fit = similarity(source[agreeing], target[agreeing])
    return fit, distances(fit, source, target) < AGREE_M


def angle_degrees(rotation: np.ndarray) -> float:
    return float(np.degrees(np.arccos(np.clip((np.trace(rotation) - 1) / 2, -1.0, 1.0))))


def mean_turn(located: list[np.ndarray], reference: list[np.ndarray]) -> np.ndarray:
    """The rotation that best carries the reference cameras' rotations onto the located ones."""
    summed = sum(
        mine[:3, :3] @ theirs[:3, :3].T for mine, theirs in zip(located, reference, strict=True)
    )
    u, _, vt = np.linalg.svd(np.asarray(summed))
    return u @ np.diag([1.0, 1.0, np.sign(np.linalg.det(u @ vt))]) @ vt


def compare(located: list[np.ndarray], reference: list[np.ndarray]) -> Accuracy:
    """Located and reference camera-to-world poses of the same frames, in the same order."""
    found = np.array([pose[:3, 3] for pose in located])
    known = np.array([pose[:3, 3] for pose in reference])
    fit, agreeing = agreeing_similarity(known, found)
    position_errors = distances(fit, known, found)
    turned = mean_turn(
        [pose for pose, keep in zip(located, agreeing, strict=True) if keep],
        [pose for pose, keep in zip(reference, agreeing, strict=True) if keep],
    )
    rotation_errors = [
        angle_degrees(mine[:3, :3].T @ turned @ theirs[:3, :3])
        for mine, theirs in zip(located, reference, strict=True)
    ]
    return Accuracy(
        frames=len(located),
        scale=fit[0],
        median_position_error=float(np.median(position_errors)),
        p90_position_error=float(np.percentile(position_errors, 90)),
        median_rotation_error_degrees=float(np.median(rotation_errors)),
        wrong=int((position_errors > WRONG_M).sum()),
        position_errors=tuple(round(float(e), 4) for e in position_errors),
    )
