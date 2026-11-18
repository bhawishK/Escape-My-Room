"""Pictures of a splat room in room metres, to see its floor and walls (#206).

Writes, beside the room: top.png (seen from above, coloured), top-height.png (from above,
by height), side-x.png and side-z.png (from the side), and heights.png (how many splats at
each height), and prints the room's extents.

Usage: python look.py ROOM_DIR [OUT_DIR] [PLY_NAME]
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from splat import Placement, read_ply

PIXELS_PER_METRE = 120


def project(points: np.ndarray, colours: np.ndarray, axes: tuple[int, int], depth_axis: int, nearest_high: bool,
            bounds: tuple[float, float, float, float]) -> Image.Image:
    """Draws points onto the plane of `axes`, the nearest along `depth_axis` on top."""
    u0, u1, v0, v1 = bounds
    width = int((u1 - u0) * PIXELS_PER_METRE) + 1
    height = int((v1 - v0) * PIXELS_PER_METRE) + 1
    u = ((points[:, axes[0]] - u0) * PIXELS_PER_METRE).astype(int)
    v = ((v1 - points[:, axes[1]]) * PIXELS_PER_METRE).astype(int)
    inside = (u >= 0) & (u < width) & (v >= 0) & (v < height)
    order = np.argsort(points[inside, depth_axis])
    if not nearest_high:
        order = order[::-1]
    image = np.full((height, width, 3), 255, np.uint8)
    image[v[inside][order], u[inside][order]] = (colours[inside][order] * 255).astype(np.uint8)
    return Image.fromarray(image)


def grid(image: Image.Image, bounds: tuple[float, float, float, float], label: str) -> Image.Image:
    """Metre lines and the origin, and a label."""
    u0, u1, v0, v1 = bounds
    draw = ImageDraw.Draw(image)
    for metre in range(int(np.floor(u0)), int(np.ceil(u1)) + 1):
        x = (metre - u0) * PIXELS_PER_METRE
        draw.line([(x, 0), (x, image.height)], fill=(255, 0, 0) if metre == 0 else (200, 200, 200))
    for metre in range(int(np.floor(v0)), int(np.ceil(v1)) + 1):
        y = (v1 - metre) * PIXELS_PER_METRE
        draw.line([(0, y), (image.width, y)], fill=(255, 0, 0) if metre == 0 else (200, 200, 200))
    draw.text((6, 6), label, fill=(0, 0, 0))
    return image


def heat(values: np.ndarray, low: float, high: float) -> np.ndarray:
    t = np.clip((values - low) / (high - low), 0, 1)
    return np.stack([t, 1 - np.abs(t - 0.5) * 2, 1 - t], axis=1)


def main() -> None:
    room = Path(sys.argv[1])
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else room / "look"
    name = sys.argv[3] if len(sys.argv) > 3 else "room.ply"
    out.mkdir(parents=True, exist_ok=True)
    splat = read_ply(room / name)
    placement = Placement.of(room / "manifest.json")
    points = placement.to_room(splat.xyz)
    solid = splat.opacity > 0.15
    print(f"{len(splat)} splats, {solid.sum()} with opacity over 0.15")
    pts, cols = points[solid], splat.colour[solid]
    low, high = np.percentile(pts, 1, axis=0), np.percentile(pts, 99, axis=0)
    print("1st..99th percentile, room metres: x {:.2f}..{:.2f}  y {:.2f}..{:.2f}  z {:.2f}..{:.2f}".format(
        low[0], high[0], low[1], high[1], low[2], high[2]))
    pad = 0.5
    x0, x1 = low[0] - pad, high[0] + pad
    y0, y1 = min(low[1], 0) - pad, high[1] + pad
    z0, z1 = low[2] - pad, high[2] + pad

    # From above, x to the right and -z up the picture, so the top is the far side.
    top_bounds = (x0, x1, -z1, -z0)
    flipped = pts * np.array([1, 1, -1])
    grid(project(flipped[:, [0, 2, 1]], cols, (0, 1), 2, True, top_bounds), top_bounds, f"{name}: from above (x right, -z up)").save(out / "top.png")
    grid(project(flipped[:, [0, 2, 1]], heat(pts[:, 1], 0, 2.5), (0, 1), 2, True, top_bounds), top_bounds,
         "from above, by height: blue 0 m, green 1.25 m, red 2.5 m").save(out / "top-height.png")
    # From the side: looking along -z (x right, y up), and along +x (z right, y up).
    side_x = (x0, x1, y0, y1)
    grid(project(pts, cols, (0, 1), 2, True, side_x), side_x, "from the front (x right, y up)").save(out / "side-x.png")
    side_z = (z0, z1, y0, y1)
    grid(project(pts[:, [2, 1, 0]], cols, (0, 1), 2, False, side_z), side_z, "from the side (z right, y up)").save(out / "side-z.png")

    # How many splats at each height: the floor and ceiling show as peaks.
    edges = np.arange(y0, y1, 0.02)
    counts, _ = np.histogram(pts[:, 1], edges)
    chart = Image.new("RGB", (len(counts) * 3 + 60, 260), "white")
    draw = ImageDraw.Draw(chart)
    peak = counts.max()
    for index, count in enumerate(counts):
        x = 40 + index * 3
        draw.rectangle([x, 240 - 220 * count / peak, x + 2, 240], fill=(40, 90, 200))
    for metre in np.arange(np.ceil(y0 * 2) / 2, y1, 0.5):
        x = 40 + (metre - y0) / 0.02 * 3
        draw.line([(x, 240), (x, 250)], fill=(0, 0, 0))
        draw.text((x - 8, 248), f"{metre:g}", fill=(0, 0, 0))
    draw.text((6, 4), "splats by height (m), 2 cm bins", fill=(0, 0, 0))
    chart.save(out / "heights.png")
    print("peak heights (m):", ", ".join(f"{edges[i]:.2f} ({counts[i]})" for i in np.argsort(counts)[::-1][:6]))


if __name__ == "__main__":
    main()
