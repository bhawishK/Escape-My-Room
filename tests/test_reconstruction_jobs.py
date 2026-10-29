"""Reconstruction jobs (#137) through a spawned service: a room video becomes a reconstruction to
review, with each stage's progress, run by a fake pipeline that uses the real stage runner."""

import json
import sys
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from conftest import StartService
from test_video_uploads import chunks, fixture_video

ROOT = Path(__file__).resolve().parents[1]
STAGES = ["frames", "colmap", "level", "splat", "vps_map", "package"]
FAKE = [sys.executable, str(ROOT / "tests" / "fake_reconstruction.py")]


def settings(**extra: str) -> dict[str, str]:
    return {
        "ESCAPE_ROOM_VIDEO_PROBE": "fixture",
        "ESCAPE_ROOM_VIDEO_CHUNK_BYTES": "1024",
        "ESCAPE_ROOM_VIDEO_WORKER": "reconstruction",
        "ESCAPE_ROOM_RECONSTRUCTION_COMMAND": json.dumps(FAKE),
        # The fake pipeline needs no GPU.
        "ESCAPE_ROOM_RECONSTRUCTION_REQUIRE_GPU": "0",
        **extra,
    }


def save_video(url: str) -> dict[str, Any]:
    video = fixture_video()
    upload = httpx.post(
        f"{url}/api/videos",
        json={"filename": "hallway.mov", "size_bytes": len(video), "media_type": "video/quicktime"},
        timeout=5,
    ).json()
    for number, part in enumerate(chunks(video)):
        httpx.put(f"{url}/api/videos/{upload['id']}/chunks/{number}", content=part, timeout=5)
    done = httpx.post(f"{url}/api/videos/{upload['id']}/complete", json={}, timeout=5)
    assert done.status_code == 201, done.text
    return done.json()


def submit(url: str, capture: dict[str, Any]) -> dict[str, Any]:
    response = httpx.post(f"{url}/api/preparations", json={"capture_id": capture["id"]}, timeout=5)
    assert response.status_code == 202, response.text
    return response.json()


def job(url: str, job_id: str) -> dict[str, Any]:
    return httpx.get(f"{url}/api/preparations/{job_id}", timeout=5).json()


def wait_until_finished(url: str, job_id: str, limit: float = 30) -> dict[str, Any]:
    deadline = time.monotonic() + limit
    while time.monotonic() < deadline:
        found = job(url, job_id)
        if found["state"] in ("awaiting_review", "failed"):
            return found
        time.sleep(0.1)
    raise AssertionError(f"The job did not finish in {limit} s: {json.dumps(found, indent=1)}")


@pytest.fixture
def service(start_service: StartService, tmp_path: Path) -> Iterator[str]:
    with start_service(tmp_path, **settings()) as url:
        yield url


def test_a_room_video_becomes_a_reconstruction_to_review(service: str) -> None:
    capture = save_video(service)

    submitted = submit(service, capture)
    assert submitted["state"] == "queued"
    assert [stage["name"] for stage in submitted["stages"]] == STAGES
    finished = wait_until_finished(service, submitted["id"])

    assert finished["state"] == "awaiting_review", finished["error"]
    assert finished["config"]["worker"] == "reconstruction"
    assert finished["input"]["capture_id"] == capture["id"]
    assert finished["input"]["image_sha256"] == [capture["sha256"]]
    assert [stage["status"] for stage in finished["stages"]] == ["done"] * 6
    assert finished["reconstruction"] == {
        "video": "hallway.mov",
        "frames": 120,
        "frames_placed": 118,
        "splats": 300000,
        "psnr_db": 24.5,
        "peak_gpu_memory_gb": 4.2,
        "memory_retried": False,
        "map_keypoints": 200000,
        "splat": "reconstruction/room.ply",
        "report": "reconstruction/report.json",
        "previews": ["reconstruction/previews/frame_0000.jpg.jpg"],
    }
    splat_stage = finished["stages"][3]
    assert [a["path"] for a in splat_stage["artifacts"]] == [
        "reconstruction/work/stages/splat.json"
    ]
    report = httpx.get(
        f"{service}/api/preparations/{finished['id']}/files/reconstruction/report.json", timeout=5
    )
    assert report.json()["frames"] == 120


