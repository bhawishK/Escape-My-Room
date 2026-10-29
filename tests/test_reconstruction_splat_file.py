"""The trained splat's file (#135): the standard 3DGS PLY, read back for the positioning map's
depth renders and readable by the rest of the app."""

from pathlib import Path

import numpy as np

from backend.reconstruction.splat import read_ply, write_ply
from backend.splat_file import read_splat


def splats(rng: np.random.Generator, count: int = 5) -> dict[str, np.ndarray]:
    quats = rng.normal(size=(count, 4))
    return {
        "means": rng.normal(size=(count, 3)),
        "scales": rng.normal(size=(count, 3)),
        "quats": quats / np.linalg.norm(quats, axis=1, keepdims=True),
        "opacities": rng.normal(size=count),
        "sh0": rng.normal(size=(count, 1, 3)),
        "shN": rng.normal(size=(count, 3, 3)),  # degree 1
    }


def test_a_written_splat_reads_back_the_same(tmp_path: Path) -> None:
    written = splats(np.random.default_rng(0))
    write_ply(tmp_path / "room.ply", **written)

    read = read_ply(tmp_path / "room.ply")

    for name, values in written.items():
        assert np.allclose(read[name], values, atol=1e-6), name


def test_the_app_reads_the_written_splat(tmp_path: Path) -> None:
    written = splats(np.random.default_rng(1), count=3)
    write_ply(tmp_path / "room.ply", **written)

    names, values = read_splat(tmp_path / "room.ply")

    assert names[:9] == ["x", "y", "z", "nx", "ny", "nz", "f_dc_0", "f_dc_1", "f_dc_2"]
    assert names[-8:] == ["opacity", "scale_0", "scale_1", "scale_2"] + [
        f"rot_{i}" for i in range(4)
    ]
    assert len(names) == 9 + 9 + 8
    assert len(values) == 3 * len(names)
    # The second splat's x, and its green degree-1 colour in the channel-major layout.
    assert abs(values[len(names) + 0] - written["means"][1, 0]) < 1e-6
    assert abs(values[len(names) + 9 + 3] - written["shN"][1, 0, 1]) < 1e-6
