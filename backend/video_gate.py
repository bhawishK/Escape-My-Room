"""The hazard video's quality gate (#225, part of #221): which candidate the 4D step gets, and how.

The 4D step (L4GM, #226) needs a still camera, the object unchanged, and the object alone on pure
white, square, at 16 fps. Wan 2.2 (#224) mostly obliges, but in its first frames it often tidies
the object into a straighter view, and now and then the camera moves. Spike #220 trimmed and
whitened by hand; this does it from measures set on real Wan videos:

- Trim: while the picture shifts more than a pixel a frame (at 64 px) at the start, Wan is still
  straightening the view; cut until three calm frames, and six more for its tail. The spike's bed
  video comes out trimmed by 8, as was done by hand; a steady video by none.
- Still camera: on a plain background, the object's footing (its bottom edge, and the middle of its
  lowest part) stays put while flames and smoke move above it. If it moves more than 12% of the
  frame after the trim, the camera moved: a 3 px a frame pan reaches 21%, the burning beds 9%.
- Choice: of the candidates that pass, the one whose first kept frame looks most like the input
  picture.
- On white: the background is fitted as a smooth surface and anything standing out from it is the
  object (flames and smoke included); the rest becomes pure white, the object centred in a square.
"""

import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from backend.furniture_generation import GenerationError

FRAMES_PER_SECOND = 16
OUTPUT_SIDE = 512
# Trimming: a frame-to-frame shift above this (pixels at 64 px) is Wan still moving the view.
SETTLED_SHIFT = 1.0
SETTLED_FRAMES = 3
TRIM_TAIL = 6
SHIFT_SIDE = 64
SHIFT_SEARCH = 6
# Still camera: the footing may move this share of the frame, at most.
MAX_FOOTING_DRIFT = 0.12
# The object in a frame: this far from the background colour, summed over R, G and B.
OBJECT_DIFFERENCE = 60
# The square round the object, this much larger than it.
FRAMING = 1.25


@dataclass
class GateResult:
    video: bytes
    chosen: int
    candidates: list[dict[str, Any]] = field(default_factory=lambda: [])


def read_frames(data: bytes) -> list[np.ndarray]:
    """An MP4's frames, as RGB arrays."""
    with tempfile.TemporaryDirectory(prefix="gate-") as folder:
        path = Path(folder) / "in.mp4"
        path.write_bytes(data)
        capture = cv2.VideoCapture(str(path))
        frames: list[np.ndarray] = []
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            frames.append(np.ascontiguousarray(frame[..., ::-1]))
        capture.release()
    return frames


def write_video(frames: list[np.ndarray], frames_per_second: int = FRAMES_PER_SECOND) -> bytes:
    """RGB frames as an MP4 (MPEG-4 Part 2, which L4GM's reader opens)."""
    height, width = frames[0].shape[:2]
    with tempfile.TemporaryDirectory(prefix="gate-") as folder:
        path = Path(folder) / "out.mp4"
        writer = cv2.VideoWriter(
            str(path), cv2.VideoWriter.fourcc(*"mp4v"), frames_per_second, (width, height)
        )
        for frame in frames:
            writer.write(np.ascontiguousarray(frame[..., ::-1]))
        writer.release()
        return path.read_bytes()


def _small(frame: np.ndarray) -> np.ndarray:
    grey = cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)
    small = cv2.resize(grey, (SHIFT_SIDE, SHIFT_SIDE), interpolation=cv2.INTER_AREA)
    return cv2.GaussianBlur(small, (3, 3), 0).astype(float)


