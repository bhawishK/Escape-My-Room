"""Splat training on the GPU, within a memory budget, and the splat file it writes."""

from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any

import numpy as np

from backend.reconstruction.pipeline import Settings

# A retry after running out of GPU memory trains on smaller frames with fewer splats.
SMALLER = 0.75


class OutOfGpuMemory(Exception):
    """Training needed more GPU memory than its budget."""


def train_within_budget[T](
    train: Callable[[Settings], T], settings: Settings
) -> tuple[T, dict[str, Any]]:
    """Train, and if the GPU runs out of memory, once more at three quarters of the frame size and
    splat count. The report lists each attempt."""
    attempts: list[dict[str, Any]] = []
    for attempt in (settings, smaller(settings)):
        tried = {"long_side": attempt.long_side, "max_splats": attempt.max_splats}
        try:
            result = train(attempt)
        except OutOfGpuMemory:
            attempts.append(tried | {"outcome": "out of GPU memory"})
            continue
        attempts.append(tried | {"outcome": "trained"})
        return result, {"retried": len(attempts) > 1, "attempts": attempts}
    sizes = "; ".join(f"{a['long_side']} px, {a['max_splats']} splats" for a in attempts)
    raise OutOfGpuMemory(f"Splat training ran out of GPU memory at {sizes}.")


def smaller(settings: Settings) -> Settings:
    return replace(
        settings,
        long_side=round(settings.long_side * SMALLER),
        max_splats=round(settings.max_splats * SMALLER),
    )


def write_ply(
    path: Path,
    means: np.ndarray,
    scales: np.ndarray,
    quats: np.ndarray,
    opacities: np.ndarray,
    sh0: np.ndarray,
    shN: np.ndarray,
) -> None:
    """The standard 3DGS PLY: log scales, wxyz quaternions, logit opacity, SH channel-major."""
    count = len(means)
    rest = np.asarray(shN).transpose(0, 2, 1).reshape(count, -1)  # all R, then G, then B
    columns = [
        means,
        np.zeros((count, 3)),
        np.asarray(sh0).reshape(count, 3),
        rest,
        np.asarray(opacities).reshape(count, 1),
        scales,
        quats,
    ]
    names = ["x", "y", "z", "nx", "ny", "nz", "f_dc_0", "f_dc_1", "f_dc_2"]
    names += [f"f_rest_{i}" for i in range(rest.shape[1])]
    names += ["opacity", "scale_0", "scale_1", "scale_2", "rot_0", "rot_1", "rot_2", "rot_3"]
    data = np.concatenate([np.asarray(column, dtype="<f4") for column in columns], axis=1)
    header = ["ply", "format binary_little_endian 1.0", f"element vertex {count}"]
    header += [f"property float {name}" for name in names] + ["end_header", ""]
    path.write_bytes("\n".join(header).encode() + data.tobytes())


def read_ply(path: Path) -> dict[str, np.ndarray]:
    """A splat written by `write_ply`, as the arrays it was written from."""
    data = path.read_bytes()
    end = data.index(b"end_header\n") + len(b"end_header\n")
    names = [
        line.split()[-1]
        for line in data[:end].decode("ascii").splitlines()
        if line.startswith("property float ")
    ]
    table = np.frombuffer(data[end:], dtype="<f4").reshape(-1, len(names))

    def columns(*wanted: str) -> np.ndarray:
        return table[:, [names.index(name) for name in wanted]]

    rest = [name for name in names if name.startswith("f_rest_")]
    count = len(table)
    return {
        "means": columns("x", "y", "z"),
        "scales": columns("scale_0", "scale_1", "scale_2"),
        "quats": columns("rot_0", "rot_1", "rot_2", "rot_3"),
        "opacities": columns("opacity")[:, 0],
        "sh0": columns("f_dc_0", "f_dc_1", "f_dc_2").reshape(count, 1, 3),
        "shN": columns(*rest).reshape(count, 3, len(rest) // 3).transpose(0, 2, 1),
    }
