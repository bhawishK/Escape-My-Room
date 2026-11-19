"""Renders rooms with Spark, the devices' own splat renderer, side by side (#206).

For each chosen filmed view, and a view from above, draws every room given, beside the real frame
when there is one, into one sheet.

Usage: python render.py OUT_PNG FRAMES_DIR ROOM_DIR [ROOM_DIR ...] --views 11,41,61
"""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from PIL import Image, ImageDraw  # noqa: E402

from backend.room_views import View, filmed, render_views  # noqa: E402

TILE = (360, 640)


def main() -> None:
    args = sys.argv[1:]
    indices = [int(i) for i in args[args.index("--views") + 1].split(",")]
    args = args[:args.index("--views")]
    out, frames_dir, rooms = Path(args[0]), Path(args[1]), [Path(arg) for arg in args[2:]]
    names = [camera["name"] for camera in json.loads((rooms[0] / "report.json").read_text())["cameras"]]
    rows = []
    columns: list[list[Image.Image]] = []
    for room in rooms:
        views = filmed(room)
        chosen = [View(position=views[i].position, look_at=views[i].look_at, fov_degrees=56.6, width=450, height=800)
                  for i in indices]
        # From above the room's middle, as the dollhouse is seen.
        chosen.append(View(position=(0.55, 4.2, 0.0), look_at=(0.55, 0.0, -0.001), fov_degrees=60, width=450, height=800))
        rendered = render_views(room, chosen)
        columns.append([Image.open(io.BytesIO(item.png)).convert("RGB").resize(TILE) for item in rendered])
    for row, index in enumerate(indices + [None]):
        tiles = []
        if index is not None:
            tiles.append(Image.open(frames_dir / names[index]).convert("RGB").resize(TILE))
        else:
            tiles.append(Image.new("RGB", TILE, "white"))
        tiles += [column[row] for column in columns]
        strip = Image.new("RGB", (TILE[0] * len(tiles), TILE[1]), "white")
        for i, tile in enumerate(tiles):
            strip.paste(tile, (i * TILE[0], 0))
        rows.append(strip)
    sheet = Image.new("RGB", (rows[0].width, TILE[1] * len(rows)), "white")
    for i, strip in enumerate(rows):
        sheet.paste(strip, (0, i * TILE[1]))
    ImageDraw.Draw(sheet).text((6, 6), "real | " + " | ".join(room.name for room in rooms), fill=(255, 0, 0))
    sheet.save(out)
    print("saved", out)


if __name__ == "__main__":
    main()
