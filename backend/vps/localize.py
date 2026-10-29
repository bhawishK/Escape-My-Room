"""Locate a camera frame against a room's positioning map (#133).

1. **Retrieval:** the map frames whose global descriptors are most like the frame's.
2. **Matching:** the frame's keypoints matched to each chosen map frame's (LightGlue on the GPU
   desktop; any `Matcher` here).
3. **Solve:** the matched map keypoints' 3D points give the camera's pose (`solve.solve_camera`).

The pose is in the map's frame, the splat's own: the room's manifest placement carries it into
room metres, as it does the splat.
"""

import time
from dataclasses import dataclass, field
from typing import Protocol

import numpy as np

from backend.reconstruction.vps_map import VpsMap
from backend.vps.solve import solve_camera

TOP_FRAMES = 10

# Keypoints, their descriptors, and the picture's (width, height).
type Features = tuple[np.ndarray, np.ndarray, tuple[int, int]]


class Matcher(Protocol):
    model: str

    def match(self, query: Features, map_frame: Features) -> np.ndarray:
        """Pairs of (query keypoint index, map keypoint index) that show the same spot."""
        ...


@dataclass(frozen=True)
class Query:
    keypoints: np.ndarray
    descriptors: np.ndarray
    global_descriptor: np.ndarray
    K: np.ndarray
    # The picture's (width, height) in pixels, the keypoints' frame.
    size: tuple[int, int]


@dataclass(frozen=True)
class Fix:
    # The camera's pose in the map's frame (x right, y down, z forward), or None.
    camera_to_world: np.ndarray | None
    inliers: int
    matches: int
    # The map frames it was matched against, most similar first.
    frames: list[str]
    reason: str | None
    seconds: dict[str, float] = field(default_factory=dict[str, float])


class Localizer:
    def __init__(self, vps: VpsMap, matcher: Matcher, top_frames: int = TOP_FRAMES) -> None:
        self.vps = vps
        self.matcher = matcher
        self.top_frames = top_frames
        norms = np.linalg.norm(vps.global_descriptors, axis=1, keepdims=True)
        self.globals = vps.global_descriptors / np.maximum(norms, 1e-12)

    def locate(self, query: Query) -> Fix:
        started = time.monotonic()
        wanted = query.global_descriptor / max(
            float(np.linalg.norm(query.global_descriptor)), 1e-12
        )
        order = np.argsort(-(self.globals @ wanted))[: self.top_frames]
        chosen = [self.vps.frames[int(index)] for index in order]
        retrieved = time.monotonic()
        pixels: list[np.ndarray] = []
        points: list[np.ndarray] = []
        for frame in chosen:
            pairs = self.matcher.match(
                (query.keypoints, query.descriptors, query.size),
                (frame.keypoints, frame.descriptors, frame.size),
            )
            if len(pairs):
                pixels.append(query.keypoints[pairs[:, 0]])
                points.append(frame.points3d[pairs[:, 1]])
        matched = time.monotonic()
        count = int(sum(len(p) for p in pixels))
        if count:
            solved = solve_camera(np.vstack(pixels), np.vstack(points), query.K)
        else:
            solved = None
        seconds = {
            "retrieval": round(retrieved - started, 4),
            "matching": round(matched - retrieved, 4),
            "solve": round(time.monotonic() - matched, 4),
        }
        names = [frame.name for frame in chosen]
        if solved is None:
            return Fix(None, 0, 0, names, "no matches in the chosen map frames", seconds)
        return Fix(solved.camera_to_world, solved.inliers, count, names, solved.reason, seconds)
