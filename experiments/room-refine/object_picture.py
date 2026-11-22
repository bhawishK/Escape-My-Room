"""A picture of one piece of the room, cut out of the room's own splat (#220): only the splats inside
its box, rendered on pure white with Spark, as L4GM wants its input. No segmentation is needed:
the box is the cut.

Usage: python object_picture.py ROOM_DIR ENTITY_ID OUT_DIR [EYE_X EYE_Y EYE_Z]
"""
import json
import math
import shutil
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
from backend.room_views import View, render_views  # noqa: E402
from splat import Placement, read_ply, write_ply  # noqa: E402

room, entity_id, out = Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3])
out.mkdir(parents=True, exist_ok=True)
manifest = json.loads((room / "manifest.json").read_text())
entity = next(e for e in manifest["entities"] if e["id"] == entity_id)
p, s, q = entity["position"], entity["size"], entity["rotation"]
yaw = 2 * math.atan2(q["y"], q["w"])
MARGIN, FLOOR = 0.06, 0.04

splat = read_ply(room / manifest["splat"]["asset"])
points = Placement.of(room / "manifest.json").to_room(splat.xyz)
# The box's own axes: turn the points by -yaw about y round its centre.
dx, dz = points[:, 0] - p["x"], points[:, 2] - p["z"]
c, sn = math.cos(-yaw), math.sin(-yaw)
lx, lz = c * dx + sn * dz, -sn * dx + c * dz
inside = ((np.abs(lx) < s["width"] / 2 + MARGIN) & (np.abs(lz) < s["depth"] / 2 + MARGIN)
          & (points[:, 1] > p["y"] + FLOOR) & (points[:, 1] < p["y"] + s["height"] + MARGIN))
# Without the haze: faint splats and the largest (stray streaks), which L4GM would take as object.
longest = splat.scales.max(axis=1)
inside &= longest < np.percentile(longest[inside], 99)
piece = splat.subset(inside)
print(f"{entity_id}: {int(inside.sum()):,} of {len(splat):,} splats inside its box")

cut = out / "cut-room"
shutil.rmtree(cut, ignore_errors=True)
shutil.copytree(room, cut, ignore=shutil.ignore_patterns(manifest["splat"]["asset"], "vps"))
write_ply(cut / manifest["splat"]["asset"], piece)
centre = (p["x"], p["y"] + s["height"] / 2, p["z"])
eye = tuple(float(v) for v in sys.argv[4:7]) if len(sys.argv) > 6 else (p["x"] + 1.2, p["y"] + 1.3, p["z"] + 1.1)
reach = max(s["width"], s["depth"], s["height"])
distance = math.dist(eye, centre)
fov = math.degrees(2 * math.atan(reach * 0.62 / distance))
view = View(position=eye, look_at=centre, fov_degrees=fov, width=768, height=768, background="#ffffff")
[image] = render_views(cut, [view])
(out / "picture.png").write_bytes(image.png)
(out / "picture.json").write_text(json.dumps({"entity": entity_id, "eye": eye, "look_at": centre, "fov": fov, "yaw": yaw,
                                               "size": s, "position": p}, indent=1))
shutil.rmtree(cut)
print("picture from", tuple(round(v, 2) for v in eye), f"fov {fov:.0f}")
