"""A hazard's 4D frames checked against their video, and written small as SPZ (#227).

`bed-4d-frame.ply` is a real frame L4GM made from the live bed video on the desktop (#226).
"""

import gzip
import io
import struct
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from backend.furniture_generation import GenerationError
from backend.room_views import View, render_views
from backend.splat_frames import (
    FRACTIONAL_BITS,
    SPZ_MAGIC,
    check,
    prune,
    read_frame,
    to_spz,
)
from backend.video_gate import gate, read_frames

FIXTURES = Path(__file__).parent / "fixtures" / "hazard"
SPLAT_ROOM = Path(__file__).resolve().parents[1] / "assets" / "splat-room"


def frame() -> dict[str, np.ndarray]:
    return read_frame((FIXTURES / "bed-4d-frame.ply").read_bytes())


def gated(name: str) -> list[np.ndarray]:
    video = (FIXTURES / f"{name}-fire.mp4").read_bytes()
    return read_frames(gate([video], (FIXTURES / f"{name}-picture.png").read_bytes()).video)


def decode(spz: bytes) -> dict[str, np.ndarray]:
    """SPZ version 2 read back, as Spark and Niantic's reader read it."""
    data = gzip.decompress(spz)
    magic, version, count, degree, bits, _flags, _ = struct.unpack("<IIIBBBB", data[:16])
    assert (magic, version, degree) == (SPZ_MAGIC, 2, 0)
    at = 16
    raw = np.frombuffer(data, np.uint8, count * 9, at).reshape(count, 3, 3).astype(np.int64)
    at += count * 9
    fixed = raw[..., 0] | (raw[..., 1] << 8) | (raw[..., 2] << 16)
    fixed = np.where(fixed & 0x800000, fixed - (1 << 24), fixed)
    alphas = np.frombuffer(data, np.uint8, count, at)
    at += count
    colours = np.frombuffer(data, np.uint8, count * 3, at).reshape(count, 3)
    at += count * 3
    scales = np.frombuffer(data, np.uint8, count * 3, at).reshape(count, 3)
    at += count * 3
    rotations = np.frombuffer(data, np.uint8, count * 3, at).reshape(count, 3)
    assert at + count * 3 == len(data)
    return {
        "xyz": fixed / (1 << bits),
        "alpha": alphas / 255,
        "dc": (colours / 255 - 0.5) / 0.15,
        "scales": scales / 16 - 10,
        "xyz_rotation": rotations / 127.5 - 1,
    }


def test_spz_keeps_each_splat_within_its_rounding():
    splats = prune(frame())
    back = decode(to_spz(splats))
    assert len(back["xyz"]) == len(splats["xyz"])
    assert np.abs(back["xyz"] - splats["xyz"]).max() <= 0.5 / (1 << FRACTIONAL_BITS) + 1e-9
    assert np.abs(back["alpha"] - 1 / (1 + np.exp(-splats["opacity"]))).max() <= 0.5 / 255 + 1e-9
    # SPZ keeps log sizes from -10 to almost 6: a flat splat's thinnest side, thinner still, is
    # stored at the smallest size, still far too thin to see.
    stored = np.clip(splats["scales"], -10, 255 / 16 - 10)
    assert np.abs(back["scales"] - stored).max() <= 0.5 / 16 + 1e-9


def test_a_frame_is_at_least_five_times_smaller_and_under_200_kb():
    ply = (FIXTURES / "bed-4d-frame.ply").read_bytes()
    spz = to_spz(prune(read_frame(ply)))
    assert len(ply) / len(spz) >= 5
    assert len(spz) < 200_000


def test_spark_draws_the_small_frame_as_it_draws_the_full_one(tmp_path):
    (tmp_path / "frame.ply").write_bytes((FIXTURES / "bed-4d-frame.ply").read_bytes())
    (tmp_path / "frame.spz").write_bytes(to_spz(prune(frame())))
    view = View(
        position=(0.0, 0.2, 1.8),
        look_at=(0.0, 0.0, 0.0),
        fov_degrees=45,
        width=256,
        height=256,
        background="#ffffff",
    )
    shots = []
    for name in ("frame.ply", "frame.spz"):
        [shot] = render_views(SPLAT_ROOM, [view], splat=tmp_path / name)
        shots.append(np.asarray(Image.open(io.BytesIO(shot.png)).convert("RGB")).astype(float))
    full, small = shots
    assert (full < 200).any()  # the frame is in the picture
    assert np.abs(full - small).mean() < 4


def test_frames_like_their_video_pass_and_another_objects_fail():
    frames = [frame()] * 3
    scores = check(frames, gated("bed"))
    assert float(np.median(scores)) >= 0.3
    with pytest.raises(GenerationError) as failed:
        check(frames, gated("strip"))
    assert failed.value.reason == "animate"
    assert "didn't come out like its video" in failed.value.message
