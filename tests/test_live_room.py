"""Making a reconstructed room live (#138), through a spawned service: the fake pipeline writes a
small real splat, the real `build_room.py` builds it, and connected devices get the new room."""

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from conftest import StartService
from test_manipulation import Phone, open_socket
from test_reconstruction_jobs import save_video, settings, submit, wait_until_finished
from websockets.sync.client import connect


def reconstructed(url: str) -> dict[str, Any]:
    """A finished reconstruction job, awaiting review."""
    finished = wait_until_finished(url, submit(url, save_video(url))["id"])
    assert finished["state"] == "awaiting_review", finished["error"]
    return finished


def activate(url: str, job: dict[str, Any]) -> httpx.Response:
    return httpx.post(f"{url}/api/preparations/{job['id']}/activate", timeout=120)


def room(url: str) -> dict[str, Any]:
    return httpx.get(f"{url}/api/room", timeout=5).json()


def next_state(ws, version: int) -> dict[str, Any]:
    """The first state a device is sent with this room version."""
    for _ in range(20):
        message = json.loads(ws.recv(timeout=5))
        if message.get("type") == "state" and message["state"]["room"]["room_version"] == version:
            return message["state"]
    raise AssertionError(f"No state with room version {version} arrived.")


@pytest.fixture
def service(start_service: StartService, tmp_path: Path) -> Iterator[str]:
    with start_service(tmp_path, **settings()) as url:
        yield url


def test_make_live_serves_the_reconstructed_room_and_tells_connected_devices(service: str) -> None:
    job = reconstructed(service)
    before = room(service)
    with connect(f"{service.replace('http://', 'ws://')}/api/ws?role=vr_solver") as headset:
        headset.recv(timeout=5)

        response = activate(service, job)

        assert response.status_code == 200, response.text
        state = next_state(headset, before["room_version"] + 1)
    assert state["room"]["splat_url"] is not None
    after = room(service)
    assert after["room_version"] == before["room_version"] + 1
    assert [entity["id"] for entity in after["entities"]] == ["floor", "box"]
    splat = httpx.get(f"{service}{after['splat_url']}", timeout=5)
    assert splat.status_code == 200
    assert splat.headers["cache-control"] == "no-cache"
    live = httpx.get(f"{service}/api/rooms/live", timeout=5).json()
    assert live["job_id"] == job["id"]
    assert live["room_version"] == after["room_version"]
    assert live["positioning_map"] is True
    assert live["can_restore"] is True


def test_restore_brings_the_earlier_room_back_under_a_higher_version(service: str) -> None:
    job = reconstructed(service)
    configured = room(service)
    activate(service, job)

    restored = httpx.post(f"{service}/api/rooms/restore", timeout=30)

    assert restored.status_code == 200, restored.text
    back = room(service)
    assert back["room_version"] == configured["room_version"] + 2
    assert back["entities"] == configured["entities"]
    assert back["splat_url"] == configured["splat_url"]
    assert restored.json()["job_id"] is None


def test_a_candidate_that_cannot_be_built_is_refused_and_the_live_room_stays(
    start_service: StartService, tmp_path: Path
) -> None:
    with start_service(tmp_path, **settings(FAKE_RECONSTRUCTION_BROKEN_SPLAT="1")) as url:
        job = reconstructed(url)
        before = room(url)

        response = activate(url, job)

        assert response.status_code == 422
        assert response.json()["detail"].startswith(
            "The reconstruction could not be built into a room:"
        )
        assert room(url) == before
        assert httpx.get(f"{url}/api/rooms/live", timeout=5).json()["can_restore"] is False
    assert not (tmp_path / "rooms" / job["id"]).exists()


def test_the_live_room_outlasts_a_restart(start_service: StartService, tmp_path: Path) -> None:
    with start_service(tmp_path, **settings()) as url:
        activate(url, reconstructed(url))
        live = room(url)

    with start_service(tmp_path, **settings()) as url:
        assert room(url) == live
        assert httpx.get(f"{url}{live['splat_url']}", timeout=5).status_code == 200


def test_the_room_is_not_changed_while_the_box_is_carried(service: str) -> None:
    job = reconstructed(service)
    before = room(service)
    with open_socket(service, "mobile_master") as ws:
        phone = Phone(ws)
        phone.walk_to(0, 1)
        assert phone.pick_up()["manipulation"] is not None

        response = activate(service, job)

    assert response.status_code == 409
    assert response.json()["detail"] == (
        "Someone is carrying the box. Let go of it before changing the room."
    )
    assert room(service)["room_version"] == before["room_version"]
