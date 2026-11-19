"""Renders of a room from views the phone never filmed, each with its nearest filmed frame (#215).

The views are holes.py's (standing across the floor looking at each wall, the upper corners) and a
few looking into the room's least-filmed corner. Each is rendered with Spark, as the devices draw
it, and paired with the filmed frame that looks most the same way from nearby: Difix's reference.
Writes OUT_DIR/<n>-render.png, <n>-reference.png and views.json.

Usage: python difix_views.py ROOM_DIR MODEL_DIR REPORT_JSON FRAMES_DIR WALLS_JSON OUT_DIR
"""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))

from PIL import Image  # noqa: E402

from backend.room_views import View, render_views  # noqa: E402
from cameras import room_frames  # noqa: E402
from holes import views_for  # noqa: E402
from splat import Placement  # noqa: E402

SIZE = (640, 480)


def nearest(frames, position: np.ndarray, look_at: np.ndarray):
    """The frame looking most the same way from nearby: 1 m of distance counts as 45 degrees."""
    forward = (look_at - position) / np.linalg.norm(look_at - position)
    def cost(frame) -> float:
        angle = np.degrees(np.arccos(np.clip(frame.rotation[2] @ forward, -1, 1)))
        return angle / 45 + float(np.linalg.norm(frame.centre - position))
    return min(frames, key=cost)


def main() -> None:
    room, model, report, frames_dir, walls_file, out = (Path(arg) for arg in sys.argv[1:7])
    walls = json.loads(walls_file.read_text())
    walls = walls.get("walls", walls)
    out.mkdir(parents=True, exist_ok=True)
    frames, error = room_frames(model, report, Placement.of(room / "manifest.json"))
    print(f"{len(frames)} filmed frames placed in the room (fit error {error:.3f})")
    named = [(name, view) for name, view in views_for(room, walls) if not name.startswith("filmed")]
    (x0, x1), (z0, z1) = walls["x"], walls["z"]
    # The least-filmed corner: furthest from every filmed camera, on the floor.
    centres = np.array([frame.centre for frame in frames])
    corners = {"near-left": (x0, z1), "near-right": (x1, z1), "far-left": (x0, z0), "far-right": (x1, z0)}
    far_name, (fx, fz) = max(corners.items(), key=lambda item: np.min(np.hypot(centres[:, 0] - item[1][0], centres[:, 2] - item[1][1])))
    cx, cz = (x0 + x1) / 2, (z0 + z1) / 2
    for step, (sx, sz) in enumerate([(cx, cz), ((cx + fx) / 2, cz), (cx, (cz + fz) / 2)]):
        named.append((f"into {far_name} {step}", View(position=(sx, 1.6, sz), look_at=(fx, 0.6, fz))))
    print(f"least-filmed corner: {far_name}")
    views = [View(position=v.position, look_at=v.look_at, fov_degrees=70, width=SIZE[0], height=SIZE[1]) for _, v in named]
    rendered = render_views(room, views)
    listing = []
    for index, ((name, view), image) in enumerate(zip(named, rendered)):
        frame = nearest(frames, np.array(view.position), np.array(view.look_at))
        Image.open(io.BytesIO(image.png)).convert("RGB").save(out / f"{index:02d}-render.png")
        reference = Image.open(frames_dir / frame.name).convert("RGB").resize(SIZE)
        reference.save(out / f"{index:02d}-reference.png")
        listing.append({"index": index, "view": name, "position": list(view.position), "look_at": list(view.look_at),
                        "reference": frame.name})
        print(f"{index:02d} {name:28s} reference {frame.name}")
    (out / "views.json").write_text(json.dumps(listing, indent=2))


if __name__ == "__main__":
    main()
