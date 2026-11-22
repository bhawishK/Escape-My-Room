"""The filmed frame that shows a piece of furniture best (#220): its box projected into every frame.

A frame scores by how much of the box's outline is inside it and how large it appears, preferring
the box near the middle. Writes the frame, the box drawn on it, and the box's pixel rectangle.

Usage: python best_view.py ROOM_DIR MODEL_DIR REPORT_JSON FRAMES_DIR ENTITY_ID OUT_DIR
"""
import json
import math
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from cameras import room_frames
from splat import Placement

room, model, report, frames_dir = (Path(a) for a in sys.argv[1:5])
entity_id, out = sys.argv[5], Path(sys.argv[6])
out.mkdir(parents=True, exist_ok=True)
manifest = json.loads((room / "manifest.json").read_text())
entity = next(e for e in manifest["entities"] if e["id"] == entity_id)
p, s, q = entity["position"], entity["size"], entity["rotation"]
yaw = 2 * math.atan2(q["y"], q["w"])
c, sn = math.cos(yaw), math.sin(yaw)
corners = []
for dx in (-1, 1):
    for dz in (-1, 1):
        for y in (0.0, s["height"]):
            lx, lz = dx * s["width"] / 2, dz * s["depth"] / 2
            corners.append((p["x"] + c * lx + sn * lz, p["y"] + y, p["z"] - sn * lx + c * lz))
corners = np.array(corners)
centre = corners.mean(axis=0)

frames, error = room_frames(model, report, Placement.of(room / "manifest.json"))
scored = []
for frame in frames:
    uv, depth = frame.project(corners)
    if (depth <= 0.2).any():
        continue
    w, h = frame.size
    x0, y0 = uv.min(axis=0)
    x1, y1 = uv.max(axis=0)
    box_area = (x1 - x0) * (y1 - y0)
    cx0, cy0, cx1, cy1 = max(x0, 0), max(y0, 0), min(x1, w), min(y1, h)
    if cx1 <= cx0 or cy1 <= cy0:
        continue
    inside = (cx1 - cx0) * (cy1 - cy0) / box_area  # share of the box in the frame
    size = box_area / (w * h)
    middle, _ = frame.project(centre[None])
    mu, mv = middle[0]
    off = math.hypot(mu / w - 0.5, mv / h - 0.5)
    score = inside ** 3 * min(size, 0.5) * (1 - off)
    scored.append((score, frame.name, (x0, y0, x1, y1), inside, size))
scored.sort(reverse=True)
for score, name, box, inside, size in scored[:5]:
    print(f"{name}: score {score:.3f}, {inside:.0%} of the box in frame, box {size:.0%} of the frame")
score, name, box, inside, size = scored[0]
image = Image.open(frames_dir / name).convert("RGB")
image.save(out / "best.jpg", quality=95)
marked = image.copy()
ImageDraw.Draw(marked).rectangle(box, outline=(255, 0, 0), width=8)
marked.save(out / "best-box.jpg", quality=85)
(out / "best.json").write_text(json.dumps({"frame": name, "box": [float(v) for v in box], "entity": entity_id}, indent=1))
