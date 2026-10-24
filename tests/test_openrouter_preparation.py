"""Scene understanding through Qwen on OpenRouter, with OpenRouter replaced by scripted replies."""

import json
from typing import Any

import httpx
import pytest

from tests.fake_openrouter import FakeOpenRouter, fake_openrouter
from tests.test_preparation import INSTRUCTIONS, save_capture, submit, wait_until_settled

KEY = "sk-or-test-key-never-shown"


def openrouter_worker(fake: FakeOpenRouter, **extra: str) -> dict[str, str]:
    return {
        "ESCAPE_ROOM_PREPARATION_WORKER": "openrouter",
        "ESCAPE_ROOM_OPENROUTER_URL": fake.url,
        "OPENROUTER_API_KEY": KEY,
        **extra,
    }


def prepare(url: str, *names: str) -> dict[str, Any]:
    capture = save_capture(url, *names)
    response = submit(url, capture)
    assert response.status_code == 202, response.text
    return wait_until_settled(url, response.json()["id"])


def test_the_overview_becomes_an_object_inventory(start_service, tmp_path):
    with fake_openrouter() as fake:
        fake.answer("white desk\nblue mug on desk\nstack of books on desk")
        with start_service(tmp_path, **openrouter_worker(fake)) as url:
            room_before = httpx.get(f"{url}/api/room", timeout=5).json()
            job = prepare(url, "overview.png", "desk.jpg")
            room_after = httpx.get(f"{url}/api/room", timeout=5).json()

    assert room_after == room_before
    assert job["state"] == "awaiting_review", job["error"]
    assert [stage["name"] for stage in job["stages"]] == ["scene_understanding"]
    inventory = job["inventory"]
    assert [(item["id"], item["label"]) for item in inventory["objects"]] == [
        ("white_desk", "white desk"),
        ("blue_mug_on_desk", "blue mug on desk"),
        ("stack_of_books_on_desk", "stack of books on desk"),
    ]
    assert job["candidate"] is None

    # One request: the overview image first, then REST3D's object-list prompt and the instructions.
    [request] = fake.received
    assert request.headers["Authorization"] == f"Bearer {KEY}"
    assert request.body["model"] == "qwen/qwen3-vl-8b-instruct"
    [message] = request.body["messages"]
    assert message["role"] == "user"
    parts = message["content"]
    assert [part["type"] for part in parts] == ["image_url", "text", "text"]
    assert parts[0]["image_url"]["url"].startswith("data:image/png;base64,")
    assert parts[1]["text"].startswith("You are an image understanding expert.")
    assert INSTRUCTIONS in parts[2]["text"]


def test_each_request_is_recorded_with_its_cost_and_answer_but_never_the_key(
    start_service, tmp_path
):
    with fake_openrouter() as fake:
        fake.answer("white desk\nblue mug on desk", cost=0.00042)
        with start_service(tmp_path, **openrouter_worker(fake)) as url:
            job = prepare(url, "overview.png")
            [call] = job["model_calls"]
            answer = httpx.get(f"{url}/api/preparations/{job['id']}/files/{call['answer']}")
            files = [
                httpx.get(f"{url}/api/preparations/{job['id']}/files/{artifact['path']}").text
                for stage in job["stages"]
                for artifact in stage["artifacts"]
            ]

    assert call == {
        "stage": "scene_understanding",
        "purpose": "object list",
        "model": "qwen/qwen3-vl-8b-instruct",
        "provider": "FakeProvider",
        "generation_id": "gen-1",
        "prompt_tokens": 1200,
        "completion_tokens": 40,
        "cost_usd": 0.00042,
        "latency_seconds": call["latency_seconds"],
        "finish_reason": "stop",
        "accepted": True,
        "problem": None,
        "answer": "artifacts/scene_understanding/answer-1.txt",
    }
    assert call["latency_seconds"] >= 0
    assert answer.text == "white desk\nblue mug on desk"
    assert job["cost_usd"] == 0.00042
    assert job["inventory"]["answer"] == call["answer"]
    assert job["config"]["worker"] == "openrouter"
    assert job["config"]["model"] == "qwen/qwen3-vl-8b-instruct"
    assert KEY not in json.dumps(job)
    assert files and all(KEY not in text for text in files)
    stored = list((tmp_path / "jobs").rglob("*"))
    assert any(path.name == "job.json" for path in stored)
    assert all(KEY.encode() not in path.read_bytes() for path in stored if path.is_file())


