"""Preparation jobs through a spawned service running the deterministic fixture worker."""

import hashlib
import json
import time
from pathlib import Path
from typing import Any

import httpx
from websockets.sync.client import connect

PHOTOS = Path(__file__).resolve().parents[1] / "frontend" / "tests" / "fixtures" / "photos"
FIXTURE_WORKER = {
    "ESCAPE_ROOM_PREPARATION_WORKER": "fixture",
    "ESCAPE_ROOM_FIXTURE_STAGE_SECONDS": "0.1",
}
STAGES = ["scene_understanding", "geometry", "stabilization", "export"]
POSE = {
    "type": "pose",
    "sequence": 1,
    "tracking_status": "tracked",
    "reference_space": "room",
    "position": {"x": 0.1, "y": 0.2, "z": -0.3},
}
INSTRUCTIONS = "The mug on the table hides the key."


def save_capture(url: str, *names: str) -> dict[str, Any]:
    files = [("images", (name, (PHOTOS / name).read_bytes())) for name in names]
    data = {"overview": "0", "instructions": INSTRUCTIONS}
    response = httpx.post(f"{url}/api/captures", files=files, data=data, timeout=5)
    assert response.status_code == 201, response.text
    return response.json()


def submit(url: str, capture: dict[str, Any], overview: str | None = None) -> httpx.Response:
    overview = overview or capture["overview_image_id"]
    body = {"capture_id": capture["id"], "overview_image_id": overview}
    return httpx.post(f"{url}/api/preparations", json=body, timeout=5)


def wait_until_settled(url: str, job_id: str) -> dict[str, Any]:
    for _ in range(100):
        job = httpx.get(f"{url}/api/preparations/{job_id}", timeout=5).json()
        if job["state"] in ("awaiting_review", "failed"):
            return job
        time.sleep(0.05)
    raise AssertionError(f"Job did not settle: {job}")


def test_a_saved_capture_becomes_a_reviewable_fixture_candidate(start_service, tmp_path):
    with start_service(tmp_path, **FIXTURE_WORKER) as url:
        room_before = httpx.get(f"{url}/api/room", timeout=5).json()
        capture = save_capture(url, "overview.png", "desk.jpg")
        response = submit(url, capture)
        assert response.status_code == 202, response.text
        assert response.json()["state"] == "queued"
        job = wait_until_settled(url, response.json()["id"])
        room_after = httpx.get(f"{url}/api/room", timeout=5).json()

    assert room_after == room_before
    assert job["state"] == "awaiting_review"
    assert job["finished_at"] is not None
    assert job["elapsed_seconds"] >= 0.4
    assert job["error"] is None
    assert job["input"]["capture_id"] == capture["id"]
    assert job["input"]["overview_image_id"] == capture["images"][0]["id"]
    assert job["input"]["image_sha256"] == [image["sha256"] for image in capture["images"]]
    assert job["input"]["instructions_sha256"] == hashlib.sha256(INSTRUCTIONS.encode()).hexdigest()
    assert job["config"]["worker"] == "fixture"
    assert len(job["input_hash"]) == 64
    assert [stage["name"] for stage in job["stages"]] == STAGES
    for stage in job["stages"]:
        assert stage["status"] == "done"
        assert stage["elapsed_seconds"] >= 0.1
        assert stage["artifacts"], stage["name"]
    candidate = job["candidate"]
    assert candidate["source"] == "fixture"
    assert candidate["label"] == "Fixture output, not AI inference"
    assert [(item["id"], item["kind"]) for item in candidate["entities"]] == [
        ("floor", "static"),
        ("table", "static"),
        ("mug", "movable"),
        ("book", "movable"),
    ]


def test_invalid_requests_create_no_job(start_service, tmp_path):
    with start_service(tmp_path / "configured", **FIXTURE_WORKER) as url:
        capture = save_capture(url, "overview.png", "desk.jpg")
        other = save_capture(url, "camera.jpg")
        unknown = {**capture, "id": "cap_" + "0" * 32}
        refused = [
            (submit(url, unknown), 404, "That capture does not exist."),
            (
                submit(url, capture, overview=other["images"][0]["id"]),
                400,
                "Choose an overview photo from this capture.",
            ),
        ]
        for response, status, detail in refused:
            assert (response.status_code, response.json()["detail"]) == (status, detail)
        assert httpx.get(f"{url}/api/preparations", timeout=5).json()["jobs"] == []

    with start_service(tmp_path / "unconfigured") as url:
        capture = save_capture(url, "overview.png")
        response = submit(url, capture)
        assert response.status_code == 503
        assert response.json()["detail"] == "Room preparation is not configured on this server."
        assert httpx.get(f"{url}/api/preparations", timeout=5).json()["jobs"] == []