def test_training_steps_show_on_the_job_while_it_runs(
    start_service: StartService, tmp_path: Path
) -> None:
    with start_service(tmp_path, **settings(FAKE_RECONSTRUCTION_STAGE_SECONDS="0.4")) as url:
        submitted = submit(url, save_video(url))
        seen: dict[str, Any] | None = None
        deadline = time.monotonic() + 30
        while seen is None and time.monotonic() < deadline:
            splat = job(url, submitted["id"])["stages"][3]
            if splat["status"] == "running" and splat["step"]:
                seen = splat
            time.sleep(0.05)

        assert seen is not None, json.dumps(job(url, submitted["id"]), indent=1)
        assert seen["total"] == 3
        assert seen["message"] == f"{seen['step'] * 1000:,} splats"
        assert seen["elapsed_seconds"] >= 0
        assert [s["status"] for s in job(url, submitted["id"])["stages"][:3]] == ["done"] * 3


@pytest.mark.parametrize(
    ("fault", "stage", "kind", "message"),
    [
        (
            {"FAKE_RECONSTRUCTION_DIE_AT": "colmap"},
            "colmap",
            "worker",
            "The reconstruction process stopped unexpectedly (exit code 9).",
        ),
        (
            {"FAKE_RECONSTRUCTION_OUT_OF_MEMORY": "1"},
            "splat",
            "resource",
            "Splat training ran out of GPU memory at 1600 px.",
        ),
    ],
)
def test_a_pipeline_that_dies_or_runs_out_of_gpu_memory_fails_the_job_at_its_stage(
    start_service: StartService,
    tmp_path: Path,
    fault: dict[str, str],
    stage: str,
    kind: str,
    message: str,
) -> None:
    with start_service(tmp_path, **settings(**fault)) as url:
        finished = wait_until_finished(url, submit(url, save_video(url))["id"])

    assert finished["state"] == "failed"
    assert finished["error"] == {"stage": stage, "kind": kind, "message": message}
    statuses = {s["name"]: s["status"] for s in finished["stages"]}
    assert statuses[stage] == "failed"
    assert statuses["package"] == "pending"
    assert finished["reconstruction"] is None


def test_a_server_without_a_gpu_says_so(start_service: StartService, tmp_path: Path) -> None:
    # The real check: no nvidia-smi on the search path.
    gpu_needed = settings(ESCAPE_ROOM_RECONSTRUCTION_REQUIRE_GPU="1", PATH="")
    with start_service(tmp_path, **gpu_needed) as url:
        finished = wait_until_finished(url, submit(url, save_video(url))["id"])

    assert finished["state"] == "failed"
    assert finished["error"]["kind"] == "configuration"
    assert finished["error"]["message"] == (
        "This server has no NVIDIA GPU (nvidia-smi was not found); room videos are "
        "reconstructed on the GPU desktop."
    )


def test_a_restart_during_training_resumes_the_job_without_redoing_finished_stages(
    start_service: StartService, tmp_path: Path
) -> None:
    slow = settings(FAKE_RECONSTRUCTION_STAGE_SECONDS="0.5")
    with start_service(tmp_path, **slow) as url:
        submitted = submit(url, save_video(url))
        deadline = time.monotonic() + 30
        while job(url, submitted["id"])["stages"][3]["status"] != "running":
            assert time.monotonic() < deadline, "Training never started."
            time.sleep(0.05)
    # The service is gone, and the pipeline it started stopped with it.
    time.sleep(1.5)

    with start_service(tmp_path, **slow) as url:
        finished = wait_until_finished(url, submitted["id"])

    assert finished["state"] == "awaiting_review", finished["error"]
    ran = (tmp_path / "jobs" / submitted["id"] / "reconstruction" / "ran.txt").read_text()
    assert ran.split() == ["frames", "colmap", "level", "splat", "splat", "vps_map", "package"]