def _shift(a: np.ndarray, b: np.ndarray) -> float:
    """How far the lower part of the picture moved from a to b, in pixels at 64: the best match."""
    first, second = _small(a)[24:], _small(b)[24:]
    height, width = first.shape
    s = SHIFT_SEARCH
    core = first[s : height - s, s : width - s]
    best, moved = float("inf"), 0.0
    for dy in range(-s, s + 1):
        for dx in range(-s, s + 1):
            error = float(
                np.abs(core - second[s + dy : height - s + dy, s + dx : width - s + dx]).mean()
            )
            distance = float(np.hypot(dx, dy))
            # A near tie keeps the smaller move, so a featureless picture doesn't seem to jump.
            if error < best * 0.999 or (error <= best * 1.001 and distance < moved):
                best, moved = min(best, error), distance
    return moved


def trim_point(frames: list[np.ndarray]) -> int:
    """How many leading frames to cut: none if the view is calm from the start."""
    shifts = [_shift(frames[t], frames[t + 1]) for t in range(min(len(frames) - 1, 24))]
    for start in range(len(shifts) - SETTLED_FRAMES + 1):
        if all(shift <= SETTLED_SHIFT for shift in shifts[start : start + SETTLED_FRAMES]):
            return 0 if start == 0 else min(start + TRIM_TAIL, len(frames) // 2)
    return len(frames) // 2


def _background(frame: np.ndarray) -> np.ndarray:
    """The colour round the frame's edges."""
    edges = np.concatenate(
        [
            frame[:8].reshape(-1, 3),
            frame[-8:].reshape(-1, 3),
            frame[:, :8].reshape(-1, 3),
            frame[:, -8:].reshape(-1, 3),
        ]
    )
    return np.median(edges, axis=0)


def _object(frame: np.ndarray) -> np.ndarray | None:
    """The object's main body: the largest region standing out from the background, without
    specks."""
    rgb = frame.astype(int)
    standing = (np.abs(rgb - _background(frame)).sum(axis=2) > OBJECT_DIFFERENCE).astype(np.uint8)
    standing = cv2.morphologyEx(standing, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
    count, labels, stats, _ = cv2.connectedComponentsWithStats(standing)
    if count < 2:
        return None
    return labels == 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))


def _footing(frame: np.ndarray) -> tuple[float, float] | None:
    """The object's bottom edge and the middle of its lowest 15%, as shares of the frame."""
    body = _object(frame)
    if body is None:
        return None
    rows = np.nonzero(body.any(axis=1))[0]
    top, bottom = int(rows.min()), int(rows.max())
    lowest = body[int(bottom - 0.15 * (bottom - top)) : bottom + 1]
    columns = np.nonzero(lowest.any(axis=0))[0]
    height, width = body.shape
    return bottom / height, (columns.min() + columns.max()) / 2 / width


def footing_drift(frames: list[np.ndarray], start: int) -> float:
    """How far the object's footing moves from frame `start` on, as a share of the frame."""
    first = _footing(frames[start])
    if first is None:
        return 1.0
    drift = 0.0
    for frame in frames[start::4]:
        footing = _footing(frame)
        if footing is None:
            return 1.0
        drift = max(drift, abs(footing[0] - first[0]), abs(footing[1] - first[1]))
    return drift


def likeness(frame: np.ndarray, picture: np.ndarray) -> float:
    """How alike two pictures are in grey at 64 px: 1 the same, 0 unrelated."""
    a = _small(frame).ravel()
    b = _small(cv2.resize(picture, (frame.shape[1], frame.shape[0]))).ravel()
    a, b = a - a.mean(), b - b.mean()
    return float(a @ b / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-9))


