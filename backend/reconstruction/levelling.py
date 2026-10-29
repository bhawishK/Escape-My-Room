"""Level and scale COLMAP's scene: the floor at y = 0 with +y up, units roughly metres, facing -z.

Moved from the notebook (spike #92). Cameras are dicts with `K` and a 4x4 `camera_to_world` in
COLMAP's convention: x right, y down, z forward.
"""

from typing import Any

import numpy as np

# `K`, `camera_to_world` and whatever else the caller keeps with a camera.
type Camera = dict[str, Any]


def rotation_between(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """The rotation turning unit vector a onto unit vector b."""
    v = np.cross(a, b)
    c = float(np.dot(a, b))
    if np.linalg.norm(v) < 1e-9:
        if c > 0:
            return np.eye(3)
        axis = np.cross(a, [1.0, 0, 0] if abs(a[0]) < 0.9 else [0, 1.0, 0])
        axis /= np.linalg.norm(axis)
        return 2 * np.outer(axis, axis) - np.eye(3)
    vx = np.array([[0, -v[2], v[1]], [v[2], 0, -v[0]], [-v[1], v[0], 0]])
    return np.eye(3) + vx + vx @ vx / (1 + c)


def level_room(
    points: np.ndarray, cameras: list[Camera], camera_height_m: float
) -> tuple[np.ndarray, dict[str, Any]]:
    """A similarity putting the floor at y = 0 with +y up, units roughly metres, facing -z.

    Up starts as the cameras' average up (frames are upright) and is refined to the normal of
    the lowest large horizontal plane of points, which is taken as the floor. Scale assumes the
    phone was held `camera_height_m` above that floor.
    """
    centres = np.array([camera["camera_to_world"][:3, 3] for camera in cameras])
    # COLMAP cameras look along +z with +y pointing down in the image.
    ups = np.array([-camera["camera_to_world"][:3, 1] for camera in cameras])
    forwards = np.array([camera["camera_to_world"][:3, 2] for camera in cameras])
    up = ups.mean(axis=0)
    up /= np.linalg.norm(up)
    first_up = up.copy()
    method = "lowest horizontal plane"
    floor = None
    for _ in range(3):
        heights = points @ up
        camera_height = float(np.median(centres @ up))
        below = heights[heights < camera_height]
        if len(below) < 50:
            break
        low = float(np.percentile(below, 0.5))
        counts, edges = np.histogram(below, bins=120, range=(low, camera_height))
        width = edges[1] - edges[0]
        start = int(np.argmax(counts >= 0.3 * counts.max()))
        peak = start + int(np.argmax(counts[start : start + 6]))
        floor = float((edges[peak] + edges[peak + 1]) / 2)
        near = points[np.abs(heights - floor) < 1.5 * width]
        if len(near) < 30:
            break
        centred = near - near.mean(axis=0)
        normal = np.linalg.svd(centred, full_matrices=False)[2][-1]
        normal = normal if normal @ up > 0 else -normal
        if np.degrees(np.arccos(np.clip(normal @ up, -1, 1))) > 20:
            break
        up = normal
    heights = points @ up
    camera_height = float(np.median(centres @ up))
    if floor is None:
        method = "lowest points (no floor plane found)"
        floor = float(np.percentile(heights, 1))
    else:
        floor = float(np.median(heights[np.abs(heights - floor) < 0.02 * (camera_height - floor)]))
    held_at = camera_height - floor
    if held_at <= 0:
        raise RuntimeError("The floor was found above the cameras; the video may be upside down.")
    scale = camera_height_m / held_at
    rotation = rotation_between(up, np.array([0.0, 1.0, 0.0]))
    forward = rotation @ forwards.mean(axis=0)
    forward[1] = 0
    if np.linalg.norm(forward) > 1e-6:
        forward /= np.linalg.norm(forward)
        yaw = np.arctan2(forward[0], -forward[2])
        turn = np.array([[np.cos(yaw), 0, -np.sin(yaw)], [0, 1, 0], [np.sin(yaw), 0, np.cos(yaw)]])
        rotation = turn @ rotation
    centre = centres.mean(axis=0)
    origin = centre - ((centre @ up) - floor) * up
    transform = np.eye(4)
    transform[:3, :3] = scale * rotation
    transform[:3, 3] = -scale * rotation @ origin
    report = {
        "floor": method,
        "up_correction_degrees": round(
            float(np.degrees(np.arccos(np.clip(up @ first_up, -1, 1)))), 2
        ),
        "camera_height_units": round(held_at, 4),
        "assumed_camera_height_m": camera_height_m,
        "scale": scale,
    }
    return transform, report


def apply_transform(
    transform: np.ndarray, cameras: list[Camera], points: np.ndarray
) -> tuple[list[Camera], np.ndarray]:
    """Move cameras and points by a similarity; camera rotations stay pure rotations."""
    scale = np.cbrt(np.linalg.det(transform[:3, :3]))
    rotation = transform[:3, :3] / scale
    moved: list[Camera] = []
    for camera in cameras:
        camera_to_world = camera["camera_to_world"]
        new = np.eye(4)
        new[:3, :3] = rotation @ camera_to_world[:3, :3]
        new[:3, 3] = transform[:3, :3] @ camera_to_world[:3, 3] + transform[:3, 3]
        moved.append({**camera, "camera_to_world": new})
    return moved, points @ transform[:3, :3].T + transform[:3, 3]
