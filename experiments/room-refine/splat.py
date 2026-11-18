"""Reading and writing a 3D Gaussian splat PLY, and placing it in room metres (#206).

The room is placed as the manifest says: a splat point p in the PLY lands at
position + R(rotation) * (scale * p), as both pages draw it. Refinement edits the PLY's
contents only, so that placement, and with it the calibration, stays exactly as it was.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

SH_C0 = 0.28209479177387814
TYPES = {"float": "<f4", "double": "<f8", "uchar": "u1", "int": "<i4", "uint": "<u4", "short": "<i2", "ushort": "<u2"}


@dataclass
class Splat:
    """Every vertex property of the PLY, by name, in the PLY's own frame."""

    names: list[str]
    data: np.ndarray  # structured array, one row per splat

    def __len__(self) -> int:
        return len(self.data)

    @property
    def xyz(self) -> np.ndarray:
        return np.stack([self.data["x"], self.data["y"], self.data["z"]], axis=1).astype(np.float64)

    @property
    def colour(self) -> np.ndarray:
        """Base colour 0..1 from the zeroth spherical harmonic."""
        dc = np.stack([self.data[f"f_dc_{i}"] for i in range(3)], axis=1)
        return np.clip(0.5 + SH_C0 * dc, 0, 1)

    @property
    def opacity(self) -> np.ndarray:
        return 1 / (1 + np.exp(-self.data["opacity"].astype(np.float64)))

    @property
    def scales(self) -> np.ndarray:
        """Each splat's three extents, in PLY units (the PLY stores their logs)."""
        return np.exp(np.stack([self.data[f"scale_{i}"] for i in range(3)], axis=1).astype(np.float64))

    def subset(self, keep: np.ndarray) -> "Splat":
        return Splat(self.names, self.data[keep])


def read_ply(path: Path) -> Splat:
    with open(path, "rb") as file:
        names: list[str] = []
        dtype: list[tuple[str, str]] = []
        count = 0
        while True:
            line = file.readline().decode("ascii").strip()
            if line.startswith("format") and "binary_little_endian" not in line:
                raise ValueError(f"Only binary little-endian PLY is read, not: {line}")
            if line.startswith("element vertex"):
                count = int(line.split()[-1])
            elif line.startswith("property"):
                _, kind, name = line.split()
                names.append(name)
                dtype.append((name, TYPES[kind]))
            elif line == "end_header":
                break
        data = np.fromfile(file, dtype=np.dtype(dtype), count=count)
    return Splat(names, data)


def write_ply(path: Path, splat: Splat) -> None:
    kinds = {v: k for k, v in TYPES.items()}
    header = ["ply", "format binary_little_endian 1.0", f"element vertex {len(splat)}"]
    for name in splat.names:
        header.append(f"property {kinds[splat.data.dtype[name].str]} {name}")
    header.append("end_header")
    with open(path, "wb") as file:
        file.write(("\n".join(header) + "\n").encode("ascii"))
        splat.data.tofile(file)


def quaternion_matrix(q: dict[str, float]) -> np.ndarray:
    x, y, z, w = q["x"], q["y"], q["z"], q["w"]
    return np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
    ])


@dataclass
class Placement:
    """The manifest's splat placement: PLY units to room metres and back."""

    position: np.ndarray
    rotation: np.ndarray
    scale: float

    @classmethod
    def of(cls, manifest: Path) -> "Placement":
        splat = json.loads(manifest.read_text())["splat"]
        position = splat.get("position", {"x": 0, "y": 0, "z": 0})
        rotation = splat.get("rotation", {"x": 0, "y": 0, "z": 0, "w": 1})
        return cls(np.array([position["x"], position["y"], position["z"]]), quaternion_matrix(rotation), float(splat.get("scale", 1)))

    def to_room(self, points: np.ndarray) -> np.ndarray:
        return self.position + (self.scale * points) @ self.rotation.T

    def from_room(self, points: np.ndarray) -> np.ndarray:
        return ((points - self.position) @ self.rotation) / self.scale
