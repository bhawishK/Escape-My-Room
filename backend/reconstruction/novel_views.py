"""Views the phone never filmed, for Difix3D+'s repair rounds (#215).

Poses are 4x4 camera-to-world matrices in the levelled frame (floor at y = 0, +y up, roughly
metres), in COLMAP's convention: the camera's x is right, y is down in the image, z is forward.

Targets are places to stand and ways to look that the walk missed: on a grid over where it went,
at its eye height, each heading round the room, ranked by how far the nearest filmed view is.
Repair rounds start each target from its nearest filmed camera and move it a step closer every
round, as Difix3D does, so each round's renders are only a little worse than the last's.
"""

import math
from typing import Any

import numpy as np

type Pose = np.ndarray
type Camera = dict[str, Any]

UP = np.array([0.0, 1.0, 0.0])
# How far apart filmed and wanted views are: angle between their directions, in degrees / 45,
# plus the distance between them in metres. 1 m counts as much as 45 degrees.
DEGREES_PER_METRE = 45.0
# The middle of training: splats have settled, and later rounds still have steps to train on.
FIRST_ROUND, LAST_ROUND = 0.3, 0.8


def looking(position: np.ndarray, heading_degrees: float, tilt_degrees: float = 0.0) -> Pose:
    """A level camera at `position`: heading 0 faces -z, 90 faces +x; negative tilt looks down."""
    heading, tilt = math.radians(heading_degrees), math.radians(tilt_degrees)
    forward = np.array(
        [math.sin(heading) * math.cos(tilt), math.sin(tilt), -math.cos(heading) * math.cos(tilt)]
    )
    right = np.cross(forward, UP)
    right /= np.linalg.norm(right)
    down = np.cross(forward, right)
    pose = np.eye(4)
    pose[:3, 0], pose[:3, 1], pose[:3, 2], pose[:3, 3] = right, down, forward, position
    return pose


def forward_of(pose: Pose) -> np.ndarray:
    return pose[:3, 2]


def apart(a: Pose, b: Pose) -> float:
    """How different two views are: degrees between their directions / 45, plus metres apart."""
    cosine = float(np.clip(forward_of(a) @ forward_of(b), -1.0, 1.0))
    return math.degrees(math.acos(cosine)) / DEGREES_PER_METRE + float(
        np.linalg.norm(a[:3, 3] - b[:3, 3])
    )


def nearest_camera(cameras: list[Camera], pose: Pose) -> int:
    """The filmed camera most like the view: its picture is Difix's reference."""
    return min(range(len(cameras)), key=lambda i: apart(cameras[i]["camera_to_world"], pose))


def target_views(
    cameras: list[Camera],
    count: int = 24,
    spacing: float = 0.5,
    headings: int = 8,
    tilt_degrees: float = -15.0,
) -> list[Pose]:
    """The `count` views least like any filmed one: standing on a `spacing` grid over the walk's
    extent at its median eye height, looking each of `headings` ways, a little down."""
    poses = [camera["camera_to_world"] for camera in cameras]
    centres = np.array([pose[:3, 3] for pose in poses])
    height = float(np.median(centres[:, 1]))

    def along(low: float, high: float) -> np.ndarray:
        steps = max(1, round((high - low) / spacing))
        return np.linspace(low, high, steps + 1) if high > low else np.array([low])

    candidates = [
        looking(np.array([x, height, z]), 360.0 * turn / headings, tilt_degrees)
        for x in along(centres[:, 0].min(), centres[:, 0].max())
        for z in along(centres[:, 2].min(), centres[:, 2].max())
        for turn in range(headings)
    ]
    gaps = [min(apart(candidate, pose) for pose in poses) for candidate in candidates]
    order = sorted(range(len(candidates)), key=lambda i: -gaps[i])
    return [candidates[i] for i in order[:count]]


def _quaternion(rotation: np.ndarray) -> np.ndarray:
    """(w, x, y, z) of a rotation matrix."""
    m = rotation
    trace = m[0, 0] + m[1, 1] + m[2, 2]
    if trace > 0:
        s = 2 * math.sqrt(trace + 1)
        q = [s / 4, (m[2, 1] - m[1, 2]) / s, (m[0, 2] - m[2, 0]) / s, (m[1, 0] - m[0, 1]) / s]
    elif m[0, 0] > m[1, 1] and m[0, 0] > m[2, 2]:
        s = 2 * math.sqrt(1 + m[0, 0] - m[1, 1] - m[2, 2])
        q = [(m[2, 1] - m[1, 2]) / s, s / 4, (m[0, 1] + m[1, 0]) / s, (m[0, 2] + m[2, 0]) / s]
    elif m[1, 1] > m[2, 2]:
        s = 2 * math.sqrt(1 + m[1, 1] - m[0, 0] - m[2, 2])
        q = [(m[0, 2] - m[2, 0]) / s, (m[0, 1] + m[1, 0]) / s, s / 4, (m[1, 2] + m[2, 1]) / s]
    else:
        s = 2 * math.sqrt(1 + m[2, 2] - m[0, 0] - m[1, 1])
        q = [(m[1, 0] - m[0, 1]) / s, (m[0, 2] + m[2, 0]) / s, (m[1, 2] + m[2, 1]) / s, s / 4]
    return np.array(q) / np.linalg.norm(q)


def _rotation(q: np.ndarray) -> np.ndarray:
    w, x, y, z = q
    return np.array(
        [
            [1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y)],
            [2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)],
            [2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)],
        ]
    )


def interpolate(start: Pose, end: Pose, fraction: float) -> Pose:
    """`fraction` of the way from `start` to `end`: moved along the line, turned along the arc."""
    a, b = _quaternion(start[:3, :3]), _quaternion(end[:3, :3])
    if a @ b < 0:
        b = -b
    angle = math.acos(min(1.0, float(a @ b)))
    if angle < 1e-6:
        q = a
    else:
        q = (math.sin((1 - fraction) * angle) * a + math.sin(fraction * angle) * b) / math.sin(
            angle
        )
    pose = np.eye(4)
    pose[:3, :3] = _rotation(q / np.linalg.norm(q))
    pose[:3, 3] = (1 - fraction) * start[:3, 3] + fraction * end[:3, 3]
    return pose


def fix_schedule(steps: int, rounds: int) -> list[int]:
    """The training steps after which each repair round runs, spread over the middle of training."""
    if rounds <= 0:
        return []
    fractions = np.linspace(FIRST_ROUND, LAST_ROUND, rounds) if rounds > 1 else [FIRST_ROUND]
    return [int(steps * fraction) for fraction in fractions]
