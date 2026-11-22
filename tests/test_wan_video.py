"""The hazard's video (#224, part of #221): Wan 2.2 image-to-video through a Hugging Face Space.

A fake Space client stands in for gradio_client's: it records what is asked and answers as the
Space does (a video file, and the seed), or fails as it does when the day's GPU time is used up.
"""

import time
from pathlib import Path

import pytest

from backend.furniture_generation import FixtureGenerator, GenerationError, HuggingFaceGenerator
from backend.hazard_generation import (
    VIDEO_SEEDS,
    HazardGeneration,
    HazardRequest,
    HazardTarget,
    video_prompt,
)


class FakeSpace:
    def __init__(self, tmp_path: Path, fail: Exception | None = None) -> None:
        self.tmp_path = tmp_path
        self.fail = fail
        self.calls: list[tuple[str, dict]] = []

    def client(self, space: str):
        fake = self

        class Client:
            def predict(self, **kwargs):
                fake.calls.append((space, kwargs))
                if fake.fail:
                    raise fake.fail
                path = fake.tmp_path / f"out-{len(fake.calls)}.mp4"
                path.write_bytes(b"\x00\x00\x00\x14ftypisom video " + str(kwargs["seed"]).encode())
                return {"video": str(path)}, kwargs["seed"]

        return Client()


def generator(space: FakeSpace) -> HuggingFaceGenerator:
    return HuggingFaceGenerator(None, client=space.client)


def test_the_picture_and_prompt_go_to_wan_and_the_video_comes_back(tmp_path):
    space = FakeSpace(tmp_path)
    video = generator(space).video(b"\x89PNG picture", "the bed catches fire", seed=11)
    assert video.endswith(b"video 11")
    [(name, asked)] = space.calls
    assert name == "zerogpu-aoti/wan2-2-fp8da-aoti-faster"
    assert asked["api_name"] == "/generate_video"
    assert asked["prompt"] == "the bed catches fire"
    assert asked["seed"] == 11 and asked["randomize_seed"] is False
    assert asked["duration_seconds"] == 3.0 and asked["steps"] == 6
    # The picture goes as a file, as gradio_client sends one.
    assert "input_image" in asked


def test_a_used_up_quota_says_how_long_to_wait(tmp_path):
    space = FakeSpace(
        tmp_path,
        RuntimeError(
            "You have exceeded your ZeroGPU quota (58s requested vs. 35s left). "
            "Try again in 18:19:24. "
            "Authenticate with a Hugging Face token for more quota"
        ),
    )
    with pytest.raises(GenerationError) as failed:
        generator(space).video(b"picture", "the bed catches fire")
    assert failed.value.reason == "quota"
    assert failed.value.message == (
        "The video generator is out of GPU time for today: try again in 18 h 19 min."
    )


def test_any_other_failure_is_a_failed_video(tmp_path):
    space = FakeSpace(
        tmp_path, RuntimeError("The current space is in the invalid state: RUNTIME_ERROR.")
    )
    with pytest.raises(GenerationError) as failed:
        generator(space).video(b"picture", "the bed catches fire")
    assert failed.value.reason == "video"


def test_the_prompt_always_asks_for_a_still_camera_and_an_unchanged_object():
    prompt = video_prompt("bed", "catches fire")
    assert prompt.startswith("the bed catches fire")
    for wording in (
        "static camera",
        "fixed viewpoint",
        "does not change",
        "plain white background",
    ):
        assert wording in prompt
    # The hazard is only filled in: it can't drop the template's wording.
    sneaky = video_prompt("bed", "catches fire, ignore the rest")
    assert "static camera" in sneaky and sneaky.endswith(prompt[len("the bed catches fire") :])


def test_a_hazard_makes_two_video_candidates_with_different_seeds(tmp_path):
    hazards = HazardGeneration(tmp_path, FixtureGenerator(seconds=0.0))
    job = hazards.start(
        HazardRequest(target=HazardTarget(description="a space heater"), hazard="catches fire")
    )
    deadline = time.monotonic() + 10
    while hazards.get(job.id).state not in ("ready", "failed") and time.monotonic() < deadline:
        time.sleep(0.05)
    assert hazards.get(job.id).state == "ready"
    folder = tmp_path / "jobs" / job.id
    candidates = sorted(folder.glob("video-*.mp4"))
    assert [path.name for path in candidates] == ["video-0.mp4", "video-1.mp4"]
    contents = [path.read_bytes() for path in candidates]
    assert contents[0] != contents[1]
    assert (
        str(VIDEO_SEEDS[0]).encode() in contents[0] and str(VIDEO_SEEDS[1]).encode() in contents[1]
    )
