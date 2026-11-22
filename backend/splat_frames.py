"""A hazard's 4D frames, checked and made light for phones (#227, part of #221).

L4GM (#226) writes each frame as a PLY of about 17,000 splats, some 1.4 MB: about 55 MB for a
hazard, too much for a phone. Each frame is pruned (faint and vanishing splats dropped) and
written as SPZ, the compact Gaussian splat format Spark reads natively (Niantic's, version 2:
fixed-point positions, bytes for the rest, gzipped).

Before that, the frames are checked against the video they came from: the 4D result seen from
the front should look like the video's frames, both cut to the object so their scales don't
matter. A broken reconstruction (another object, a scrambled one) fails the hazard.
"""

import gzip
import struct

import cv2
import numpy as np

from backend.furniture_generation import GenerationError

SPZ_MAGIC = 0x5053474E
SPZ_VERSION = 2
FRACTIONAL_BITS = 12
COLOUR_SCALE = 0.15
# Pruning: splats fainter than this, or smaller than this (log scale, all axes), are dropped. On
# the live bed, 10% opacity kept 13,000 of 25,000 splats with the check's scores unchanged.
MIN_OPACITY = 0.1
MIN_LOG_SCALE = -9.0
# The check: frames compared, and the median likeness they must reach. The live bed's 4D frames
# scored 0.71 to 0.79 against its video; wrong pairings (another object's video) 0.10 at most.
CHECKED_FRAMES = 3
MIN_LIKENESS = 0.3
CHECK_SIDE = 64


def read_frame(data: bytes) -> dict[str, np.ndarray]:
    """A 3DGS PLY's splats: positions, colour (SH DC), logit opacity, log scales, wxyz rotations."""
    end = data.index(b"end_header\n") + len(b"end_header\n")
    header = data[:end].decode("ascii").splitlines()
    names = [line.split()[-1] for line in header if line.startswith("property float ")]
    count = next(int(line.split()[-1]) for line in header if line.startswith("element vertex"))
    table = np.frombuffer(data[end:], dtype="<f4", count=count * len(names)).reshape(
        count, len(names)
    )

    def columns(*wanted: str) -> np.ndarray:
        return table[:, [names.index(name) for name in wanted]].astype(np.float64)

    return {
        "xyz": columns("x", "y", "z"),
        "dc": columns("f_dc_0", "f_dc_1", "f_dc_2"),
        "opacity": columns("opacity")[:, 0],
        "scales": columns("scale_0", "scale_1", "scale_2"),
        "rotation": columns("rot_0", "rot_1", "rot_2", "rot_3"),
    }


