"""Depth priors for splat training (#209), in plain numpy so they are tested without a GPU.

A monocular depth model (Depth Anything V2) gives each frame an inverse depth only up to an
unknown scale and shift. The COLMAP points the frame sees fix both: their true depths are fitted
by `1 / depth = a * relative + b`, robustly, since some points are hidden behind nearer things
or badly matched. Training then pulls the splat's rendered depth toward the fitted one, which
gives plain painted walls a shape the colours alone don't.

Splats may also stretch into needles that look right from the filmed path and like streaks from
anywhere else. `needle_excess` measures how far a splat's longest axis outgrows its next one past
a limit; flat discs, as on a wall, are not needles.

Cameras are dicts with `K` and a 4x4 `camera_to_world` in COLMAP's convention: x right, y down,
z forward.
"""

from typing import Any

import numpy as np

# A frame's fit needs at least this many points, and keeps the best this share each round.
MIN_POINTS = 20
KEEP = 0.8
ROUNDS = 4
# Points nearer than this to the camera are not trusted.
NEAREST_M = 0.05

type Fit = tuple[float, float]


def training_size(width: int, height: int, long_side: int) -> tuple[int, int, float]:
    """The size training shrinks a frame to, and by how much: never larger than it was."""
    factor = min(1.0, long_side / max(width, height))
    return round(width * factor), round(height * factor), factor


def seen_points(camera: dict[str, Any], points: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """The pixels (x, y) and depths of the points in front of the camera and inside its frame."""
    world_to_camera = np.linalg.inv(camera["camera_to_world"])
    local = points @ world_to_camera[:3, :3].T + world_to_camera[:3, 3]
    depth = local[:, 2]
    front = depth > NEAREST_M
    projected = local[front] @ camera["K"].T
    pixels = projected[:, :2] / projected[:, 2:3]
    inside = (
        (pixels[:, 0] >= 0)
        & (pixels[:, 0] < camera["width"])
        & (pixels[:, 1] >= 0)
        & (pixels[:, 1] < camera["height"])
    )
    return pixels[inside], depth[front][inside]


def fit_inverse_depth(relative: np.ndarray, pixels: np.ndarray, depths: np.ndarray) -> Fit | None:
    """`a` and `b` with `1 / depth = a * relative + b` at the points, or None when too few points
    agree or the fit runs backwards (nearer points with smaller relative inverse depth)."""
    if len(pixels) < MIN_POINTS:
        return None
    height, width = relative.shape
    columns = np.clip(pixels[:, 0].astype(int), 0, width - 1)
    rows = np.clip(pixels[:, 1].astype(int), 0, height - 1)
    x = relative[rows, columns].astype(float)
    y = 1 / depths
    keep = np.ones(len(x), bool)
    a = b = 0.0
    for _ in range(ROUNDS):
        design = np.column_stack([x[keep], np.ones(keep.sum())])
        (a, b), *_ = np.linalg.lstsq(design, y[keep], rcond=None)
        # Keep the points that agree best, by how far their depth is off in proportion.
        error = np.abs((a * x + b) * depths - 1)
        keep = error <= np.quantile(error, KEEP)
        if keep.sum() < MIN_POINTS:
            return None
    if a <= 0:
        return None
    return float(a), float(b)


def metric_depth(relative: np.ndarray, fit: Fit) -> np.ndarray:
    """Depth in metres from a frame's relative inverse depth; 0 where the fit gives none."""
    a, b = fit
    inverse = a * relative + b
    depth = np.zeros_like(relative, dtype=float)
    valid = inverse > 1e-6
    depth[valid] = 1 / inverse[valid]
    return depth


def needle_excess(log_scales: np.ndarray, limit: float) -> np.ndarray:
    """How far each splat's longest axis is past `limit` times its middle one; 0 within it."""
    extents = np.sort(np.exp(log_scales), axis=1)
    return np.maximum(extents[:, 2] / extents[:, 1] - limit, 0.0)
