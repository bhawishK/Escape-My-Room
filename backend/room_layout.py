"""A room's layout from SpatialLM, as part of the pipeline (#270; from the #206 experiment).

Two steps:
- **On the GPU desktop, at the end of a reconstruction** (`layout` stage): the splat's visible
  points, placed in metres as the room builder will place them, are written as SpatialLM's point
  cloud (z up, walls along x and y), and SpatialLM (its own env, like L4GM's) writes `layout.txt`:
  walls, doors, windows and furniture boxes, one per line.
- **When a room is built from it** (`apply_layout`): solid furniture becomes static entities,
  their tops checked against the splat; the floor becomes the rectangle the walls enclose; the
  movable box goes to the freest floor; and `layout.json` keeps the walls and openings, which give
  the dollhouse its walls (#269).

SpatialLM's frame is z up: a room point (x, y, z) with y up is (x, -z, y) there, and back.
"""

import json
import math
import os
import re
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np

SPATIALLM_MODEL = "manycore-research/SpatialLM1.1-Qwen-0.5B"
SPATIALLM_SEED = 0
# Things that stand on the floor and are solid enough to bump into; soft or flat ones are left out.
SOLID = {
    "bed", "desk", "chair", "table", "sofa", "cabinet", "wardrobe", "nightstand", "shelf",
    "bookshelf", "dresser", "stool", "bench", "tv_cabinet", "washing_cabinet", "bar",
}  # fmt: skip
LINE = re.compile(r"^(\w+)=(\w+)\((.*)\)$")
MIN_OPACITY = 0.1
MARGIN = 0.5


class LayoutUnavailable(Exception):
    """SpatialLM can't run here; the message says why. The room is built without a layout."""


def spatiallm_dir() -> Path:
    return Path(os.environ.get("ESCAPE_ROOM_SPATIALLM_DIR") or Path.home() / "spatiallm")


def z_up(points: np.ndarray) -> np.ndarray:
    """Room metres (y up) as SpatialLM's frame (z up)."""
    return np.column_stack([points[:, 0], -points[:, 2], points[:, 1]])


def to_room(x: float, y: float, z: float) -> tuple[float, float, float]:
    """A point of SpatialLM's frame in the room's (y up)."""
    return x, z, -y


def write_points(path: Path, points: np.ndarray, colours: np.ndarray) -> int:
    """`points` (room metres) as SpatialLM's coloured point cloud, strays far outside cut off."""
    cloud = z_up(points)
    low = np.percentile(cloud, 1, axis=0) - MARGIN
    high = np.percentile(cloud, 99, axis=0) + MARGIN
    core = np.all((cloud >= low) & (cloud <= high), axis=1)
    cloud, colours = cloud[core], colours[core]
    rows = np.zeros(
        len(cloud),
        dtype=[
            ("x", "<f4"),
            ("y", "<f4"),
            ("z", "<f4"),
            ("red", "u1"),
            ("green", "u1"),
            ("blue", "u1"),
        ],
    )
    for i, key in enumerate("xyz"):
        rows[key] = cloud[:, i]
    for i, key in enumerate(("red", "green", "blue")):
        rows[key] = np.round(np.clip(colours[:, i], 0, 1) * 255).astype(np.uint8)
    header = (
        "ply\nformat binary_little_endian 1.0\n"
        f"element vertex {len(rows)}\n"
        "property float x\nproperty float y\nproperty float z\n"
        "property uchar red\nproperty uchar green\nproperty uchar blue\nend_header\n"
    )
    with path.open("wb") as file:
        file.write(header.encode("ascii"))
        rows.tofile(file)
    return len(rows)