def test_an_unreadable_answer_is_repaired_by_asking_again(start_service, tmp_path):
    with fake_openrouter() as fake:
        fake.answer("Here are the objects I can see in the image, listed one per line below:")
        fake.answer("I see a white desk with a blue mug and some books on it.")
        fake.answer("white desk\nblue mug", finish_reason="length")
        fake.answer("white desk\nblue mug on desk")
        settings = openrouter_worker(fake, ESCAPE_ROOM_OPENROUTER_MAX_REPAIRS="3")
        with start_service(tmp_path, **settings) as url:
            job = prepare(url, "overview.png")

    assert job["state"] == "awaiting_review", job["error"]
    assert [item["label"] for item in job["inventory"]["objects"]] == [
        "white desk",
        "blue mug on desk",
    ]
    assert [(call["accepted"], call["problem"]) for call in job["model_calls"]] == [
        (
            False,
            '"Here are the objects I can see in the image, listed one per…" is not an object name',
        ),
        (False, '"I see a white desk with a blue mug and some books on it." reads as a sentence'),
        (False, "the answer was cut off"),
        (True, None),
    ]
    assert job["inventory"]["answer"] == "artifacts/scene_understanding/answer-4.txt"
    assert job["cost_usd"] == 0.0016
    # Each repair sends the conversation so far, the refused answer, and REST3D's format reminder.
    last = fake.received[-1].body["messages"]
    assert [message["role"] for message in last] == [
        "user",
        "assistant",
        "user",
        "assistant",
        "user",
        "assistant",
        "user",
    ]
    assert last[5]["content"] == [{"type": "text", "text": "white desk\nblue mug"}]
    assert "Output ONLY a plain list, one object per line." in last[6]["content"][0]["text"]


def test_answers_that_stay_unreadable_fail_the_stage_after_the_repair_limit(
    start_service, tmp_path
):
    with fake_openrouter() as fake:
        for _ in range(3):
            fake.answer("")
        fake.answer("white desk")
        with start_service(tmp_path, **openrouter_worker(fake)) as url:
            job = prepare(url, "overview.png")

    assert job["state"] == "failed"
    assert job["error"] == {
        "stage": "scene_understanding",
        "kind": "inference",
        "message": "Qwen's answers did not follow the object list format after 3 attempts; "
        "the last one: the answer lists no objects.",
    }
    assert len(fake.received) == 3
    assert [call["accepted"] for call in job["model_calls"]] == [False, False, False]
    assert job["cost_usd"] == 0.0012
    assert job["inventory"] is None


SPEND_LIMIT = (
    "resource",
    "The OpenRouter key has reached its spending limit. "
    "Ask for the limit to be raised, then submit again.",
)
RATE_LIMIT = (
    "provider",
    "OpenRouter is limiting requests right now. Wait a minute, then submit again.",
)
OUTAGE = (
    "provider",
    "The model is unavailable right now (No endpoints available). Try again later.",
)
REFUSED_KEY = ("configuration", "OpenRouter refused the server's key. Check OPENROUTER_API_KEY.")


@pytest.mark.parametrize(
    ("status", "message", "expected"),
    [
        (402, "Insufficient credits", SPEND_LIMIT),
        (429, "Rate limit exceeded", RATE_LIMIT),
        (503, "No endpoints available", OUTAGE),
        (401, "No auth credentials found", REFUSED_KEY),
    ],
)
def test_a_provider_failure_fails_the_stage_once_and_keeps_the_room(
    start_service, tmp_path, status, message, expected
):
    with fake_openrouter() as fake:
        fake.fail(status, message)
        fake.answer("white desk")
        with start_service(tmp_path, **openrouter_worker(fake)) as url:
            room_before = httpx.get(f"{url}/api/room", timeout=5).json()
            job = prepare(url, "overview.png")
            room_after = httpx.get(f"{url}/api/room", timeout=5).json()

    assert job["state"] == "failed"
    kind, text = expected
    assert job["error"] == {"stage": "scene_understanding", "kind": kind, "message": text}
    assert len(fake.received) == 1
    assert job["model_calls"] == []
    assert job["cost_usd"] is None
    assert room_after == room_before


def test_a_server_without_a_key_or_a_reachable_openrouter_says_so(start_service, tmp_path):
    with fake_openrouter() as fake:
        settings = openrouter_worker(fake, OPENROUTER_API_KEY="")
        with start_service(tmp_path / "no-key", **settings) as url:
            no_key = prepare(url, "overview.png")
        assert fake.received == []

    # Nothing listens at the fake's address once it has stopped.
    with start_service(tmp_path / "unreachable", **openrouter_worker(fake)) as url:
        unreachable = prepare(url, "overview.png")

    assert no_key["error"] == {
        "stage": "scene_understanding",
        "kind": "configuration",
        "message": "The server has no OpenRouter key. "
        "Set OPENROUTER_API_KEY and restart the service.",
    }
    assert unreachable["error"]["kind"] == "provider"
    assert unreachable["error"]["message"].startswith("OpenRouter could not be reached (")
    assert unreachable["error"]["message"].endswith("). Try again later.")
