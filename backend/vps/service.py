"""Locating the phone's camera frames in the live room, for `POST /api/localize` (#133).

The live room's positioning map is read on the first frame after the room changes, and the
feature models load on the first frame at all (on the GPU desktop's GPU when it has one). A fix
comes back in room metres: the map sits in the splat's own frame, so the room's splat placement
(scaled, then rotated, then moved) carries it there exactly as it carries the splat. Its
orientation is the room camera's, as three.js has it: x right, y up, looking down -z.

One frame is located at a time; frames are never stored.
"""

import io
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import BinaryIO, Protocol

import numpy as np

from backend.errors import Refusal
from backend.prepared_room import SplatPlacement
from backend.reconstruction.vps_map import read_vps_map
from backend.vps.localize import Localizer, Matcher, Query
from backend.vps.matching import MutualNearest

# COLMAP's camera (x right, y down, z forward) as three.js's (x right, y up, z back).
COLMAP_TO_THREE = np.diag([1.0, -1.0, -1.0])


class FrameExtractor(Protocol):
    def local(self, image: BinaryIO) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Keypoints as pixel (x, y), descriptors, and scores."""
        ...

    def global_descriptor(self, image: BinaryIO) -> np.ndarray: ...


def hugging_face_extractor() -> FrameExtractor:
    """The models the maps are built with, on the GPU when there is one."""
    import torch  # pyright: ignore[reportMissingImports]

    from backend.reconstruction.features import HuggingFaceExtractor

    return HuggingFaceExtractor("cuda" if torch.cuda.is_available() else "cpu")


@dataclass(frozen=True)
class Located:
    room_version: int | None
    # In room metres and the room camera's orientation (x, y, z, w); None without a fix.
    position: tuple[float, float, float] | None
    orientation: tuple[float, float, float, float] | None
    inliers: int
    matches: int
    reason: str | None
    seconds: dict[str, float] = field(default_factory=dict[str, float])

    def wire(self) -> dict[str, object]:
        return {
            "located": self.position is not None,
            "room_version": self.room_version,
            "position": None
            if self.position is None
            else dict(zip("xyz", self.position, strict=True)),
            "orientation": None
            if self.orientation is None
            else dict(zip("xyzw", self.orientation, strict=True)),
            "inliers": self.inliers,
            "matches": self.matches,
            "reason": self.reason,
            "seconds": self.seconds,
        }


def rotation_matrix(x: float, y: float, z: float, w: float) -> np.ndarray:
    return np.array(
        [
            [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
        ]
    )


def quaternion(matrix: np.ndarray) -> tuple[float, float, float, float]:
    """The unit quaternion (x, y, z, w) of a rotation matrix, with w >= 0."""
    m = matrix
    w = np.sqrt(max(0.0, 1 + m[0, 0] + m[1, 1] + m[2, 2])) / 2
    x = np.sqrt(max(0.0, 1 + m[0, 0] - m[1, 1] - m[2, 2])) / 2
    y = np.sqrt(max(0.0, 1 - m[0, 0] + m[1, 1] - m[2, 2])) / 2
    z = np.sqrt(max(0.0, 1 - m[0, 0] - m[1, 1] + m[2, 2])) / 2
    x = float(np.copysign(x, m[2, 1] - m[1, 2]))
    y = float(np.copysign(y, m[0, 2] - m[2, 0]))
    z = float(np.copysign(z, m[1, 0] - m[0, 1]))
    norm = np.sqrt(x * x + y * y + z * z + w * w)
    return (x / norm, y / norm, z / norm, float(w) / norm)


def in_room(
    camera_to_world: np.ndarray, placement: SplatPlacement | None
) -> tuple[tuple[float, float, float], tuple[float, float, float, float]]:
    """A camera pose in the map's frame as a room position and room camera orientation."""
    place = placement or SplatPlacement()
    turn = rotation_matrix(place.rotation.x, place.rotation.y, place.rotation.z, place.rotation.w)
    shift = np.array([place.position.x, place.position.y, place.position.z])
    position = shift + place.scale * turn @ camera_to_world[:3, 3]
    x, y, z = (round(float(value), 4) for value in position)
    facing = quaternion(turn @ camera_to_world[:3, :3] @ COLMAP_TO_THREE)
    return (x, y, z), tuple(round(value, 6) for value in facing)  # pyright: ignore[reportReturnType]


@dataclass(frozen=True)
class LiveMap:
    directory: Path
    placement: SplatPlacement | None
    room_version: int | None


class Positioning:
    def __init__(
        self,
        extractor: Callable[[], FrameExtractor] = hugging_face_extractor,
        matcher: Matcher | None = None,
    ) -> None:
        self.make_extractor = extractor
        self.matcher = matcher or MutualNearest()
        self.lock = threading.Lock()
        self.extractor: FrameExtractor | None = None
        self.room: LiveMap | None = None
        self.localizer: Localizer | None = None

    def use(
        self, directory: Path, placement: SplatPlacement | None, room_version: int | None
    ) -> None:
        """Locate against this room from now on; its map is read on the next frame."""
        with self.lock:
            self.room = LiveMap(directory, placement, room_version)
            self.localizer = None

    @property
    def available(self) -> bool:
        """Whether the live room has a positioning map."""
        room = self.room
        return room is not None and (room.directory / "vps" / "map.json").is_file()

    def locate(self, jpeg: bytes, K: np.ndarray, size: tuple[int, int]) -> Located:
        """Where the camera that took `jpeg` stood, with its intrinsics `K` for that picture."""
        with self.lock:
            room = self.room
            if room is None or not self.available:
                raise Refusal("The live room has no positioning map.", 404)
            started = time.monotonic()
            extractor = self.loaded_extractor()
            if self.localizer is None:
                self.localizer = Localizer(read_vps_map(room.directory / "vps"), self.matcher)
            ready = time.monotonic()
            keypoints, descriptors, _ = extractor.local(io.BytesIO(jpeg))
            described = extractor.global_descriptor(io.BytesIO(jpeg))
            featured = time.monotonic()
            fix = self.localizer.locate(Query(keypoints, descriptors, described, K, size))
            seconds = {
                "loading": round(ready - started, 4),
                "features": round(featured - ready, 4),
                **fix.seconds,
                "total": round(time.monotonic() - started, 4),
            }
            if fix.camera_to_world is None:
                return Located(
                    room.room_version, None, None, fix.inliers, fix.matches, fix.reason, seconds
                )
            position, orientation = in_room(fix.camera_to_world, room.placement)
            return Located(
                room.room_version, position, orientation, fix.inliers, fix.matches, None, seconds
            )

    def loaded_extractor(self) -> FrameExtractor:
        if self.extractor is None:
            try:
                self.extractor = self.make_extractor()
            except (ImportError, OSError) as exc:
                raise Refusal(f"Positioning is not available on this server: {exc}", 503) from exc
        return self.extractor
