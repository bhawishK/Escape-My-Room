"""Finds a room's four walls from its splat, in room metres (#206).

Rooms are mostly rectangular. So this finds the turn about the vertical that makes the splats
line up best with x and z (the sharpest histograms), then, along each of those directions, the
outermost strong pile-up of splats between LOWEST_M and HIGHEST_M up (above the beds and
desks, where walls and tall cupboards are most of what there is): a wall. It draws them over the
room seen from above (walls.png) for a person, or an LLM, to judge, and writes walls.json.

Usage: python walls.py ROOM_DIR [STRONG_FRACTION] [LOWEST_M] [HIGHEST_M]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
from PIL import ImageDraw

from look import PIXELS_PER_METRE, grid, heat, project
from splat import Placement, read_ply

BIN_M = 0.02


def sharpness(values: np.ndarray) -> float:
    counts, _ = np.histogram(values, np.arange(values.min(), values.max() + BIN_M, BIN_M))
    p = counts[counts > 0] / counts.sum()
    return float((p * np.log(p)).sum())  # minus the entropy: higher is sharper


def best_turn(xz: np.ndarray) -> float:
    """The yaw, in radians, that best lines the splats up with the axes (within ±45°)."""
    def score(angle: float) -> float:
        c, s = np.cos(angle), np.sin(angle)
        turned = xz @ np.array([[c, -s], [s, c]]).T
        return sharpness(turned[:, 0]) + sharpness(turned[:, 1])
    coarse = max(np.radians(np.arange(-45, 45, 1.0)), key=score)
    return max(coarse + np.radians(np.arange(-1, 1.01, 0.05)), key=score)


def outer_walls(values: np.ndarray, strong: float) -> tuple[float, float, np.ndarray, np.ndarray]:
    """The outermost bins, from each end, holding at least `strong` of the fullest bin."""
    edges = np.arange(np.percentile(values, 0.5) - 0.1, np.percentile(values, 99.5) + 0.1, BIN_M)
    counts, _ = np.histogram(values, edges)
    threshold = strong * counts.max()
    low = next(i for i in range(len(counts)) if counts[i] >= threshold)
    high = next(i for i in reversed(range(len(counts))) if counts[i] >= threshold)
    return float(edges[low] + BIN_M / 2), float(edges[high] + BIN_M / 2), counts, edges


def main() -> None:
    room = Path(sys.argv[1])
    strong = float(sys.argv[2]) if len(sys.argv) > 2 else 0.3
    lowest = float(sys.argv[3]) if len(sys.argv) > 3 else 1.0
    highest = float(sys.argv[4]) if len(sys.argv) > 4 else 1.8
    splat = read_ply(room / "room.ply")
    points = Placement.of(room / "manifest.json").to_room(splat.xyz)
    band = (splat.opacity > 0.15) & (points[:, 1] > lowest) & (points[:, 1] < highest)
    xz = points[band][:, [0, 2]]
    yaw = best_turn(xz)
    c, s = np.cos(yaw), np.sin(yaw)
    turned = xz @ np.array([[c, -s], [s, c]]).T
    x0, x1, xc, xe = outer_walls(turned[:, 0], strong)
    z0, z1, zc, ze = outer_walls(turned[:, 1], strong)
    print(f"turn {np.degrees(yaw):.2f}°; walls along the turned axes: x {x0:.2f} and {x1:.2f}, z {z0:.2f} and {z1:.2f}")
    print(f"room inside the walls: {x1 - x0:.2f} × {z1 - z0:.2f} m")
    for name, counts, edges in (("x", xc, xe), ("z", zc, ze)):
        top = np.argsort(counts)[::-1][:8]
        print(f"strongest {name} bins:", ", ".join(f"{edges[i] + BIN_M / 2:.2f} ({counts[i]})" for i in sorted(top)))

    # Corners back in room metres (the turn undone), drawn over the room from above.
    back = np.array([[c, s], [-s, c]])
    corners = np.array([[x0, z0], [x1, z0], [x1, z1], [x0, z1]]) @ back.T
    everything = points[splat.opacity > 0.15]
    low, high = np.percentile(everything, 1, axis=0) - 0.5, np.percentile(everything, 99, axis=0) + 0.5
    bounds = (low[0], high[0], -high[2], -low[2])
    flipped = everything * np.array([1, 1, -1])
    image = grid(project(flipped[:, [0, 2, 1]], heat(everything[:, 1], 0, 2.5), (0, 1), 2, True, bounds), bounds,
                 f"walls found (black), turn {np.degrees(yaw):.1f} deg; colour = height")
    draw = ImageDraw.Draw(image)
    pixel = [((x - bounds[0]) * PIXELS_PER_METRE, (bounds[3] + z) * PIXELS_PER_METRE) for x, z in corners]
    draw.line(pixel + [pixel[0]], fill=(0, 0, 0), width=3)
    image.save(room / "look" / "walls.png")
    (room / "walls.json").write_text(json.dumps({
        "yaw_degrees": float(np.degrees(yaw)), "turned": {"x": [x0, x1], "z": [z0, z1]},
        "corners_xz": corners.tolist(),
    }, indent=2))


if __name__ == "__main__":
    main()
