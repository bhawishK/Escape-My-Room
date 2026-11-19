"""The video frames' cameras, from COLMAP's binary model, placed in room metres (#206).

COLMAP's model is in its own frame. The room's report lists where each frame's camera stands in
the splat's own frame (as `backend.room_views.filmed` reads it), so a similarity (Umeyama) fitted
between the two carries every camera into the splat's frame, and the manifest's placement then
carries it into the room, as it carries the splat.
"""

from __future__ import annotations

import json
import struct
from dataclasses import dataclass
from pathlib import Path

import numpy as np

# COLMAP camera model id: (name, number of parameters).
MODELS = {0: ("SIMPLE_PINHOLE", 3), 1: ("PINHOLE", 4), 2: ("SIMPLE_RADIAL", 4), 3: ("RADIAL", 5),
          4: ("OPENCV", 8), 5: ("OPENCV_FISHEYE", 8), 6: ("FULL_OPENCV", 12)}


@dataclass
class Frame:
    """One frame's camera in room metres: world_to_camera turns room points into its view."""

    name: str
    rotation: np.ndarray  # room to camera
    centre: np.ndarray  # in room metres
    focal: tuple[float, float]
    principal: tuple[float, float]
    size: tuple[int, int]

    def project(self, points: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Pixel positions and depths (metres along the view) of room points."""
        local = (points - self.centre) @ self.rotation.T
        depth = local[:, 2]
        with np.errstate(divide="ignore", invalid="ignore"):
            u = self.focal[0] * local[:, 0] / depth + self.principal[0]
            v = self.focal[1] * local[:, 1] / depth + self.principal[1]
        return np.stack([u, v], axis=1), depth


def qvec_matrix(q: np.ndarray) -> np.ndarray:
    w, x, y, z = q
    return np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y)],
        [2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)],
        [2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)],
    ])


def read_cameras(path: Path) -> dict[int, tuple[str, int, int, np.ndarray]]:
    cameras = {}
    with open(path, "rb") as file:
        (count,) = struct.unpack("<Q", file.read(8))
        for _ in range(count):
            camera_id, model, width, height = struct.unpack("<iiQQ", file.read(24))
            name, params = MODELS[model]
            cameras[camera_id] = (name, width, height, np.array(struct.unpack(f"<{params}d", file.read(8 * params))))
    return cameras


def read_images(path: Path) -> list[tuple[str, np.ndarray, np.ndarray, int]]:
    """Each image's name, rotation (world to camera), translation and camera id."""
    images = []
    with open(path, "rb") as file:
        (count,) = struct.unpack("<Q", file.read(8))
        for _ in range(count):
            _image_id, *rest = struct.unpack("<i7di", file.read(64))
            q, t, camera_id = np.array(rest[:4]), np.array(rest[4:7]), rest[7]
            name = b""
            while (char := file.read(1)) != b"\0":
                name += char
            (points,) = struct.unpack("<Q", file.read(8))
            file.seek(24 * points, 1)
            images.append((name.decode(), qvec_matrix(q), t, camera_id))
    return images


def similarity(source: np.ndarray, target: np.ndarray) -> tuple[float, np.ndarray, np.ndarray]:
    """Scale, rotation and translation carrying source points onto target ones (Umeyama)."""
    ms, mt = source.mean(0), target.mean(0)
    cs, ct = source - ms, target - mt
    u, d, vt = np.linalg.svd(ct.T @ cs / len(source))
    flip = np.eye(3)
    if np.linalg.det(u @ vt) < 0:
        flip[2, 2] = -1
    rotation = u @ flip @ vt
    scale = np.trace(np.diag(d) @ flip) / (cs ** 2).sum(1).mean()
    return scale, rotation, mt - scale * rotation @ ms


def room_frames(model: Path, report: Path, placement=None) -> tuple[list[Frame], float]:
    """Every placed frame's camera in room metres (in the splat's frame without a placement), and the fit's RMS error."""
    cameras = read_cameras(model / "cameras.bin")
    images = read_images(model / "images.bin")
    listed = {camera["name"]: np.array(camera["position"]) for camera in json.loads(report.read_text())["cameras"]}
    centres = {name: -rotation.T @ t for name, rotation, t, _ in images}
    common = [name for name in centres if name in listed]
    source = np.array([centres[name] for name in common])
    target = np.array([listed[name] for name in common])
    scale, turn, shift = similarity(source, target)
    error = float(np.sqrt((((source * scale) @ turn.T + shift - target) ** 2).sum(1).mean()))
    frames = []
    for name, rotation, t, camera_id in images:
        model_name, width, height, params = cameras[camera_id]
        if model_name in ("SIMPLE_PINHOLE", "SIMPLE_RADIAL", "RADIAL"):
            focal, principal = (params[0], params[0]), (params[1], params[2])
        else:
            focal, principal = (params[0], params[1]), (params[2], params[3])
        # A splat-frame point p is at turn^T (p - shift) / scale in COLMAP; the camera turns that by R.
        to_camera, centre = rotation @ turn.T, scale * turn @ centres[name] + shift
        if placement is not None:
            # A room point r is at R_place^T (r - position) / s in the splat's frame; dropping the
            # 1/s keeps the view's depths in metres and leaves its pixels as they are.
            to_camera = to_camera @ placement.rotation.T
            centre = placement.to_room(centre[None])[0]
        frames.append(Frame(name, to_camera, centre, focal, principal, (width, height)))
    return frames, error
