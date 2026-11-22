"""Hazard jobs (#222): the furniture generator's jobs extended with video and 4D steps.

A hazard is made for an object already in the room (its picture cut from the room, #223) or for a
new one (its picture drawn from words, as furniture is). The picture becomes a short video of the
hazard (#224), and the video a sequence of 3D splat frames (#226). Through a spawned service with
the fixture generator, which fakes each step."""

import io
import time
from typing import Any

import httpx
import pytest
from PIL import Image
from test_room_object_picture import BLOCK, entity, room_with

GENERATOR = {"ESCAPE_ROOM_FURNITURE_GENERATOR": "fixture"}


def start(url: str, target: dict[str, str], hazard: str = "catches fire") -> httpx.Response:
    return httpx.post(
        f"{url}/api/hazards/jobs", json={"target": target, "hazard": hazard}, timeout=5
    )


def job(url: str, job_id: str) -> dict[str, Any]:
    return httpx.get(f"{url}/api/hazards/jobs/{job_id}", timeout=5).json()


def wait_for(url: str, job_id: str, states: set[str], timeout: float = 10) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    current: dict[str, Any] = {}
    while time.monotonic() < deadline:
        current = job(url, job_id)
        if current["state"] in states:
            return current
        time.sleep(0.05)
    raise AssertionError(f"Job {job_id} never reached {states}; it is {current.get('state')}.")


def test_a_new_object_becomes_a_picture_then_a_video_then_4d_frames(start_service, tmp_path):
    with start_service(tmp_path, **GENERATOR) as url:
        response = start(url, {"description": "a space heater"})
        assert response.status_code == 202, response.text
        started = response.json()
        assert started["state"] in ("queued", "image_ready")

        pictured = wait_for(url, started["id"], {"image_ready", "video_ready", "ready"})
        assert (
            httpx.get(f"{url}{pictured['image_url']}", timeout=5).headers["content-type"]
            == "image/png"
        )
        filmed = wait_for(url, started["id"], {"video_ready", "ready"})
        video = httpx.get(f"{url}{filmed['video_url']}", timeout=5)
        assert video.headers["content-type"] == "video/mp4"

        done = wait_for(url, started["id"], {"ready"})
        asset = done["asset"]
        assert asset["target"] == {"description": "a space heater"}
        assert asset["hazard"] == "catches fire"
        assert asset["frames"] >= 2 and asset["frames_per_second"] > 0
        first = httpx.get(f"{url}{asset['frame_url'].format(n=0)}", timeout=5)
        assert first.status_code == 200
        assert first.content.startswith(b"ply")
        last = httpx.get(f"{url}{asset['frame_url'].format(n=asset['frames'] - 1)}", timeout=5)
        assert last.status_code == 200
        past = httpx.get(f"{url}{asset['frame_url'].format(n=asset['frames'])}", timeout=5)
        assert past.status_code == 404


def splat_room(tmp_path):
    """The splat test room with its red block as an object (#223 pictures it from the splat)."""
    block = entity("block", BLOCK["x"], BLOCK["z"], BLOCK["width"], BLOCK["depth"], BLOCK["height"])
    block["asset"] = "block.glb"
    return room_with(tmp_path, block)


def test_an_object_in_the_room_starts_from_its_own_picture_cut_from_the_splat(
    start_service, tmp_path
):
    room = splat_room(tmp_path)
    with start_service(tmp_path / "data", **GENERATOR, ESCAPE_ROOM_PREPARED_DIR=str(room)) as url:
        response = start(url, {"entity": "block"})
        assert response.status_code == 202, response.text
        done = wait_for(url, response.json()["id"], {"ready", "failed"}, timeout=60)
        assert done["state"] == "ready", done
        assert done["asset"]["target"] == {"entity": "block"}
        picture = httpx.get(f"{url}{done['image_url']}", timeout=5)
        image = Image.open(io.BytesIO(picture.content))
        assert image.size == (768, 768)


def test_an_object_the_video_barely_showed_is_refused_with_the_reason(start_service, tmp_path):
    room = splat_room(tmp_path)
    with start_service(tmp_path / "data", **GENERATOR, ESCAPE_ROOM_PREPARED_DIR=str(room)) as url:
        response = start(url, {"entity": "box"})
        failed = wait_for(url, response.json()["id"], {"ready", "failed"}, timeout=60)
        assert failed["state"] == "failed"
        assert failed["error"].startswith("Too little of the room's video shows the box")


def test_an_object_not_in_the_room_is_refused(start_service, tmp_path):
    with start_service(tmp_path, **GENERATOR) as url:
        response = start(url, {"entity": "no_such_thing"})
        assert response.status_code == 422
        assert "no_such_thing" in response.json()["detail"]


@pytest.mark.parametrize(
    ("fail", "kept", "message"),
    [
        ("video", "image_url", "The generator couldn't make a video of that. Try again."),
        ("animate", "video_url", "The video couldn't be turned into a 3D animation. Try again."),
    ],
)
def test_a_failed_step_says_why_and_keeps_what_was_made(
    start_service, tmp_path, fail, kept, message
):
    settings = GENERATOR | {"ESCAPE_ROOM_FIXTURE_GENERATOR_FAIL": fail}
    with start_service(tmp_path, **settings) as url:
        started = start(url, {"description": "a space heater"}).json()
        failed = wait_for(url, started["id"], {"failed", "ready"})
        assert failed["state"] == "failed"
        assert failed["error"] == message
        assert failed["asset"] is None
        assert httpx.get(f"{url}{failed[kept]}", timeout=5).status_code == 200


def test_a_hazard_can_be_cancelled_at_any_step_and_makes_nothing(start_service, tmp_path):
    slow = GENERATOR | {"ESCAPE_ROOM_FIXTURE_GENERATOR_SECONDS": "0.6"}
    with start_service(tmp_path, **slow) as url:
        started = start(url, {"description": "a space heater"}).json()
        wait_for(url, started["id"], {"video_ready"})
        cancelled = httpx.post(f"{url}/api/hazards/jobs/{started['id']}/cancel", timeout=5).json()
        assert cancelled["state"] == "cancelled"
        time.sleep(1.5)
        after = job(url, started["id"])
        assert after["state"] == "cancelled"
        assert after["asset"] is None


def test_a_server_without_a_generator_says_so(service_url):
    response = start(service_url, {"description": "a space heater"})
    assert response.status_code == 503
    assert "isn't set up" in response.json()["detail"]
