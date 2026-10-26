"""Read a room splat in the notebook's layout: a binary little-endian PLY of float properties."""

from array import array
from pathlib import Path

from backend.grab import Vector


class SplatFileError(Exception):
    """The file is not a splat this code can read."""


def read_splat(path: Path) -> tuple[list[str], array[float]]:
    """The property names and float values of a binary little-endian PLY of float properties."""
    data = path.read_bytes()
    end = data.index(b"end_header\n") + len(b"end_header\n")
    header = data[:end].decode("ascii").splitlines()
    if "format binary_little_endian 1.0" not in header:
        raise SplatFileError(f"{path} is not a binary little-endian PLY.")
    names = [line.split()[-1] for line in header if line.startswith("property float ")]
    values: array[float] = array("f")
    values.frombytes(data[end:])
    return names, values


def visible_splats(path: Path) -> list[Vector]:
    """Centres of the splats more than half opaque, in the splat's own frame."""
    names, values = read_splat(path)
    stride = len(names)
    x, y, z, opacity = (names.index(name) for name in ("x", "y", "z", "opacity"))
    return [
        (values[i + x], values[i + y], values[i + z])
        for i in range(0, len(values), stride)
        if values[i + opacity] > 0
    ]