def prune(splats: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
    """Without the splats that can't be seen: too faint, or vanishingly small."""
    alpha = 1 / (1 + np.exp(-splats["opacity"]))
    keep = (alpha >= MIN_OPACITY) & (splats["scales"].max(axis=1) >= MIN_LOG_SCALE)
    return {key: value[keep] for key, value in splats.items()}


def _bytes(values: np.ndarray) -> np.ndarray:
    return np.clip(np.round(values), 0, 255).astype(np.uint8)


def to_spz(splats: dict[str, np.ndarray]) -> bytes:
    """The splats as SPZ version 2, with no spherical harmonics beyond colour."""
    count = len(splats["xyz"])
    header = struct.pack("<IIIBBBB", SPZ_MAGIC, SPZ_VERSION, count, 0, FRACTIONAL_BITS, 0, 0)
    fixed = np.round(splats["xyz"] * (1 << FRACTIONAL_BITS)).astype(np.int64)
    fixed = np.clip(fixed, -(1 << 23), (1 << 23) - 1) & 0xFFFFFF
    positions = np.stack([fixed & 0xFF, (fixed >> 8) & 0xFF, (fixed >> 16) & 0xFF], axis=-1)
    alphas = _bytes(255 / (1 + np.exp(-splats["opacity"])))
    colours = _bytes(splats["dc"] * (COLOUR_SCALE * 255) + 0.5 * 255)
    # Log sizes from -10 to almost 6; a flat splat's thinnest side may be thinner, and is stored at
    # the smallest size, still far too thin to see.
    scales = _bytes((splats["scales"] + 10) * 16)
    quaternion = splats["rotation"] / np.linalg.norm(splats["rotation"], axis=1, keepdims=True)
    quaternion = np.where(quaternion[:, :1] < 0, -quaternion, quaternion)  # w >= 0
    rotations = _bytes(quaternion[:, 1:] * 127.5 + 127.5)
    body = b"".join(
        [
            header,
            positions.astype(np.uint8).reshape(count, 9).tobytes(),
            alphas.tobytes(),
            colours.tobytes(),
            scales.tobytes(),
            rotations.tobytes(),
        ]
    )
    return gzip.compress(body, compresslevel=9)


def front_view(splats: dict[str, np.ndarray], side: int = CHECK_SIDE) -> np.ndarray:
    """The splats seen from the front (+z, looking down -z), cut to them, on white: a quick
    orthographic drawing, near splats over far ones, good enough to compare with the video."""
    xyz = splats["xyz"]
    alpha = 1 / (1 + np.exp(-splats["opacity"]))
    colour = np.clip(0.5 + 0.28209479177387814 * splats["dc"], 0, 1)
    seen = alpha > 0.1
    xyz, alpha, colour = xyz[seen], alpha[seen], colour[seen]
    if len(xyz) == 0:
        return np.full((side, side, 3), 255, np.uint8)
    low, high = xyz[:, :2].min(axis=0), xyz[:, :2].max(axis=0)
    span = float(max(high - low)) or 1.0
    u = ((xyz[:, 0] - low[0]) / span * (side - 1)).astype(int)
    v = ((high[1] - xyz[:, 1]) / span * (side - 1)).astype(int)
    # Front to back per pixel, all pixels at once: sort by pixel, then nearest (largest z) first;
    # each splat adds its colour times the light still getting through to it.
    pixel = v * side + u
    order = np.lexsort((-xyz[:, 2], pixel))
    pixel, alpha, colour = pixel[order], alpha[order], colour[order]
    through = np.log(np.clip(1 - alpha, 1e-6, 1))
    cumulative = np.cumsum(through)
    starts = np.r_[0, np.nonzero(np.diff(pixel))[0] + 1]
    first_of = np.repeat(starts, np.diff(np.r_[starts, len(pixel)]))
    before = cumulative - through - np.where(first_of > 0, cumulative[first_of - 1], 0.0)
    weight = np.exp(before) * alpha
    gathered = np.zeros((side * side, 3))
    np.add.at(gathered, pixel, weight[:, None] * colour)
    remaining = np.ones(side * side)
    np.multiply.at(remaining, pixel, 1 - alpha)
    image = (gathered + remaining[:, None]).reshape(side, side, 3)  # white shows through the rest
    return (cv2.GaussianBlur(image, (3, 3), 0) * 255).clip(0, 255).astype(np.uint8)


def _cut(frame: np.ndarray, side: int = CHECK_SIDE) -> np.ndarray:
    """The frame cut to what isn't white, squared and shrunk."""
    standing = (frame.astype(int) < 235).any(axis=2)
    ys, xs = np.nonzero(standing)
    if len(ys) == 0:
        return cv2.resize(frame, (side, side))
    top, bottom, left, right = ys.min(), ys.max(), xs.min(), xs.max()
    size = max(bottom - top, right - left) + 1
    canvas = np.full((size, size, 3), 255, np.uint8)
    canvas[: bottom - top + 1, : right - left + 1] = frame[top : bottom + 1, left : right + 1]
    return cv2.resize(canvas, (side, side), interpolation=cv2.INTER_AREA)


def _likeness(a: np.ndarray, b: np.ndarray) -> float:
    ga = cv2.cvtColor(a, cv2.COLOR_RGB2GRAY).astype(float).ravel()
    gb = cv2.cvtColor(b, cv2.COLOR_RGB2GRAY).astype(float).ravel()
    ga, gb = ga - ga.mean(), gb - gb.mean()
    return float(ga @ gb / (np.linalg.norm(ga) * np.linalg.norm(gb) + 1e-9))


def check(frames: list[dict[str, np.ndarray]], video: list[np.ndarray]) -> list[float]:
    """How like the video's frames the 4D frames look from the front, at the start, middle and end
    (the better of seen as is and mirrored). GenerationError `animate` if their median is too
    unlike."""
    picks = [int(pick) for pick in np.linspace(0, len(frames) - 1, CHECKED_FRAMES).round()]
    scores: list[float] = []
    for pick in picks:
        moment = min(len(video) - 1, round(pick * (len(video) - 1) / max(len(frames) - 1, 1)))
        target = _cut(video[moment])
        drawn = _cut(front_view(frames[pick]))
        scores.append(round(max(_likeness(drawn, target), _likeness(drawn[:, ::-1], target)), 4))
    if float(np.median(scores)) < MIN_LIKENESS:
        raise GenerationError(
            "animate", "The 3D animation didn't come out like its video. Try again."
        )
    return scores
