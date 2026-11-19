"""Keeps only the splats inside a room's walls and above its floor (#206, #209).

Stray splats outside the room are hidden by its walls from inside, but are what the dollhouse
sees first from its corners. This removes splats more than MARGIN_M outside the walls, below the
floor, or above the walls' height, and nothing else: the splat inside is left as it was.

Usage: python crop.py ROOM_DIR WALLS_JSON OUT_DIR
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import numpy as np

from make_room import build_room_module
from splat import Placement, read_ply, write_ply

MARGIN_M = 0.05


def main() -> None:
    room, walls_path, out = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
    walls = json.loads(walls_path.read_text())
    (x0, x1), (z0, z1), height = walls["x"], walls["z"], walls["height"]
    splat = read_ply(room / "room.ply")
    points = Placement.of(room / "manifest.json").to_room(splat.xyz)
    inside = ((points[:, 1] > -MARGIN_M) & (points[:, 1] < height + MARGIN_M)
              & (points[:, 0] > x0 - MARGIN_M) & (points[:, 0] < x1 + MARGIN_M)
              & (points[:, 2] > z0 - MARGIN_M) & (points[:, 2] < z1 + MARGIN_M))
    out.mkdir(parents=True, exist_ok=True)
    for item in room.iterdir():
        if item.is_file() and item.name not in ("room.ply", "room-phone.ply"):
            shutil.copy2(item, out / item.name)
    write_ply(out / "room.ply", splat.subset(inside))
    build = build_room_module()
    build.write_phone_splat(out / "room.ply", out / build.PHONE_FILE, build.PHONE_SPLATS)
    print(f"kept {inside.sum():,} of {len(splat):,} splats inside the room ({(~inside).sum():,} outside)")


if __name__ == "__main__":
    main()