def _whitened(frame: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """The frame with its background pure white, and how much of each pixel is the object."""
    height, width = frame.shape[:2]
    yy, xx = np.mgrid[0:height, 0:width] / max(height, width)
    terms = np.stack([np.ones_like(xx), xx, yy, xx * xx, xx * yy, yy * yy, xx**3, yy**3], axis=-1)
    image = frame.astype(float)
    top, low = image.max(axis=2), image.min(axis=2)
    saturation = (top - low) / np.maximum(top, 1)
    use = (saturation < 0.06) & (top > 170)
    surface = np.zeros_like(image)
    for _ in range(3):
        for c in range(3):
            coef = np.linalg.lstsq(terms[use], image[..., c][use], rcond=None)[0]
            surface[..., c] = terms @ coef
        residual = np.linalg.norm(image - surface, axis=2)
        if use.sum() > 100:
            use &= residual < np.percentile(residual[use], 80)
    distance = np.linalg.norm(image - surface, axis=2)
    alpha = np.maximum(
        np.clip((distance - 16) / 14, 0, 1), np.clip((saturation - 0.10) / 0.1, 0, 1)
    )
    mask = (alpha * 255).astype(np.uint8)
    mask = cv2.erode(cv2.dilate(cv2.erode(mask, np.ones((3, 3))), np.ones((5, 5))), np.ones((3, 3)))
    alpha = cv2.GaussianBlur(mask, (0, 0), 1.2).astype(float) / 255
    white = image * alpha[..., None] + 255 * (1 - alpha[..., None])
    return white, alpha


def on_white(frames: list[np.ndarray]) -> list[np.ndarray]:
    """The frames as the 4D step wants them: the object alone on white, centred in a square."""
    whitened = [_whitened(frame) for frame in frames]
    union = np.max(np.stack([alpha for _, alpha in whitened]), axis=0) > 0.3
    ys, xs = np.nonzero(union)
    if len(ys) == 0:
        raise GenerationError(
            "video_gate", "The generated video shows nothing to turn into 3D. Try again."
        )
    cx, cy = (xs.min() + xs.max()) / 2, (ys.min() + ys.max()) / 2
    side = int(max(xs.max() - xs.min(), ys.max() - ys.min()) * FRAMING) + 2
    left, top = int(cx - side / 2), int(cy - side / 2)
    height, width = frames[0].shape[:2]
    out: list[np.ndarray] = []
    for white, _ in whitened:
        canvas = np.full((side, side, 3), 255.0)
        x0, y0, x1, y1 = max(0, left), max(0, top), min(width, left + side), min(height, top + side)
        canvas[y0 - top : y1 - top, x0 - left : x1 - left] = white[y0:y1, x0:x1]
        out.append(
            cv2.resize(
                canvas.astype(np.uint8), (OUTPUT_SIDE, OUTPUT_SIDE), interpolation=cv2.INTER_AREA
            )
        )
    return out


def gate(candidates: list[bytes], picture: bytes) -> GateResult:
    """The best candidate, trimmed and on white, with each candidate's measures; GenerationError
    `video_gate` with the reason when none will do."""
    source = cv2.imdecode(np.frombuffer(picture, np.uint8), cv2.IMREAD_COLOR)
    if source is None:
        raise GenerationError("video_gate", "The hazard's picture couldn't be read.")
    source = source[..., ::-1]
    measured: list[dict[str, Any]] = []
    clips: list[list[np.ndarray]] = []
    for data in candidates:
        frames = read_frames(data)
        clips.append(frames)
        if len(frames) < 8:
            measured.append({"passed": False, "reason": "too short", "frames": len(frames)})
            continue
        start = trim_point(frames)
        drift = footing_drift(frames, start)
        measured.append(
            {
                "frames": len(frames),
                "trimmed": start,
                "drift": round(float(drift), 4),
                "likeness": round(float(likeness(frames[start], source)), 4),
                "passed": bool(drift <= MAX_FOOTING_DRIFT),
                "reason": None if drift <= MAX_FOOTING_DRIFT else "the camera moved",
            }
        )
    passing = [number for number, found in enumerate(measured) if found["passed"]]
    if not passing:
        raise GenerationError(
            "video_gate",
            "The generated videos moved the camera too much to turn into 3D. Try again.",
        )
    chosen = max(passing, key=lambda number: measured[number]["likeness"])
    kept = clips[chosen][measured[chosen]["trimmed"] :]
    return GateResult(video=write_video(on_white(kept)), chosen=chosen, candidates=measured)
