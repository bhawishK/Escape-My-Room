"""Refines a splat room into one with a whole floor and walls, keeping its placement (#206).

Given the room (its floor already on y = 0, see fix_floor.py) and its four walls as an LLM or a
person judged them from the evidence (walls.py, the frames), this:
1. removes splats below the floor or outside the walls: reflections and floaters;
2. flattens splats lying on the floor onto it;
3. covers the floor and the walls with flat splats where none are, each coloured from the frames
   that see it, with a depth test so a bed in front doesn't paint the wall behind it;
4. writes the room again, with the walls as static entities for physics.
The manifest's splat placement, and so the calibration and the positioning map, are unchanged.

Usage: python refine.py ROOM_DIR MODEL_DIR FRAMES_DIR OUT_DIR WALLS_JSON
WALLS_JSON: {"x": [left, right], "z": [far, near], "height": metres, "source": "why"}
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import sys
from pathlib import Path

import numpy as np
from PIL import Image

from cameras import room_frames
from splat import SH_C0, Placement, Splat, read_ply, write_ply

ROOT = Path(__file__).resolve().parents[2]
SPACING = 0.03  # metres between new splats
PHONE_SPACING = 0.06
PHONE_SPLATS = 100_000
FLAT_M = 0.03  # splats this near the floor are flattened onto it
OUTSIDE_M = 0.05  # splats further than this outside a wall, or below the floor, are removed
DEPTH_SLACK = 0.12  # a frame sees a point if nothing drawn is this much nearer
FRAME_STEP = 2  # every other frame colours the new splats
BUFFER_DOWN = 8  # the depth test runs at an eighth of the frame's size
WALL_THICKNESS = 0.1


def surface_points(walls: dict) -> list[tuple[str, np.ndarray, np.ndarray, np.ndarray]]:
    """Each surface's name, its grid of points, its unit normal into the room, and two in-plane axes."""
    (x0, x1), (z0, z1), height = walls["x"], walls["z"], walls["height"]
    def grid(a: np.ndarray, b: np.ndarray, spacing: float) -> np.ndarray:
        return np.array(np.meshgrid(a, b, indexing="ij")).reshape(2, -1).T
    surfaces = []
    xs = np.arange(x0 + SPACING / 2, x1, SPACING)
    zs = np.arange(z0 + SPACING / 2, z1, SPACING)
    ys = np.arange(SPACING / 2, height, SPACING)
    floor = grid(xs, zs, SPACING)
    surfaces.append(("floor", np.column_stack([floor[:, 0], np.zeros(len(floor)), floor[:, 1]]),
                     np.array([0, 1.0, 0]), np.array([[1.0, 0, 0], [0, 0, 1.0]])))
    for name, fixed, value, inward in (("wall_left", "x", x0, 1), ("wall_right", "x", x1, -1),
                                       ("wall_far", "z", z0, 1), ("wall_near", "z", z1, -1)):
        along = zs if fixed == "x" else xs
        flat = grid(along, ys, SPACING)
        if fixed == "x":
            points = np.column_stack([np.full(len(flat), value), flat[:, 1], flat[:, 0]])
            normal, axes = np.array([inward, 0, 0.0]), np.array([[0, 0, 1.0], [0, 1.0, 0]])
        else:
            points = np.column_stack([flat[:, 0], flat[:, 1], np.full(len(flat), value)])
            normal, axes = np.array([0, 0, inward * 1.0]), np.array([[1.0, 0, 0], [0, 1.0, 0]])
        surfaces.append((name, points, normal, axes))
    return surfaces


def occupied(points: np.ndarray, cell: float) -> set[tuple[int, int, int]]:
    return set(map(tuple, np.floor(points / cell).astype(int)))


