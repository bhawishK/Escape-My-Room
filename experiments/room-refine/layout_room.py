"""A room laid out by SpatialLM: its walls set the floor, its furniture becomes solid (#206).

SpatialLM reads the room's points (`export_points.py`: metres, z up, x along the room) and writes
walls, doors, windows and boxes, one per line:

    wall_0=Wall(ax, ay, az, bx, by, bz, height, thickness)
    door_0=Door(wall_2, x, y, z, width, height)          # centre of the opening
    bbox_0=Bbox(bed, x, y, z, angle_z, size_x, size_y, size_z)   # centre, turn about z

This turns them back into the room's frame (x, y up, z): room (x, y, z) = (X, Z, -Y), so a turn
of θ about SpatialLM's z is a turn of θ about the room's y. The floor becomes the rectangle the
walls enclose, so physics' walls (built round the floor) stand where SpatialLM's do. Solid
furniture becomes static entities, bottom-centre as the manifest wants; soft or flat things
(carpets, curtains) are left out. Doors and windows are kept in `layout.json` for later use.

SpatialLM's boxes are checked against the splat, as the model proposes and the measurements
decide: a piece's top is lowered to the densest flat layer of splats inside its footprint when
that is clearly lower (its box may include a bed's frame or posts), and the movable box is put on
the free floor point furthest from all furniture.

Usage: python layout_room.py ROOM_DIR LAYOUT_TXT OUT_DIR [ROOM_VERSION]
"""

from __future__ import annotations

import json
import math
import re
import shutil
import sys
from pathlib import Path

import numpy as np

from refine import write_entity_glb
from splat import Placement, read_ply

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

# Things that stand on the floor and are solid enough to bump into.
SOLID = {"bed", "desk", "chair", "table", "sofa", "cabinet", "wardrobe", "nightstand", "shelf",
         "bookshelf", "dresser", "stool", "bench", "tv_cabinet", "washing_cabinet", "bar"}
LINE = re.compile(r"^(\w+)=(\w+)\((.*)\)$")


def parse(text: str) -> list[tuple[str, str, list[str]]]:
    items = []
    for line in text.splitlines():
        match = LINE.match(line.strip())
        if match:
            name, kind, args = match.groups()
            items.append((name, kind, [arg.strip() for arg in args.split(",")]))
    return items


def to_room(x: float, y: float, z: float) -> tuple[float, float, float]:
    """SpatialLM's z-up point in the room's frame (y up)."""
    return x, z, -y


def turn_about_y(angle: float) -> dict[str, float]:
    return {"x": 0.0, "y": math.sin(angle / 2), "z": 0.0, "w": math.cos(angle / 2)}


def measured_top(points: np.ndarray, centre: tuple[float, float], size: tuple[float, float], top: float) -> float:
    """The densest flat layer of splats inside the footprint's middle, if clearly below `top`."""
    (cx, cz), (width, depth) = centre, size
    inside = ((np.abs(points[:, 0] - cx) < width * 0.4) & (np.abs(points[:, 2] - cz) < depth * 0.4)
              & (points[:, 1] > 0.15) & (points[:, 1] < top + 0.3))
    if inside.sum() < 200:
        return top
    counts, edges = np.histogram(points[inside, 1], np.arange(0.15, top + 0.3, 0.02))
    layer = float(edges[int(np.argmax(counts))] + 0.01)
    return layer if layer < 0.85 * top else top


def free_spot(x: tuple[float, float], z: tuple[float, float], footprints: list[tuple[float, float, float, float]],
              margin: float = 0.25) -> tuple[float, float]:
    """The floor point furthest from every footprint (x0, x1, z0, z1) and the walls."""
    best, far = ((x[0] + x[1]) / 2, (z[0] + z[1]) / 2), -1.0
    for px in np.arange(x[0] + margin, x[1] - margin, 0.05):
        for pz in np.arange(z[0] + margin, z[1] - margin, 0.05):
            gap = min(px - x[0], x[1] - px, pz - z[0], z[1] - pz)
            for fx0, fx1, fz0, fz1 in footprints:
                dx, dz = max(fx0 - px, 0, px - fx1), max(fz0 - pz, 0, pz - fz1)
                gap = min(gap, float(np.hypot(dx, dz)))
            if gap > far:
                best, far = (float(px), float(pz)), gap
    return best