def run_spatiallm(points: Path, out: Path, folder: Path | None = None) -> None:
    """SpatialLM's layout of `points`, written to `out`. LayoutUnavailable when it can't run."""
    folder = folder or spatiallm_dir()
    # Its own env's Python; a setting can name another (the tests use a fake SpatialLM).
    configured = os.environ.get("ESCAPE_ROOM_SPATIALLM_PYTHON")
    python = Path(configured) if configured else folder / ".venv" / "bin" / "python"
    if not (folder / "inference.py").is_file() or not python.is_file():
        raise LayoutUnavailable(f"SpatialLM isn't installed in {folder}.")
    environment = {key: value for key, value in os.environ.items() if key != "HF_TOKEN"}
    # The model is downloaded once at install; a saved login that expired breaks downloads.
    environment |= {"HF_HUB_OFFLINE": "1", "HF_HUB_DISABLE_IMPLICIT_TOKEN": "1"}
    command = [
        str(python), "inference.py", "--point_cloud", str(points.resolve()),
        "--output", str(out.resolve()), "--model_path", SPATIALLM_MODEL,
        "--seed", str(SPATIALLM_SEED),
    ]  # fmt: skip
    done = subprocess.run(
        command, cwd=folder, env=environment, capture_output=True, text=True, timeout=900
    )
    if done.returncode != 0 or not out.is_file():
        tail = (done.stderr or done.stdout).strip().splitlines()[-3:]
        raise LayoutUnavailable("SpatialLM failed: " + " | ".join(tail))


def placed_points(
    xyz: np.ndarray,
    rotation: tuple[float, float, float, float],
    scale: float,
    position: tuple[float, float, float],
) -> np.ndarray:
    """Splat points in room metres: turned by the unit quaternion (x, y, z, w), scaled, moved."""
    qx, qy, qz, qw = rotation
    q = np.array([qx, qy, qz])
    t = 2 * np.cross(q, xyz)
    turned = xyz + qw * t + np.cross(q, t)
    return np.asarray(position) + scale * turned


def visible_points(
    splat: dict[str, np.ndarray],
    rotation: tuple[float, float, float, float],
    scale: float,
    position: tuple[float, float, float],
) -> tuple[np.ndarray, np.ndarray]:
    """The splat's visible points in room metres, and their colours (0..1)."""
    shown = 1 / (1 + np.exp(-splat["opacities"])) > MIN_OPACITY
    colours = 0.5 + 0.28209479177387814 * splat["sh0"].reshape(len(splat["means"]), -1)[:, :3]
    return placed_points(splat["means"][shown], rotation, scale, position), colours[shown]


def room_points(room: Path) -> np.ndarray:
    """The visible points of the room in `room`, in room metres, as its manifest places them."""
    from backend.reconstruction.splat import read_ply

    manifest: dict[str, Any] = json.loads((room / "manifest.json").read_text(encoding="utf-8"))
    entry: dict[str, Any] = manifest.get("splat") or {}
    rotation: dict[str, float] = entry.get("rotation") or {"x": 0.0, "y": 0.0, "z": 0.0, "w": 1.0}
    position: dict[str, float] = entry.get("position") or {"x": 0.0, "y": 0.0, "z": 0.0}
    points, _ = visible_points(
        read_ply(room / entry.get("asset", "room.ply")),
        (rotation["x"], rotation["y"], rotation["z"], rotation["w"]),
        float(entry.get("scale", 1.0)),
        (position["x"], position["y"], position["z"]),
    )
    return points


def parse(text: str) -> list[tuple[str, str, list[str]]]:
    items: list[tuple[str, str, list[str]]] = []
    for line in text.splitlines():
        match = LINE.match(line.strip())
        if match:
            name, kind, args = match.groups()
            items.append((name, kind, [arg.strip() for arg in args.split(",")]))
    return items


def turn_about_y(angle: float) -> dict[str, float]:
    return {"x": 0.0, "y": math.sin(angle / 2), "z": 0.0, "w": math.cos(angle / 2)}


def measured_top(
    points: np.ndarray, centre: tuple[float, float], size: tuple[float, float], top: float
) -> float:
    """The densest flat layer of splats inside the footprint's middle, if clearly below `top`:
    SpatialLM's box may include a bed's frame or posts."""
    (cx, cz), (width, depth) = centre, size
    inside = (
        (np.abs(points[:, 0] - cx) < width * 0.4)
        & (np.abs(points[:, 2] - cz) < depth * 0.4)
        & (points[:, 1] > 0.15)
        & (points[:, 1] < top + 0.3)
    )
    if inside.sum() < 200:
        return top
    counts, edges = np.histogram(points[inside, 1], np.arange(0.15, top + 0.3, 0.02))
    layer = float(edges[int(np.argmax(counts))] + 0.01)
    return layer if layer < 0.85 * top else top


def free_spot(
    x: tuple[float, float],
    z: tuple[float, float],
    footprints: list[tuple[float, float, float, float]],
    margin: float = 0.25,
) -> tuple[float, float]:
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


