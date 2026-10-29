"""The reconstruction's six stages, from a room video to a package `build_room.py` accepts."""

import json
import shutil
from dataclasses import asdict
from pathlib import Path

import numpy as np

from backend.reconstruction.levelling import Camera
from backend.reconstruction.pipeline import Report, Stage, StageContext


def video_to_room(video: Path, out: Path) -> list[Stage]:
    """The stages, writing intermediates to `out/work/` and the package to `out/`."""

    def frames(context: StageContext) -> Report:
        from backend.reconstruction.frames import extract_frames

        s = context.settings
        count = extract_frames(
            video, context.work / "frames", s.frames_per_second, s.long_side, s.max_frames
        )
        return {"video": video.name, "frames": count}

    def colmap(context: StageContext) -> Report:
        from backend.reconstruction.colmap import reconstruct

        s = context.settings
        report = reconstruct(
            context.work / "frames",
            context.work / "colmap",
            s.sequential_overlap,
            s.mapper,
            s.exhaustive_up_to,
        )
        if report["frames_placed"] < 0.8 * report["frames"]:
            report["warning"] = "Fewer than 80% of frames were placed; the splat will have gaps."
        return report

    def level(context: StageContext) -> Report:
        from backend.reconstruction.colmap import load_scene
        from backend.reconstruction.levelling import level_room

        cameras, points, _ = load_scene(context.work / "colmap" / "undistorted")
        transform, report = level_room(points, cameras, context.settings.camera_height_m)
        return report | {"transform": transform.tolist()}

    def splat(context: StageContext) -> Report:
        from backend.reconstruction.splat import train_within_budget
        from backend.reconstruction.training import train_splat

        cameras, points, colours = levelled_scene(context)
        training, memory = train_within_budget(
            lambda settings: train_splat(cameras, points, colours, settings, out, context.step),
            context.settings,
        )
        return training | {"memory": memory}

    def vps_map(context: StageContext) -> Report:
        from backend.reconstruction.colmap import write_levelled_model
        from backend.reconstruction.features import HuggingFaceExtractor
        from backend.reconstruction.training import depth_renderer
        from backend.reconstruction.vps_map import MapFrame, build_vps_map

        undistorted = context.work / "colmap" / "undistorted"
        target = out / "vps"
        shutil.rmtree(target, ignore_errors=True)
        cameras, _, _ = levelled_scene(context)
        # The levelled COLMAP model and its frames, kept for checks and other feature types.
        write_levelled_model(undistorted, transform_of(context), target / "sparse")
        shutil.copytree(undistorted / "images", target / "images")
        map_frames = [
            MapFrame(
                camera["name"],
                target / "images" / camera["name"],
                camera["K"],
                camera["camera_to_world"],
                camera["width"],
                camera["height"],
            )
            for camera in cameras
        ]
        return build_vps_map(
            map_frames,
            depth_renderer(out / "room.ply"),
            HuggingFaceExtractor(),
            target,
            context.step,
        )

    def package(context: StageContext) -> Report:
        cameras, _, _ = levelled_scene(context)
        reports = context.reports
        report = {
            "video": video.name,
            "settings": asdict(context.settings),
            "frames": reports["frames"]["frames"],
            "colmap": reports["colmap"],
            "levelling": {k: v for k, v in reports["level"].items() if k != "transform"},
            "levelling_transform": reports["level"]["transform"],
            "training": reports["splat"],
            "vps": reports["vps_map"],
            "stage_seconds": dict(context.seconds),
            "ply_mb": round((out / "room.ply").stat().st_size / 1e6, 1),
            # Where each frame was filmed from and the way it faced, so the viewer can start there.
            "cameras": [
                {
                    "name": camera["name"],
                    "position": camera["camera_to_world"][:3, 3].round(4).tolist(),
                    "forward": camera["camera_to_world"][:3, 2].round(4).tolist(),
                }
                for camera in cameras
            ],
        }
        (out / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        return {"report": "report.json", "ply_mb": report["ply_mb"]}

    return [
        Stage("frames", frames, ("frames_per_second", "max_frames", "long_side")),
        Stage("colmap", colmap, ("exhaustive_up_to", "sequential_overlap", "mapper")),
        Stage("level", level, ("camera_height_m",)),
        Stage(
            "splat",
            splat,
            (
                "train_steps",
                "max_splats",
                "sh_degree",
                "holdout_every",
                "min_start_splats",
                "memory_budget_gb",
            ),
        ),
        Stage("vps_map", vps_map),
        Stage("package", package),
    ]


def transform_of(context: StageContext) -> np.ndarray:
    return np.array(context.reports["level"]["transform"])


def levelled_scene(context: StageContext) -> tuple[list[Camera], np.ndarray, np.ndarray]:
    """COLMAP's cameras and points, moved by the levelling stage's similarity."""
    from backend.reconstruction.colmap import load_scene
    from backend.reconstruction.levelling import apply_transform

    cameras, points, colours = load_scene(context.work / "colmap" / "undistorted")
    cameras, points = apply_transform(transform_of(context), cameras, points)
    return cameras, points, colours