def test_a_failed_stage_stays_inspectable_and_leaves_the_room_alone(start_service, tmp_path):
    failing = FIXTURE_WORKER | {"ESCAPE_ROOM_FIXTURE_FAIL_STAGE": "geometry"}
    with start_service(tmp_path, **failing) as url:
        room_before = httpx.get(f"{url}/api/room", timeout=5).json()
        capture = save_capture(url, "overview.png")
        job = wait_until_settled(url, submit(url, capture).json()["id"])
        listed = httpx.get(f"{url}/api/preparations", timeout=5).json()["jobs"]
        room_after = httpx.get(f"{url}/api/room", timeout=5).json()

    assert job["state"] == "failed"
    assert job["error"] == {
        "stage": "geometry",
        "kind": "fixture",
        "message": "The fixture worker was configured to fail at the geometry stage.",
    }
    assert [(stage["name"], stage["status"]) for stage in job["stages"]] == [
        ("scene_understanding", "done"),
        ("geometry", "failed"),
        ("stabilization", "pending"),
        ("export", "pending"),
    ]
    assert job["stages"][1]["elapsed_seconds"] >= 0.1
    assert job["candidate"] is None
    assert listed == [job]
    assert room_after == room_before


def test_jobs_run_one_at_a_time_while_devices_stay_responsive(start_service, tmp_path):
    slow = FIXTURE_WORKER | {"ESCAPE_ROOM_FIXTURE_STAGE_SECONDS": "0.3"}
    with start_service(tmp_path, **slow) as url:
        capture = save_capture(url, "overview.png")
        socket_url = f"{url.replace('http://', 'ws://')}/api/ws?role=mobile_master"
        with connect(socket_url) as phone:
            json.loads(phone.recv(timeout=1))
            first = submit(url, capture).json()
            second = submit(url, capture).json()
            time.sleep(0.15)
            running = httpx.get(f"{url}/api/preparations/{first['id']}", timeout=5).json()
            waiting = httpx.get(f"{url}/api/preparations/{second['id']}", timeout=5).json()
            started = time.monotonic()
            phone.send(json.dumps(POSE))
            accepted = json.loads(phone.recv(timeout=1))
            assert time.monotonic() - started < 0.5
        assert accepted["state"]["marker"]["tracking_status"] == "tracked"
        assert (running["state"], waiting["state"]) == ("running", "queued")
        assert running["stages"][0]["status"] == "running"
        assert running["stages"][0]["elapsed_seconds"] > 0
        assert running["elapsed_seconds"] > 0
        first_done = wait_until_settled(url, first["id"])
        second_done = wait_until_settled(url, second["id"])

    assert first_done["state"] == second_done["state"] == "awaiting_review"
    assert second_done["stages"][0]["started_at"] >= first_done["stages"][-1]["finished_at"]


def test_jobs_cut_off_by_a_restart_are_marked_interrupted(start_service, tmp_path):
    slow = FIXTURE_WORKER | {"ESCAPE_ROOM_FIXTURE_STAGE_SECONDS": "5"}
    with start_service(tmp_path, **slow) as url:
        capture = save_capture(url, "overview.png")
        running = submit(url, capture).json()
        queued = submit(url, capture).json()
        for _ in range(40):
            job = httpx.get(f"{url}/api/preparations/{running['id']}", timeout=5).json()
            if job["state"] == "running":
                break
            time.sleep(0.05)
    with start_service(tmp_path, **FIXTURE_WORKER) as url:
        listed = httpx.get(f"{url}/api/preparations", timeout=5).json()["jobs"]
        jobs = {job["id"]: job for job in listed}

    message = "The service restarted before this job finished. Submit it again."
    cut_off = jobs[running["id"]]
    assert cut_off["state"] == "failed"
    assert cut_off["error"] == {
        "stage": "scene_understanding",
        "kind": "interrupted",
        "message": message,
    }
    assert cut_off["stages"][0]["status"] == "failed"
    never_started = jobs[queued["id"]]
    assert never_started["state"] == "failed"
    assert never_started["error"] == {"stage": None, "kind": "interrupted", "message": message}