def apply_layout(
    room: Path,
    layout_text: str,
    points: np.ndarray,
    write_box: Callable[[Path, str, tuple[float, float, float], str], None],
) -> dict[str, Any]:
    """The room in `room` laid out by SpatialLM's `layout_text`: its manifest, box models and
    `layout.json` rewritten in place. `points` are the splat's visible points in room metres;
    `write_box(folder, name, size, colour)` writes a box model. Returns `layout.json`. A layout
    without walls changes nothing and returns {}."""
    items = parse(layout_text)
    walls = [[float(v) for v in args] for _, kind, args in items if kind == "Wall"]
    if not walls:
        return {}
    corners = [to_room(*wall[0:3]) for wall in walls] + [to_room(*wall[3:6]) for wall in walls]
    xs, zs = [corner[0] for corner in corners], [corner[2] for corner in corners]
    x0, x1, z0, z1 = min(xs), max(xs), min(zs), max(zs)
    height = max(wall[6] for wall in walls)

    manifest = json.loads((room / "manifest.json").read_text(encoding="utf-8"))
    entities: list[dict[str, Any]] = []
    for entity in manifest["entities"]:
        if entity["id"].startswith(("wall_", "layout_")):
            continue  # physics builds the walls round the floor; old layouts are replaced
        if entity["id"] == "floor":
            entity["size"].update({"width": x1 - x0, "depth": z1 - z0})
            entity["position"].update({"x": (x0 + x1) / 2, "z": (z0 + z1) / 2})
            write_box(room, "floor", (x1 - x0, entity["size"]["height"], z1 - z0), "#8d9399")
        entities.append(entity)

    counts: dict[str, int] = {}
    openings: list[dict[str, Any]] = []
    footprints: list[tuple[float, float, float, float]] = []
    kept: list[str] = []
    for name, kind, args in items:
        if kind in ("Door", "Window"):
            x, y, z = to_room(*(float(v) for v in args[1:4]))
            openings.append(
                {
                    "id": name,
                    "kind": kind.lower(),
                    "wall": args[0],
                    "centre": [x, y, z],
                    "width": float(args[4]),
                    "height": float(args[5]),
                }
            )
        if kind != "Bbox" or args[0] not in SOLID:
            continue
        label = args[0]
        x, y, z, angle, sx, sy, sz = (float(v) for v in args[1:8])
        cx, cy, cz = to_room(x, y, z)
        counts[label] = counts.get(label, 0) + 1
        entity_id = f"layout_{label}_{counts[label]}"
        bottom = max(0.0, cy - sz / 2)  # standing on the floor, never below it
        # Its footprint along the room's axes: turned a quarter, width and depth swap.
        quarter = abs(math.sin(angle)) > 0.7
        along_x, along_z = (sy, sx) if quarter else (sx, sy)
        top = measured_top(points, (cx, cz), (along_x, along_z), cy + sz / 2)
        entities.append(
            {
                "id": entity_id,
                "label": label.replace("_", " ").capitalize(),
                "asset": f"{entity_id}.glb",
                "node": entity_id,
                "kind": "static",
                "selectable": False,
                "solid": True,
                "size": {"width": sx, "height": top - bottom, "depth": sy},
                "position": {"x": cx, "y": bottom, "z": cz},
                "rotation": turn_about_y(angle),
            }
        )
        write_box(room, entity_id, (sx, top - bottom, sy), "#b49a7a")
        footprints.append((cx - along_x / 2, cx + along_x / 2, cz - along_z / 2, cz + along_z / 2))
        kept.append(
            f"{entity_id} {sx:.2f} x {sy:.2f} x {top - bottom:.2f} m at x {cx:.2f}, z {cz:.2f}"
        )
    for entity in entities:
        if entity["kind"] == "movable":
            x, z = free_spot((x0, x1), (z0, z1), footprints)
            entity["position"].update({"x": x, "y": 0.0, "z": z})
    manifest["entities"] = entities
    (room / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    layout = {
        "source": SPATIALLM_MODEL.split("/")[-1],
        "walls": {"x": [x0, x1], "z": [z0, z1], "height": height},
        "openings": openings,
        "furniture": kept,
        "raw": layout_text.splitlines(),
    }
    (room / "layout.json").write_text(json.dumps(layout, indent=2), encoding="utf-8")
    return layout
