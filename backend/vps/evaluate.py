"""The offline test of visual positioning (#133), on the GPU desktop:

    python -m backend.vps.evaluate ROOM QUERY [--every N] [--report PATH]

ROOM is a built room with a positioning map (`ROOM/vps/`). QUERY is the COLMAP folder of another
video of the same place, as the reconstruction pipeline leaves it: `QUERY/sparse` and
`QUERY/images`, for example `data/jobs/<job>/reconstruction/work/colmap/undistorted`. Every Nth of
its placed frames is located against the map, with that video's own COLMAP intrinsics. Its COLMAP
poses are the reference the located ones are aligned to and compared with.

Prints one line per frame and a summary: the share located, the error of the located ones, and
the time each step takes; `--report` also writes it all as JSON.
"""

# torch and transformers are only installed on the GPU desktop.
# pyright: basic
# pyright: reportMissingImports=false

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

from backend.reconstruction.colmap import load_scene
from backend.reconstruction.features import HuggingFaceExtractor
from backend.reconstruction.vps_map import read_vps_map
from backend.vps.accuracy import compare
from backend.vps.localize import Localizer, Query
from backend.vps.matching import MutualNearest

# The bar #133 set before the phone side is built.
LOCATED_SHARE = 0.7
MEDIAN_ERROR_M = 0.10
MEDIAN_ERROR_DEGREES = 3.0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="python -m backend.vps.evaluate")
    parser.add_argument("room", type=Path)
    parser.add_argument("query", type=Path)
    parser.add_argument("--every", type=int, default=2)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)

    vps = read_vps_map(args.room / "vps")
    localizer = Localizer(vps, MutualNearest())
    extractor = HuggingFaceExtractor()
    cameras, _, _ = load_scene(args.query)
    cameras = cameras[:: args.every]
    print(f"{len(vps.frames)} map frames; locating {len(cameras)} query frames", flush=True)

    frames, located, reference = [], [], []
    for camera in cameras:
        started = time.monotonic()
        keypoints, descriptors, _ = extractor.local(camera["path"])
        described = time.monotonic()
        query = Query(
            keypoints,
            descriptors,
            extractor.global_descriptor(camera["path"]),
            camera["K"],
            (camera["width"], camera["height"]),
        )
        fix = localizer.locate(query)
        seconds = {"features": round(described - started, 3), **fix.seconds}
        seconds["total"] = round(time.monotonic() - started, 3)
        frames.append(
            {
                "name": camera["name"],
                "keypoints": len(keypoints),
                "matches": fix.matches,
                "inliers": fix.inliers,
                "located": fix.camera_to_world is not None,
                "reason": fix.reason,
                "seconds": seconds,
                # The map frames it was compared with, most similar first, to see what it saw.
                "map_frames": fix.frames[:3],
                "camera_to_world": None
                if fix.camera_to_world is None
                else fix.camera_to_world.round(5).tolist(),
            }
        )
        if fix.camera_to_world is not None:
            located.append(fix.camera_to_world)
            reference.append(camera["camera_to_world"])
        status = "located" if fix.camera_to_world is not None else f"not located: {fix.reason}"
        print(
            f"{camera['name']}: {len(keypoints)} keypoints, {fix.matches} matches, "
            f"{fix.inliers} inliers, {seconds['total']:.2f} s, {status}",
            flush=True,
        )

    share = len(located) / len(cameras) if cameras else 0.0
    summary: dict = {
        "map_frames": len(vps.frames),
        "query_frames": len(cameras),
        "located": len(located),
        "located_share": round(share, 3),
        "median_seconds": float(np.median([f["seconds"]["total"] for f in frames])),
    }
    if len(located) >= 3:
        accuracy = compare(located, reference)
        summary |= {
            "median_position_error": round(accuracy.median_position_error, 3),
            "p90_position_error": round(accuracy.p90_position_error, 3),
            "median_rotation_error_degrees": round(accuracy.median_rotation_error_degrees, 2),
            "map_to_reference_scale": round(accuracy.scale, 4),
        }
        summary["passes"] = bool(
            share >= LOCATED_SHARE
            and accuracy.median_position_error <= MEDIAN_ERROR_M
            and accuracy.median_rotation_error_degrees <= MEDIAN_ERROR_DEGREES
        )
    else:
        summary["passes"] = False
    print(json.dumps(summary, indent=2))
    if args.report:
        args.report.write_text(json.dumps({"summary": summary, "frames": frames}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
