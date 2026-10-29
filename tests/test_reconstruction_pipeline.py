"""The reconstruction pipeline's stage runner (#135): stages run in order, report what they did,
and a restart skips the stages that already finished."""

import time
from pathlib import Path

import pytest

from backend.reconstruction.pipeline import Settings, Stage, StageContext, run_pipeline


def recording(name: str, log: list[str], keys: tuple[str, ...] = ()) -> Stage:
    def run(context: StageContext) -> dict:
        log.append(name)
        context.step(1, 2, "halfway")
        return {"ran": name}

    return Stage(name, run, keys)


def test_stages_run_in_order_and_report(tmp_path: Path) -> None:
    log: list[str] = []
    events: list[dict] = []

    reports = run_pipeline(
        [recording("frames", log), recording("colmap", log)], tmp_path, Settings(), events.append
    )

    assert log == ["frames", "colmap"]
    assert reports == {"frames": {"ran": "frames"}, "colmap": {"ran": "colmap"}}
    assert [(e["stage"], e["state"]) for e in events] == [
        ("frames", "started"),
        ("frames", "step"),
        ("frames", "done"),
        ("colmap", "started"),
        ("colmap", "step"),
        ("colmap", "done"),
    ]
    assert events[1] | {"seconds": 0} == {
        "stage": "frames",
        "state": "step",
        "step": 1,
        "total": 2,
        "message": "halfway",
        "seconds": 0,
    }


def test_a_restart_skips_finished_stages(tmp_path: Path) -> None:
    first: list[str] = []
    run_pipeline([recording("frames", first)], tmp_path, Settings(), lambda _: None)

    again: list[str] = []
    events: list[dict] = []
    reports = run_pipeline(
        [recording("frames", again), recording("colmap", again)],
        tmp_path,
        Settings(),
        events.append,
    )

    assert again == ["colmap"]
    assert reports["frames"] == {"ran": "frames"}
    assert ("frames", "skipped") in [(e["stage"], e["state"]) for e in events]


def test_a_changed_setting_reruns_its_stage_and_the_ones_after(tmp_path: Path) -> None:
    def stages(log: list[str]) -> list[Stage]:
        return [
            recording("frames", log, ("max_frames",)),
            recording("splat", log, ("train_steps",)),
            recording("package", log),
        ]

    run_pipeline(stages([]), tmp_path, Settings(), lambda _: None)
    again: list[str] = []
    run_pipeline(stages(again), tmp_path, Settings(train_steps=500), lambda _: None)

    assert again == ["splat", "package"]


def test_later_stages_see_how_long_earlier_ones_took_even_after_a_restart(tmp_path: Path) -> None:
    def slow(context: StageContext) -> dict:
        time.sleep(0.15)
        return {}

    seen: list[dict[str, float]] = []

    def package(context: StageContext) -> dict:
        seen.append(dict(context.seconds))
        return {}

    run_pipeline([Stage("colmap", slow)], tmp_path, Settings(), lambda _: None)
    run_pipeline(
        [Stage("colmap", slow), Stage("package", package)], tmp_path, Settings(), lambda _: None
    )

    assert list(seen[0]) == ["colmap"]
    assert seen[0]["colmap"] >= 0.1


def test_a_failed_stage_is_reported_and_runs_again_next_time(tmp_path: Path) -> None:
    def broken(context: StageContext) -> dict:
        raise RuntimeError("COLMAP could not place the frames.")

    events: list[dict] = []
    with pytest.raises(RuntimeError):
        run_pipeline([Stage("colmap", broken)], tmp_path, Settings(), events.append)

    assert events[-1]["state"] == "failed"
    assert events[-1]["message"] == "COLMAP could not place the frames."
    again: list[str] = []
    run_pipeline([recording("colmap", again)], tmp_path, Settings(), lambda _: None)
    assert again == ["colmap"]
