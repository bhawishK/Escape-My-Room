"""Before and after, seen from the frames' own cameras (#206).

Draws each room's splats as dots through a frame's camera (nearest on top, each dot as wide as
the splat appears, up to a limit) beside the real frame, and measures, over the frame's pixels:
how much of it the room covers, and the mean colour difference where it does.

Usage: python compare.py MODEL_DIR FRAMES_DIR OUT_PNG ROOM_DIR [ROOM_DIR ...] --frames a.jpg,b.jpg
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from cameras import room_frames
from splat import Placement, read_ply

DOWN = 4  # drawn at a quarter of the frame's size


def draw(frame, points: np.ndarray, colours: np.ndarray, radius: np.ndarray) -> np.ndarray:
    width, height = frame.size[0] // DOWN, frame.size[1] // DOWN
    uv, depth = frame.project(points)
    uv = uv / DOWN
    ok = (depth > 0.05) & (uv[:, 0] >= 0) & (uv[:, 0] < width) & (uv[:, 1] >= 0) & (uv[:, 1] < height)
    pixel_radius = np.clip(frame.focal[0] / DOWN * radius[ok] / depth[ok], 0.6, 4).round().astype(int)
    order = np.argsort(-depth[ok])
    image = np.full((height, width, 3), np.nan)
    u, v = uv[ok].astype(int), None
    u, v, c, r = uv[ok][order, 0].astype(int), uv[ok][order, 1].astype(int), colours[ok][order], pixel_radius[order]
    for size in range(0, 5):
        pick = r >= size
        for du in range(-size, size + 1):
            for dv in range(-size, size + 1):
                if max(abs(du), abs(dv)) != size:
                    continue
                image[np.clip(v[pick] + dv, 0, height - 1), np.clip(u[pick] + du, 0, width - 1)] = c[pick]
    # Draw the nearest last: redo the radius-0 pass so near splats win over far wide ones.
    image[v, u] = c
    return image


def main() -> None:
    args = sys.argv[1:]
    names = args[args.index("--frames") + 1].split(",")
    args = args[:args.index("--frames")]
    model, frames_dir, out, rooms = Path(args[0]), Path(args[1]), Path(args[2]), [Path(arg) for arg in args[3:]]
    loaded = []
    for room in rooms:
        splat = read_ply(room / "room.ply")
        placement = Placement.of(room / "manifest.json")
        solid = splat.opacity > 0.1
        radius = splat.scales[solid].max(axis=1) * placement.scale
        # Each room is placed its own way, so each has its own cameras in the room.
        frames = {frame.name: frame for frame in room_frames(model, room / "report.json", placement)[0]}
        loaded.append((room.name, placement.to_room(splat.xyz)[solid], splat.colour[solid], radius, frames))
    rows = []
    for frame_name in names:
        if frame_name not in loaded[0][4]:
            print(f"{frame_name}: not placed by the reconstruction")
            continue
        first = loaded[0][4][frame_name]
        real = np.asarray(Image.open(frames_dir / frame_name).convert("RGB").resize((first.size[0] // DOWN, first.size[1] // DOWN))) / 255
        tiles = [real]
        line = [frame_name]
        for name, points, colours, radius, frames in loaded:
            drawn = draw(frames[frame_name], points, colours, radius)
            covered = ~np.isnan(drawn[..., 0])
            error = np.abs(drawn[covered] - real[covered]).mean() if covered.any() else float("nan")
            line.append(f"{name}: covers {covered.mean():.0%}, colour error {error:.3f}")
            tiles.append(np.nan_to_num(drawn, nan=1.0))
        print(" | ".join(line))
        rows.append(np.concatenate(tiles, axis=1))
    sheet = Image.fromarray((np.concatenate(rows, axis=0) * 255).astype(np.uint8))
    ImageDraw.Draw(sheet).text((4, 4), "real | " + " | ".join(item[0] for item in loaded), fill=(255, 0, 0))
    sheet.save(out)


if __name__ == "__main__":
    main()
