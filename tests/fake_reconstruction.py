"""A stand-in for `python -m backend.reconstruction` (#137), for tests without a GPU.

    python tests/fake_reconstruction.py VIDEO OUT [--watch-stdin]

It uses the real stage runner, so progress lines, stage markers and skipping on a restart are the
real ones; only the six stages are fakes that wait briefly and write small files. Settings:
- FAKE_RECONSTRUCTION_STAGE_SECONDS: how long each stage takes (default 0.2).
- FAKE_RECONSTRUCTION_DIE_AT: a stage at which the process dies without a word, as if killed.
- FAKE_RECONSTRUCTION_OUT_OF_MEMORY: "twice" makes splat training run out of GPU memory twice;
  "once" makes it run out once and train again smaller, through the real retry.
- FAKE_RECONSTRUCTION_BROKEN_SPLAT: "1" writes a `room.ply` no room can be built from.

The splat it writes is `build_room.py`'s small test splat, a floor and a block, so the real room
build (#138) can run on it.
"""

import importlib.util
import json
import os
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.reconstruction.__main__ import stop_when_stdin_closes  # noqa: E402
from backend.reconstruction.pipeline import Settings, Stage, StageContext, run_pipeline  # noqa: E402
from backend.reconstruction.splat import OutOfGpuMemory, train_within_budget  # noqa: E402

SECONDS = float(os.environ.get("FAKE_RECONSTRUCTION_STAGE_SECONDS") or 0.2)
DIE_AT = os.environ.get("FAKE_RECONSTRUCTION_DIE_AT")
OUT_OF_MEMORY = os.environ.get("FAKE_RECONSTRUCTION_OUT_OF_MEMORY")
TRAINING_STEPS = 3
BROKEN_SPLAT = os.environ.get("FAKE_RECONSTRUCTION_BROKEN_SPLAT") == "1"


def write_test_splat(path: Path) -> None:
    spec = importlib.util.spec_from_file_location(
        "splat_build_room", ROOT / "assets" / "splat-room" / "build_room.py"
    )
    assert spec and spec.loader
    build_room = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(build_room)
    build_room.write_test_splat(path)


def main() -> int:
    video, out = Path(sys.argv[1]), Path(sys.argv[2])
    out.mkdir(parents=True, exist_ok=True)
    if "--watch-stdin" in sys.argv:
        threading.Thread(target=stop_when_stdin_closes, daemon=True).start()

    def stage(name: str, report: dict, write=None) -> Stage:
        def run(context: StageContext) -> dict:
            # Each stage actually run, so a test can see a restart skip the finished ones.
            with open(out / "ran.txt", "a", encoding="utf-8") as ran:
                ran.write(name + "\n")
            if DIE_AT == name:
                os._exit(9)
            if name == "splat":
                for step in range(1, TRAINING_STEPS + 1):
                    time.sleep(SECONDS)
                    context.step(step, TRAINING_STEPS, f"{step * 1000:,} splats")
                if OUT_OF_MEMORY == "twice":
                    raise OutOfGpuMemory("Splat training ran out of GPU memory at 1600 px.")
                if OUT_OF_MEMORY == "once":
                    tries: list[int] = []

                    def train(settings: Settings) -> None:
                        tries.append(settings.long_side)
                        if len(tries) == 1:
                            raise OutOfGpuMemory("CUDA out of memory")

                    _, memory = train_within_budget(train, context.settings)
                    return report | {"memory": memory}
            else:
                time.sleep(SECONDS)
            if write:
                write()
            return report

        return Stage(name, run)

    def package() -> None:
        if BROKEN_SPLAT:
            (out / "room.ply").write_bytes(b"ply\n")
        else:
            write_test_splat(out / "room.ply")
        (out / "previews").mkdir(parents=True, exist_ok=True)
        (out / "previews" / "frame_0000.jpg.jpg").write_bytes(b"jpeg")
        (out / "vps").mkdir(parents=True, exist_ok=True)
        (out / "vps" / "map.json").write_text("{}", encoding="utf-8")
        report = {"video": video.name, "frames": 120, "training": {"splats": 300000}}
        (out / "report.json").write_text(json.dumps(report), encoding="utf-8")

    stages = [
        stage("frames", {"video": video.name, "frames": 120}),
        stage("colmap", {"frames": 120, "frames_placed": 118, "mapper": "incremental"}),
        stage("level", {"scale": 2.1}),
        stage(
            "splat",
            {
                "splats": 300000,
                "psnr_db": 24.5,
                "peak_gpu_memory_gb": 4.2,
                "memory": {"retried": False, "attempts": []},
            },
        ),
        stage("vps_map", {"frames": 118, "keypoints": 240000, "keypoints_with_depth": 200000}),
        stage("package", {"report": "report.json", "ply_mb": 30.0}, package),
    ]
    try:
        run_pipeline(stages, out / "work", Settings(), lambda e: print(json.dumps(e), flush=True))
    except OutOfGpuMemory:
        return 3
    except Exception:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
