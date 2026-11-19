"""A room's splat as a coloured point cloud for SpatialLM (#206): metres, z up, axis-aligned.

SpatialLM takes a PLY point cloud whose z-axis is up and whose walls run along x and y. The room
is placed in metres with y up (the manifest's placement), so each splat's centre is moved into the
room and turned (x, y, z) -> (x, -z, y), which keeps the frame right-handed. Only splats that show
(opacity over `--min-opacity`) are kept, so faint floaters don't read as walls. `--turn-degrees`
turns about the vertical first, for a room whose walls aren't along x and z.

Stray splats far outside the room are cut off: only points within the 1st..99th percentile of
each axis, widened by `--margin` metres, are kept.

Usage: python export_points.py ROOM_DIR OUT_PLY [--min-opacity 0.1] [--turn-degrees 0] [--margin 0.5]
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np

from splat import Placement, read_ply


def z_up(points: np.ndarray, turn_degrees: float = 0.0) -> np.ndarray:
    """Room metres (y up) turned about the vertical by `turn_degrees`, then made z up."""
    angle = np.radians(turn_degrees)
    c, s = np.cos(angle), np.sin(angle)
    x = c * points[:, 0] + s * points[:, 2]
    z = -s * points[:, 0] + c * points[:, 2]
    return np.column_stack([x, -z, points[:, 1]])


def write_points(path: Path, points: np.ndarray, colours: np.ndarray) -> None:
    rows = np.zeros(len(points), dtype=[("x", "<f4"), ("y", "<f4"), ("z", "<f4"),
                                        ("red", "u1"), ("green", "u1"), ("blue", "u1")])
    for i, key in enumerate("xyz"):
        rows[key] = points[:, i]
    for i, key in enumerate(("red", "green", "blue")):
        rows[key] = np.round(colours[:, i] * 255).astype(np.uint8)
    header = (
        "ply\nformat binary_little_endian 1.0\n"
        f"element vertex {len(rows)}\n"
        "property float x\nproperty float y\nproperty float z\n"
        "property uchar red\nproperty uchar green\nproperty uchar blue\nend_header\n"
    )
    with open(path, "wb") as file:
        file.write(header.encode("ascii"))
        rows.tofile(file)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("room", type=Path)
    parser.add_argument("out", type=Path)
    parser.add_argument("--min-opacity", type=float, default=0.1)
    parser.add_argument("--turn-degrees", type=float, default=0.0)
    parser.add_argument("--margin", type=float, default=0.5)
    args = parser.parse_args()
    splat = read_ply(args.room / "room.ply")
    shown = splat.opacity > args.min_opacity
    points = Placement.of(args.room / "manifest.json").to_room(splat.xyz[shown])
    cloud = z_up(points, args.turn_degrees)
    low, high = np.percentile(cloud, 1, axis=0) - args.margin, np.percentile(cloud, 99, axis=0) + args.margin
    core = np.all((cloud >= low) & (cloud <= high), axis=1)
    cloud = cloud[core]
    write_points(args.out, cloud, splat.colour[shown][core])
    low, high = cloud.min(axis=0), cloud.max(axis=0)
    print(f"{len(cloud):,} points; x {low[0]:.2f}..{high[0]:.2f}, y {low[1]:.2f}..{high[1]:.2f}, "
          f"z {low[2]:.2f}..{high[2]:.2f} m -> {args.out}")


if __name__ == "__main__":
    main()
