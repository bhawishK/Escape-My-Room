"""The filming coach's server check (#100): every few seconds the phone sends a small frame, and
Qwen says whether it is a close-up of a plain surface, whether the floor is in view and what is in
shot. Each recording has a spending limit, and any failure is quiet: the phone keeps filming.
Against a spawned service and the fake OpenRouter."""

import base64
import io
import json
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
from conftest import StartService
from PIL import Image

from tests.fake_openrouter import FakeOpenRouter, fake_openrouter


def frame() -> str:
    """A small JPEG frame, as the phone sends it."""
    data = io.BytesIO()
    Image.new("RGB", (180, 320), (200, 190, 170)).save(data, format="JPEG", quality=70)
    return base64.b64encode(data.getvalue()).decode()


def answer(plain: bool, floor: bool, in_shot: str = "a white door") -> str:
    return json.dumps({"plain_close_up": plain, "floor_visible": floor, "in_shot": in_shot})


@pytest.fixture
def fake() -> Iterator[FakeOpenRouter]:
    with fake_openrouter() as server:
        yield server


@pytest.fixture
def service(start_service: StartService, tmp_path: Path, fake: FakeOpenRouter) -> Iterator[str]:
    with start_service(
        tmp_path,
        ESCAPE_ROOM_OPENROUTER_URL=fake.url,
        OPENROUTER_API_KEY="test-key",
        ESCAPE_ROOM_COACH_BUDGET_USD="0.001",
    ) as url:
        yield url


def check(url: str, recording: str = "rec-1") -> dict:
    response = httpx.post(
        f"{url}/api/coach/check", json={"recording": recording, "image": frame()}, timeout=10
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_a_close_up_of_a_plain_surface_is_told_to_step_back(service: str, fake: FakeOpenRouter):
    fake.answer(answer(plain=True, floor=True))
    result = check(service)
    assert result["prompt"] == "Step back to show more of the room"
    assert result["in_shot"] == "a white door"
    assert result["status"] == "ok"
    # The frame went to Qwen as a picture.
    [request] = fake.received
    parts = request.body["messages"][-1]["content"]
    assert any(part.get("type") == "image_url" for part in parts)


def test_the_floor_is_asked_for_once_it_has_been_out_of_view_twice(
    service: str, fake: FakeOpenRouter
):
    fake.answer(answer(plain=False, floor=False, in_shot="a wardrobe"))
    fake.answer(answer(plain=False, floor=False, in_shot="a wardrobe"))
    assert check(service)["prompt"] is None
    assert check(service)["prompt"] == "Show the floor: tilt the phone down as you go"


def test_each_recording_stops_asking_at_its_spending_limit(service: str, fake: FakeOpenRouter):
    for _ in range(4):
        fake.answer(answer(plain=False, floor=True), cost=0.0004)
    statuses = [check(service)["status"] for _ in range(4)]
    # 0.0004 a check against 0.001: the third takes it to 0.0012, so the fourth isn't asked.
    assert statuses == ["ok", "ok", "ok", "over_budget"]
    assert len(fake.received) == 3
    # Another recording has its own limit.
    assert check(service, "rec-2")["status"] == "ok"


def test_when_openrouter_fails_filming_carries_on_without_a_prompt(
    service: str, fake: FakeOpenRouter
):
    fake.fail(503, "No provider available")
    result = check(service)
    assert result == {"status": "unavailable", "prompt": None, "in_shot": None}


def test_an_answer_qwen_cannot_put_right_is_quiet_too(service: str, fake: FakeOpenRouter):
    for _ in range(3):
        fake.answer("The camera sees a door.")
    assert check(service)["status"] == "unavailable"


def test_a_request_that_is_not_a_small_image_is_refused(service: str):
    response = httpx.post(
        f"{service}/api/coach/check",
        json={"recording": "rec-1", "image": base64.b64encode(b"not an image").decode()},
        timeout=10,
    )
    assert response.status_code == 422