def main() -> None:
    room, layout_path, out = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
    version = int(sys.argv[4]) if len(sys.argv) > 4 else None
    items = parse(layout_path.read_text())
    walls = [[float(v) for v in args] for _, kind, args in items if kind == "Wall"]
    corners = [to_room(*wall[0:3]) for wall in walls] + [to_room(*wall[3:6]) for wall in walls]
    xs, zs = [c[0] for c in corners], [c[2] for c in corners]
    x0, x1, z0, z1 = min(xs), max(xs), min(zs), max(zs)
    height = max(wall[6] for wall in walls)
    print(f"walls enclose x {x0:.2f}..{x1:.2f}, z {z0:.2f}..{z1:.2f} ({x1 - x0:.2f} x {z1 - z0:.2f} m), {height:.2f} m high")

    manifest = json.loads((room / "manifest.json").read_text())
    if version is not None:
        manifest["room_version"] = version
    out.mkdir(parents=True, exist_ok=True)
    entities = []
    for entity in manifest["entities"]:
        if entity["id"].startswith("wall_"):
            continue  # physics builds the walls round the floor
        if entity["id"] == "floor":
            entity["size"].update({"width": x1 - x0, "depth": z1 - z0})
            entity["position"].update({"x": (x0 + x1) / 2, "z": (z0 + z1) / 2})
            write_entity_glb(out, "floor", (x1 - x0, entity["size"]["height"], z1 - z0), "#8d9399")
        else:
            shutil.copy2(room / entity["asset"], out / entity["asset"])
        entities.append(entity)

    splat = read_ply(room / "room.ply")
    points = Placement.of(room / "manifest.json").to_room(splat.xyz)[splat.opacity > 0.15]
    counts: dict[str, int] = {}
    kept, openings, footprints = [], [], []
    for name, kind, args in items:
        if kind in ("Door", "Window"):
            x, y, z = to_room(*(float(v) for v in args[1:4]))
            openings.append({"id": name, "kind": kind.lower(), "wall": args[0], "centre": [x, y, z],
                             "width": float(args[4]), "height": float(args[5])})
        if kind != "Bbox" or args[0] not in SOLID:
            continue
        label = args[0]
        x, y, z, angle, sx, sy, sz = (float(v) for v in args[1:8])
        cx, cy, cz = to_room(x, y, z)
        counts[label] = counts.get(label, 0) + 1
        entity_id = f"layout_{label}_{counts[label]}"
        bottom = max(0.0, cy - sz / 2)  # standing on the floor, never below it
        # Footprint along the room's axes: turned a quarter, width and depth swap.
        quarter = abs(math.sin(angle)) > 0.7
        along_x, along_z = (sy, sx) if quarter else (sx, sy)
        top = measured_top(points, (cx, cz), (along_x, along_z), cy + sz / 2)
        entities.append({
            "id": entity_id, "label": label.replace("_", " ").capitalize(), "asset": f"{entity_id}.glb",
            "node": entity_id, "kind": "static", "selectable": False, "solid": True,
            "size": {"width": sx, "height": top - bottom, "depth": sy},
            "position": {"x": cx, "y": bottom, "z": cz}, "rotation": turn_about_y(angle),
        })
        footprints.append((cx - along_x / 2, cx + along_x / 2, cz - along_z / 2, cz + along_z / 2))
        note = f" (top lowered from {cy + sz / 2:.2f} m to the splat's {top:.2f} m)" if top < cy + sz / 2 else ""
        kept.append(f"{entity_id} {sx:.2f} x {sy:.2f} x {top - bottom:.2f} m at x {cx:.2f}, z {cz:.2f}{note}")
    # Glb heights must match the entities' (a box cut at the floor is shorter).
    for entity in entities:
        if entity["id"].startswith("layout_"):
            size = entity["size"]
            write_entity_glb(out, entity["id"], (size["width"], size["height"], size["depth"]), "#b49a7a")
    for entity in entities:
        if entity["kind"] == "movable":
            x, z = free_spot((x0, x1), (z0, z1), footprints)
            entity["position"].update({"x": x, "y": 0.0, "z": z})
            kept.append(f"{entity['id']} moved to the free spot x {x:.2f}, z {z:.2f}")
    manifest["entities"] = entities
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2))
    for name in ("room.ply", "room-phone.ply", "report.json"):
        shutil.copy2(room / name, out / name)
    (out / "layout.json").write_text(json.dumps({
        "source": "SpatialLM1.1-Qwen-0.5B", "walls": {"x": [x0, x1], "z": [z0, z1], "height": height},
        "openings": openings, "furniture": kept, "raw": layout_path.read_text().splitlines(),
    }, indent=2))
    print("\n".join(kept))

    from backend.prepared_room import load_prepared_room

    loaded = load_prepared_room(out)
    print(f"room {loaded.room_version} accepted: {[entity.id for entity in loaded.entities]}")


if __name__ == "__main__":
    main()
