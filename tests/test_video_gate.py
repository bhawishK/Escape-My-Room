"""The hazard video's quality gate (#225, part of #221), on real Wan 2.2 videos.

`bed-fire.mp4` is spike #220's: Wan tidies the bed into a straighter view in its first frames,
then the camera stays still while it burns. `strip-fire.mp4` is the power strip's, steady
throughout. A camera that pans is made here by sliding the steady one's frames along.
"""

from pathlib import Path

import cv2
import numpy as np
import pytest

from backend.furniture_generation import GenerationError
from backend.video_gate import (
    OUTPUT_SIDE,
    footing_drift,
    gate,
    read_frames,
    trim_point,
    write_video,
)

FIXTURES = Path(__file__).parent / "fixtures" / "hazard"


def video(name: str) -> bytes:
    return (FIXTURES / f"{name}.mp4").read_bytes()


def picture(name: str) -> bytes:
    return (FIXTURES / f"{name}-picture.png").read_bytes()


def panned(data: bytes, step: int = 3) -> bytes:
    """The video with its camera panning `step` pixels a frame to the side."""
    frames = read_frames(data)
    slid = []
    for number, frame in enumerate(frames):
        shift = np.float32([[1, 0, -step * number], [0, 1, 0]])
        slid.append(
            cv2.warpAffine(
                frame, shift, (frame.shape[1], frame.shape[0]), borderValue=(235, 235, 235)
            )
        )
    return write_video(slid, 16)


def test_frames_wan_spends_straightening_the_view_are_trimmed():
    assert trim_point(read_frames(video("bed-fire"))) == 8
    assert trim_point(read_frames(video("strip-fire"))) == 0


def test_a_still_camera_keeps_its_footing_and_a_panning_one_does_not():
    assert footing_drift(read_frames(video("strip-fire")), 0) < 0.02
    assert footing_drift(read_frames(video("bed-fire")), 8) < 0.12
    assert footing_drift(read_frames(panned(video("strip-fire"))), 0) > 0.12


def test_the_better_candidate_comes_out_trimmed_on_white_and_square():
    result = gate([panned(video("strip-fire")), video("strip-fire")], picture("strip"))
    assert result.chosen == 1
    assert [candidate["passed"] for candidate in result.candidates] == [False, True]
    frames = read_frames(result.video)
    assert len(frames) == 49
    assert frames[0].shape == (OUTPUT_SIDE, OUTPUT_SIDE, 3)
    first = frames[0].astype(int)
    border = np.concatenate(
        [
            first[:4].reshape(-1, 3),
            first[-4:].reshape(-1, 3),
            first[:, :4].reshape(-1, 3),
            first[:, -4:].reshape(-1, 3),
        ]
    )
    # The background is pure white, allowing for the video codec.
    assert border.min() >= 240
    # The object is whole: nothing of it touches the edge.
    middle = (first < 200).any(axis=2)
    assert middle.any()
    assert (
        not middle[0].any()
        and not middle[-1].any()
        and not middle[:, 0].any()
        and not middle[:, -1].any()
    )


def test_the_trim_is_kept_in_the_chosen_video():
    result = gate([video("bed-fire")], picture("bed"))
    assert result.candidates[0]["trimmed"] == 8
    assert len(read_frames(result.video)) == 49 - 8


def test_when_every_candidate_moves_the_camera_the_hazard_fails_with_why():
    with pytest.raises(GenerationError) as failed:
        gate([panned(video("strip-fire")), panned(video("strip-fire"), step=4)], picture("strip"))
    assert failed.value.reason == "video_gate"
    assert "camera" in failed.value.message
