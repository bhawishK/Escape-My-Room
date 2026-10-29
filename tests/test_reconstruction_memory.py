"""Splat training within a GPU memory budget (#135): running out retries once, smaller."""

import pytest

from backend.reconstruction.pipeline import Settings
from backend.reconstruction.splat import OutOfGpuMemory, train_within_budget


def test_running_out_retries_once_with_smaller_frames_and_fewer_splats() -> None:
    tried: list[Settings] = []

    def train(settings: Settings) -> str:
        tried.append(settings)
        if len(tried) == 1:
            raise OutOfGpuMemory("CUDA out of memory")
        return "splat"

    result, report = train_within_budget(train, Settings(long_side=1600, max_splats=400_000))

    assert result == "splat"
    assert [(s.long_side, s.max_splats) for s in tried] == [(1600, 400_000), (1200, 300_000)]
    assert report == {
        "retried": True,
        "attempts": [
            {"long_side": 1600, "max_splats": 400_000, "outcome": "out of GPU memory"},
            {"long_side": 1200, "max_splats": 300_000, "outcome": "trained"},
        ],
    }


def test_running_out_twice_fails_with_both_attempts_named() -> None:
    def train(settings: Settings) -> str:
        raise OutOfGpuMemory("CUDA out of memory")

    with pytest.raises(OutOfGpuMemory, match="1600 px, 400000 splats.*1200 px, 300000 splats"):
        train_within_budget(train, Settings(long_side=1600, max_splats=400_000))