def colour_from_frames(points: np.ndarray, normal: np.ndarray, frames, images, scene: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Each point's median colour over the frames that see it, and how many did."""
    samples: list[list[np.ndarray]] = [[] for _ in range(len(points))]
    for frame, image in zip(frames, images):
        width, height = frame.size
        bw, bh = width // BUFFER_DOWN, height // BUFFER_DOWN
        # What the frame sees nearest, from the room's splats, at a coarse size, widened by a pixel.
        uv, depth = frame.project(scene)
        ok = (depth > 0.05) & (uv[:, 0] >= 0) & (uv[:, 0] < width) & (uv[:, 1] >= 0) & (uv[:, 1] < height)
        buffer = np.full((bh, bw), np.inf)
        cells = (uv[ok] / BUFFER_DOWN).astype(int)
        np.minimum.at(buffer, (np.clip(cells[:, 1], 0, bh - 1), np.clip(cells[:, 0], 0, bw - 1)), depth[ok])
        padded = np.pad(buffer, 1, constant_values=np.inf)
        buffer = np.min([padded[1 + dy:1 + dy + bh, 1 + dx:1 + dx + bw] for dy in (-1, 0, 1) for dx in (-1, 0, 1)], axis=0)

        uv, depth = frame.project(points)
        facing = (frame.centre - points) @ normal > 0  # the surface's front faces the camera
        ok = facing & (depth > 0.1) & (uv[:, 0] >= 0) & (uv[:, 0] < width - 1) & (uv[:, 1] >= 0) & (uv[:, 1] < height - 1)
        index = np.flatnonzero(ok)
        cell = (uv[index] / BUFFER_DOWN).astype(int)
        nearest = buffer[np.clip(cell[:, 1], 0, bh - 1), np.clip(cell[:, 0], 0, bw - 1)]
        seen = index[depth[index] <= nearest + DEPTH_SLACK]
        pixels = uv[seen].astype(int)
        colours = image[pixels[:, 1], pixels[:, 0]] / 255.0
        for i, colour in zip(seen, colours):
            samples[i].append(colour)
    counts = np.array([len(s) for s in samples])
    median = np.array([np.median(s, axis=0) if s else np.full(3, np.nan) for s in samples])
    return median, counts


def fill_unseen(points: np.ndarray, colours: np.ndarray, axes: np.ndarray) -> np.ndarray:
    """Points no frame saw take the colour of the nearest seen point on the same surface."""
    seen = ~np.isnan(colours[:, 0])
    if seen.all() or not seen.any():
        return np.nan_to_num(colours, nan=0.8)
    flat_seen = points[seen] @ axes.T
    flat_unseen = points[~seen] @ axes.T
    filled = colours.copy()
    chunk = 2000
    for start in range(0, len(flat_unseen), chunk):
        part = flat_unseen[start:start + chunk]
        distance = ((part[:, None, :] - flat_seen[None, :, :]) ** 2).sum(-1)
        filled[np.flatnonzero(~seen)[start:start + chunk]] = colours[seen][distance.argmin(1)]
    return filled


def matrix_quaternion(m: np.ndarray) -> np.ndarray:
    """w, x, y, z of a rotation matrix (columns: the splat's local axes)."""
    trace = np.trace(m)
    if trace > 0:
        s = 2 * np.sqrt(trace + 1)
        q = [s / 4, (m[2, 1] - m[1, 2]) / s, (m[0, 2] - m[2, 0]) / s, (m[1, 0] - m[0, 1]) / s]
    else:
        i = int(np.argmax(np.diag(m)))
        j, k = (i + 1) % 3, (i + 2) % 3
        s = 2 * np.sqrt(1 + m[i, i] - m[j, j] - m[k, k])
        v = np.zeros(3)
        v[i] = s / 4
        v[j] = (m[j, i] + m[i, j]) / s
        v[k] = (m[k, i] + m[i, k]) / s
        q = [(m[k, j] - m[j, k]) / s, *v]
    q = np.array(q)
    return q / np.linalg.norm(q)


def new_splats(template: Splat, placement: Placement, points: np.ndarray, colours: np.ndarray,
               axes: np.ndarray, normal: np.ndarray, spacing: float) -> np.ndarray:
    """Flat discs on a surface, as rows of the template's PLY layout, in the PLY's own frame."""
    rows = np.zeros(len(points), dtype=template.data.dtype)
    local = placement.from_room(points)
    for i, key in enumerate("xyz"):
        rows[key] = local[:, i]
    for i in range(3):
        rows[f"f_dc_{i}"] = (colours[:, i] - 0.5) / SH_C0
    rows["opacity"] = np.log(0.97 / 0.03)
    # Discs a little wider than the gap between them, and almost flat.
    in_plane, thin = spacing * 0.75 / placement.scale, 0.003 / placement.scale
    rows["scale_0"], rows["scale_1"], rows["scale_2"] = np.log(in_plane), np.log(in_plane), np.log(thin)
    # The disc's axes in the PLY frame: the placement turns PLY directions into room ones.
    basis = placement.rotation.T @ np.column_stack([axes[0], axes[1], normal])
    q = matrix_quaternion(basis)
    for i in range(4):
        rows[f"rot_{i}"] = q[i]
    return rows


def write_entity_glb(out: Path, name: str, size: tuple[float, float, float], colour: str) -> None:
    spec = importlib.util.spec_from_file_location("multi_asset_room", ROOT / "assets" / "multi-asset-room" / "build_room.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.write_glb(out / f"{name}.glb", name, [module.part(f"{name}_slab", size, colour)])


def main() -> None:
    room, model, frames_dir, out = (Path(arg) for arg in sys.argv[1:5])
    walls = json.loads(Path(sys.argv[5]).read_text())
    manifest = json.loads((room / "manifest.json").read_text())
    placement = Placement.of(room / "manifest.json")
    splat = read_ply(room / "room.ply")
    points = placement.to_room(splat.xyz)
    (x0, x1), (z0, z1), height = walls["x"], walls["z"], walls["height"]

    # 1. Remove what is below the floor or outside the walls.
    keep = ((points[:, 1] > -OUTSIDE_M) & (points[:, 1] < height + 0.3)
            & (points[:, 0] > x0 - OUTSIDE_M) & (points[:, 0] < x1 + OUTSIDE_M)
            & (points[:, 2] > z0 - OUTSIDE_M) & (points[:, 2] < z1 + OUTSIDE_M))
    print(f"removed {np.sum(~keep)} of {len(splat)} splats below the floor or outside the walls")
    kept = splat.subset(keep)
    kept_points = points[keep]

    # 2. Flatten the floor: splats lying on it are put on it.
    flat = np.abs(kept_points[:, 1]) < FLAT_M
    kept_points[flat, 1] = 0.0
    local = placement.from_room(kept_points)
    for i, key in enumerate("xyz"):
        kept.data[key] = local[:, i]
    print(f"flattened {flat.sum()} splats onto the floor")

    # 3. Cover the floor and walls where nothing is, coloured from the frames.
    frames, error = room_frames(model, room / "report.json", placement)
    frames = frames[::FRAME_STEP]
    images = [np.asarray(Image.open(frames_dir / frame.name).convert("RGB")) for frame in frames]
    print(f"{len(frames)} frames colour the new splats (camera fit {error:.4f} m)")
    scene = kept_points[kept.opacity > 0.1]
    taken = occupied(kept_points[kept.opacity > 0.15], SPACING)
    full, phone_rows, report = [kept.data], [], {}
    for name, grid_points, normal, axes in surface_points(walls):
        empty = np.array([tuple(cell) not in taken for cell in np.floor(grid_points / SPACING).astype(int)])
        new = grid_points[empty]
        colours, seen = colour_from_frames(new, normal, frames, images, scene)
        colours = fill_unseen(new, colours, axes)
        full.append(new_splats(kept, placement, new, colours, axes, normal, SPACING))
        # The phone gets the surface at twice the spacing.
        coarse = (np.round((new @ axes.T) / SPACING).astype(int) % 2 == 0).all(axis=1)
        phone_rows.append(new_splats(kept, placement, new[coarse], colours[coarse], axes, normal, PHONE_SPACING))
        report[name] = {"grid": int(len(grid_points)), "added": int(len(new)), "seen_by_a_frame": int((seen > 0).sum()),
                        "median_views": float(np.median(seen)) if len(seen) else 0.0}
        print(f"{name}: {len(new)} of {len(grid_points)} places empty; {(seen > 0).sum()} of them seen by a frame")

    out.mkdir(parents=True, exist_ok=True)
    refined = Splat(kept.names, np.concatenate(full))
    write_ply(out / "room.ply", refined)
    # The phone: its own lighter splat, cleaned the same way, plus the coarse surfaces, within its cap.
    phone = read_ply(room / "room-phone.ply")
    phone_points = placement.to_room(phone.xyz)
    phone_keep = ((phone_points[:, 1] > -OUTSIDE_M) & (phone_points[:, 0] > x0 - OUTSIDE_M) & (phone_points[:, 0] < x1 + OUTSIDE_M)
                  & (phone_points[:, 2] > z0 - OUTSIDE_M) & (phone_points[:, 2] < z1 + OUTSIDE_M))
    phone = phone.subset(phone_keep)
    coarse_rows = np.concatenate(phone_rows)
    added = np.zeros(len(coarse_rows), dtype=phone.data.dtype)
    for name in phone.names:
        added[name] = coarse_rows[name]
    room_part = PHONE_SPLATS - len(added)
    if len(phone) > room_part:
        phone = phone.subset(np.argsort(-phone.opacity)[:room_part])
    phone_data = np.concatenate([phone.data, added])
    write_ply(out / "room-phone.ply", Splat(phone.names, phone_data))

    # 4. The walls as static entities, 10 cm thick outside the room; the floor fills the room.
    entities = [entity for entity in manifest["entities"] if not entity["id"].startswith("wall_")]
    for entity in entities:
        if entity["id"] == "floor":
            entity["size"].update({"width": x1 - x0, "depth": z1 - z0})
            entity["position"].update({"x": (x0 + x1) / 2, "z": (z0 + z1) / 2})
    walls_entities = {
        "wall_left": ((WALL_THICKNESS, height, z1 - z0 + 2 * WALL_THICKNESS), (x0 - WALL_THICKNESS / 2, (z0 + z1) / 2)),
        "wall_right": ((WALL_THICKNESS, height, z1 - z0 + 2 * WALL_THICKNESS), (x1 + WALL_THICKNESS / 2, (z0 + z1) / 2)),
        "wall_far": ((x1 - x0, height, WALL_THICKNESS), ((x0 + x1) / 2, z0 - WALL_THICKNESS / 2)),
        "wall_near": ((x1 - x0, height, WALL_THICKNESS), ((x0 + x1) / 2, z1 + WALL_THICKNESS / 2)),
    }
    for name, (size, (x, z)) in walls_entities.items():
        write_entity_glb(out, name, size, "#d8d4cc")
        entities.append({
            "id": name, "label": name.replace("_", " ").capitalize(), "asset": f"{name}.glb", "node": name,
            "kind": "static", "selectable": False,
            "size": {"width": size[0], "height": size[1], "depth": size[2]},
            "position": {"x": x, "y": 0.0, "z": z}, "rotation": {"x": 0.0, "y": 0.0, "z": 0.0, "w": 1.0},
        })
    manifest["entities"] = entities
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2))
    for name in ("floor.glb", "box.glb", "report.json"):
        shutil.copy2(room / name, out / name)
    floor = next(entity for entity in entities if entity["id"] == "floor")
    write_entity_glb(out, "floor", (floor["size"]["width"], floor["size"]["height"], floor["size"]["depth"]), "#8d9399")
    (out / "refine-report.json").write_text(json.dumps({"surfaces": report, "removed": int(np.sum(~keep)),
                                                         "flattened": int(flat.sum()), "splats": len(refined), "walls": walls,
                                                         "phone_splats": len(phone_data)}, indent=2))
    print(f"wrote {len(refined)} splats ({len(phone_data)} for the phone) to {out}")


if __name__ == "__main__":
    main()
