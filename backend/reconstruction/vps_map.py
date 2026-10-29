"""The positioning map for #133: what Python matches the phone's camera frames against.

For each map frame (a COLMAP frame, levelled into the splat's own frame) it keeps:
- the frame's camera, `K` and `camera_to_world` (x right, y down, z forward);
- local keypoints and descriptors (SuperPoint by default), each with the 3D point it shows;
- one global descriptor, to find the frames worth matching quickly.

A keypoint's 3D point comes from the trained splat's depth at that pixel, so no re-triangulation is
needed, and frames rendered from the splat can be added the same way. Keypoints where the splat is
see-through have no reliable depth and are left out.

On disk, in `vps/`:
- `map.json`: the models used and each frame's camera;
- `frames/<frame>.npz`: keypoints, descriptors, scores and 3D points;
- `global.npz`: frame names and global descriptors, in the same order as `map.json`.

The map is in the splat's frame, so the room's manifest placement (rotation, scale, lift) carries
it into room metres exactly as it does the splat.
"""

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import numpy as np

# Rendered opacity a keypoint's pixel needs before its depth is trusted.
MIN_ALPHA = 0.9
VERSION = 1


@dataclass(frozen=True)
class MapFrame:
    name: str
    image: Path
    K: np.ndarray
    camera_to_world: np.ndarray
    width: int
    height: int


@dataclass(frozen=True)
class StoredFrame:
    name: str
    K: np.ndarray
    camera_to_world: np.ndarray
    keypoints: np.ndarray
    descriptors: np.ndarray
    scores: np.ndarray
    points3d: np.ndarray


@dataclass(frozen=True)
class VpsMap:
    local_model: str
    global_model: str
    frames: list[StoredFrame]
    global_descriptors: np.ndarray


class Extractor(Protocol):
    local_model: str
    global_model: str

    def local(self, image: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Keypoints as pixel (x, y), descriptors, and scores."""
        ...

    def global_descriptor(self, image: Path) -> np.ndarray: ...


# A frame's rendered depth (z in the camera) and opacity, each height x width.
type DepthRenderer = Callable[[MapFrame], tuple[np.ndarray, np.ndarray]]


def build_vps_map(
    frames: list[MapFrame],
    render_depth: DepthRenderer,
    extractor: Extractor,
    out: Path,
    step: Callable[[int, int, str], None] | None = None,
) -> dict[str, Any]:
    (out / "frames").mkdir(parents=True, exist_ok=True)
    entries: list[dict[str, Any]] = []
    globals_: list[np.ndarray] = []
    total = kept = 0
    for number, frame in enumerate(frames, start=1):
        keypoints, descriptors, scores = extractor.local(frame.image)
        depth, alpha = render_depth(frame)
        points, solid = unproject(frame, keypoints, depth, alpha)
        np.savez(
            out / "frames" / f"{Path(frame.name).stem}.npz",
            keypoints=keypoints[solid],
            descriptors=descriptors[solid],
            scores=scores[solid],
            points3d=points[solid],
        )
        globals_.append(extractor.global_descriptor(frame.image))
        entries.append(
            {
                "name": frame.name,
                "width": frame.width,
                "height": frame.height,
                "K": frame.K.tolist(),
                "camera_to_world": frame.camera_to_world.tolist(),
                "keypoints": int(solid.sum()),
            }
        )
        total += len(keypoints)
        kept += int(solid.sum())
        if step:
            step(number, len(frames), f"map frame {number} of {len(frames)}")
    np.savez(
        out / "global.npz",
        names=np.array([frame.name for frame in frames]),
        descriptors=np.array(globals_),
    )
    manifest = {
        "version": VERSION,
        "frame": "splat",
        "local_model": extractor.local_model,
        "global_model": extractor.global_model,
        "frames": entries,
    }
    (out / "map.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return {
        "frames": len(frames),
        "keypoints": total,
        "keypoints_with_depth": kept,
        "local_model": extractor.local_model,
        "global_model": extractor.global_model,
    }


def unproject(
    frame: MapFrame, keypoints: np.ndarray, depth: np.ndarray, alpha: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """Each keypoint's 3D point from the depth at its pixel, and whether that pixel was solid."""
    columns = np.clip(np.floor(keypoints[:, 0]).astype(int), 0, frame.width - 1)
    rows = np.clip(np.floor(keypoints[:, 1]).astype(int), 0, frame.height - 1)
    z = depth[rows, columns]
    solid = (alpha[rows, columns] >= MIN_ALPHA) & (z > 0)
    rays = np.linalg.inv(frame.K) @ np.vstack([keypoints.T, np.ones(len(keypoints))])
    in_camera = rays * z
    world = frame.camera_to_world[:3, :3] @ in_camera + frame.camera_to_world[:3, 3:4]
    return world.T, solid


def read_vps_map(folder: Path) -> VpsMap:
    manifest: dict[str, Any] = json.loads((folder / "map.json").read_text(encoding="utf-8"))
    frames: list[StoredFrame] = []
    for entry in manifest["frames"]:
        with np.load(folder / "frames" / f"{Path(entry['name']).stem}.npz") as stored:
            frames.append(
                StoredFrame(
                    entry["name"],
                    np.array(entry["K"]),
                    np.array(entry["camera_to_world"]),
                    stored["keypoints"],
                    stored["descriptors"],
                    stored["scores"],
                    stored["points3d"],
                )
            )
    with np.load(folder / "global.npz") as stored:
        descriptors = stored["descriptors"]
    return VpsMap(manifest["local_model"], manifest["global_model"], frames, descriptors)
