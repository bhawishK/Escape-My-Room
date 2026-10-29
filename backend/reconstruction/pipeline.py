"""Run the reconstruction's stages in order, reporting progress, and skip finished ones on restart.

Each stage that finishes leaves a marker in `<work>/stages/<name>.json` with its report and the
settings it used. A restart skips a stage whose marker is there with the same settings; once one
stage runs again, every stage after it runs too, since their inputs may have changed.
"""

import json
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

type Report = dict[str, Any]
type Progress = Callable[[Report], None]


@dataclass(frozen=True)
class Settings:
    """The notebook's settings. The defaults suit a 1–2 minute walk round a room."""

    frames_per_second: float = 2.0
    max_frames: int = 240
    long_side: int = 1600
    exhaustive_up_to: int = 150
    sequential_overlap: int = 15
    mapper: str = "incremental"
    camera_height_m: float = 1.4
    train_steps: int = 20_000
    max_splats: int = 400_000
    sh_degree: int = 1
    holdout_every: int = 10
    min_start_splats: int = 50_000
    # Splat training's share of the GPU, so the positioning service (#133) keeps its own.
    memory_budget_gb: float = 5.5


@dataclass
class StageContext:
    work: Path
    settings: Settings
    reports: dict[str, Report]
    # How long each stage before this one took, in seconds, from its first finished run.
    seconds: dict[str, float]
    step: Callable[[int, int, str], None]


@dataclass(frozen=True)
class Stage:
    name: str
    run: Callable[[StageContext], Report]
    # The settings this stage's output depends on; changing one runs it again.
    settings: tuple[str, ...] = ()


def run_pipeline(
    stages: list[Stage], work: Path, settings: Settings, progress: Progress
) -> dict[str, Report]:
    """Every stage's report, by name."""
    reports: dict[str, Report] = {}
    seconds: dict[str, float] = {}
    rerunning = False
    for stage in stages:
        started = time.monotonic()

        def emit(state: str, stage: Stage = stage, started: float = started, **fields: Any) -> None:
            elapsed = round(time.monotonic() - started, 1)
            progress({"stage": stage.name, "state": state, **fields, "seconds": elapsed})

        marker = work / "stages" / f"{stage.name}.json"
        used = stage_settings(stage, settings)
        if not rerunning and marker.is_file():
            done = json.loads(marker.read_text(encoding="utf-8"))
            if done["settings"] == used:
                reports[stage.name] = done["report"]
                seconds[stage.name] = done["seconds"]
                emit("skipped")
                continue
        rerunning = True
        emit("started")
        context = StageContext(
            work,
            settings,
            reports,
            seconds,
            lambda step, total, message, emit=emit: emit(
                "step", step=step, total=total, message=message
            ),
        )
        try:
            reports[stage.name] = stage.run(context)
        except Exception as exc:
            emit("failed", message=str(exc))
            raise
        seconds[stage.name] = round(time.monotonic() - started, 1)
        write_json(
            marker,
            {"settings": used, "report": reports[stage.name], "seconds": seconds[stage.name]},
        )
        emit("done")
    return reports


def stage_settings(stage: Stage, settings: Settings) -> dict[str, Any]:
    values = asdict(settings)
    return {key: values[key] for key in stage.settings}


def write_json(path: Path, value: Any) -> None:
    """Written whole or not at all, so a stop mid-write never leaves half a marker."""
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(path.suffix + ".partial")
    partial.write_text(json.dumps(value, indent=2), encoding="utf-8")
    partial.replace(path)
