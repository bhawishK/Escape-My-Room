"""The room without one of its pieces (#220): its splats inside its box removed, so a generated
4D version can stand in its place without the real one showing through.

Usage: python hide_object.py ROOM_DIR ENTITY_ID OUT_ROOM_DIR
"""
import json
import math
import shutil
import sys
from pathlib import Path

import numpy as np

from splat import Placement, read_ply, write_ply

room, entity_id, out = Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3])
manifest = json.loads((room / "manifest.json").read_text())
entity = next(e for e in manifest["entities"] if e["id"] == entity_id)
p, s, q = entity["position"], entity["size"], entity["rotation"]
yaw = 2 * math.atan2(q["y"], q["w"])
MARGIN = 0.08
splat = read_ply(room / manifest["splat"]["asset"])
points = Placement.of(room / "manifest.json").to_room(splat.xyz)
dx, dz = points[:, 0] - p["x"], points[:, 2] - p["z"]
c, sn = math.cos(-yaw), math.sin(-yaw)
lx, lz = c * dx + sn * dz, -sn * dx + c * dz
inside = ((np.abs(lx) < s["width"] / 2 + MARGIN) & (np.abs(lz) < s["depth"] / 2 + MARGIN)
          & (points[:, 1] > p["y"] + 0.03) & (points[:, 1] < p["y"] + s["height"] + MARGIN))
shutil.rmtree(out, ignore_errors=True)
shutil.copytree(room, out, ignore=shutil.ignore_patterns(manifest["splat"]["asset"], "vps"))
write_ply(out / manifest["splat"]["asset"], splat.subset(~inside))
print(f"removed {int(inside.sum()):,} splats of {entity_id}")
