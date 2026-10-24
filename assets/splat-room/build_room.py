"""Write a prepared room whose look is a Gaussian splat (issue #92): a floor, a box, the splat.

    python assets/splat-room/build_room.py SOURCE OUT

SOURCE holds the notebook's `room.ply` and, optionally, its `report.json`. The splat already sits
in the room frame (meters, +Y up, floor at y = 0), so it is copied as it is. The floor entity is
sized to where the splat is, so the phone's walking stays in the room; it is not drawn. The box is
placed on the floor 1 m in front of the middle filmed viewpoint, so there is something to pick up.
OUT is usually `data/splat-room`; set ESCAPE_ROOM_PREPARED_DIR to it before starting Python.

With no arguments, writes the committed test room here: a small synthetic splat of a checkered
floor and a red block, for the automated tests.
"""

import importlib.util
import json
import math
import shutil
import struct
import sys
from array import array
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
FLOOR_HEIGHT = 0.02
BOX_SIZE = 0.3
MIN_FLOOR = 2.0

_spec = importlib.util.spec_from_file_location(
    "multi_asset_room", ROOT.parent / "multi-asset-room" / "build_room.py"
)
assert _spec and _spec.loader
multi_asset = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(multi_asset)


def read_splat(path: Path) -> tuple[list[str], array]:
    """The property names and float values of a binary little-endian PLY of float properties."""
    data = path.read_bytes()
    end = data.index(b"end_header\n") + len(b"end_header\n")
    header = data[:end].decode("ascii").splitlines()
    if "format binary_little_endian 1.0" not in header:
        raise SystemExit(f"{path} is not a binary little-endian PLY.")
    names = [line.split()[-1] for line in header if line.startswith("property float ")]
    values = array("f")
    values.frombytes(data[end:])
    return names, values


def floor_extent(path: Path) -> tuple[float, float, float, float]:
    """The middle 90% of the room's visible splats across x and z, at least MIN_FLOOR wide."""
    names, values = read_splat(path)
    stride = len(names)
    x, y, z, opacity = (names.index(name) for name in ("x", "y", "z", "opacity"))
    xs, zs = [], []
    for start in range(0, len(values), stride):
        visible = values[start + opacity] > 0  # more than half opaque
        if visible and -0.3 < values[start + y] < 2.6:
            xs.append(values[start + x])
            zs.append(values[start + z])
    if len(xs) < 20:
        raise SystemExit(f"{path} has too few visible splats near the floor.")

    def middle(items: list[float]) -> tuple[float, float]:
        items.sort()
        low, high = items[len(items) // 20], items[len(items) * 19 // 20]
        centre, half = (low + high) / 2, max(high - low, MIN_FLOOR) / 2
        return centre - half, centre + half

    (min_x, max_x), (min_z, max_z) = middle(xs), middle(zs)
    return min_x, max_x, min_z, max_z


def box_place(report: Path, extent: tuple[float, float, float, float]) -> tuple[float, float]:
    """1 m in front of the middle filmed viewpoint, kept on the floor."""
    min_x, max_x, min_z, max_z = extent
    x, z = (min_x + max_x) / 2, (min_z + max_z) / 2
    if report.is_file():
        cameras = json.loads(report.read_text(encoding="utf-8")).get("cameras", [])
        if cameras:
            camera = cameras[len(cameras) // 2]
            forward = camera.get("forward", [0.0, 0.0, -1.0])
            length = math.hypot(forward[0], forward[2]) or 1.0
            x = camera["position"][0] + forward[0] / length
            z = camera["position"][2] + forward[2] / length
    margin = BOX_SIZE
    return min(max(x, min_x + margin), max_x - margin), min(max(z, min_z + margin), max_z - margin)


def write_room(out: Path, splat: Path, report: Path, room_version: int) -> None:
    out.mkdir(parents=True, exist_ok=True)
    if splat.resolve() != (out / "room.ply").resolve():
        shutil.copyfile(splat, out / "room.ply")
    extent = floor_extent(out / "room.ply")
    min_x, max_x, min_z, max_z = extent
    width, depth = max_x - min_x, max_z - min_z
    box_x, box_z = box_place(report, extent)
    multi_asset.write_glb(
        out / "floor.glb",
        "floor",
        [multi_asset.part("floor_slab", (width, FLOOR_HEIGHT, depth), "#8d9399")],
    )
    multi_asset.write_glb(
        out / "box.glb", "box", [multi_asset.part("box_body", (BOX_SIZE,) * 3, "#ff9500")]
    )
    identity = {"x": 0.0, "y": 0.0, "z": 0.0, "w": 1.0}

    def entity(id_: str, label: str, kind: str, size: tuple, position: tuple) -> dict[str, Any]:
        return {
            "id": id_,
            "label": label,
            "asset": f"{id_}.glb",
            "node": id_,
            "kind": kind,
            "selectable": kind == "movable",
            "size": dict(zip(("width", "height", "depth"), size, strict=True)),
            "position": dict(zip("xyz", position, strict=True)),
            "rotation": identity,
        }

    centre = ((min_x + max_x) / 2, -FLOOR_HEIGHT, (min_z + max_z) / 2)
    manifest = {
        "schema_version": 2,
        "room_version": room_version,
        "units": "meters",
        "frame": "y_up_right_handed",
        "pivot": "bottom_center",
        "quaternion_order": "xyzw",
        "splat": {"asset": "room.ply"},
        "entities": [
            entity("floor", "Floor", "static", (width, FLOOR_HEIGHT, depth), centre),
            entity("box", "Box", "movable", (BOX_SIZE,) * 3, (box_x, 0.0, box_z)),
        ],
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {out}: floor {width:.1f} x {depth:.1f} m, box at ({box_x:.2f}, {box_z:.2f})")


def write_test_splat(path: Path) -> None:
    """A 3 m checkered floor of splats and a red block on it, in the notebook's PLY layout."""
    names = ["x", "y", "z", "nx", "ny", "nz", "f_dc_0", "f_dc_1", "f_dc_2", "opacity"]
    names += ["scale_0", "scale_1", "scale_2", "rot_0", "rot_1", "rot_2", "rot_3"]
    splats = []
    steps = [i * 0.08 - 1.5 for i in range(38)]
    for x in steps:
        for z in steps:
            light = (math.floor(x * 2) + math.floor(z * 2)) % 2
            splats.append((x, 0.0, z, (0.85, 0.85, 0.85) if light else (0.3, 0.32, 0.36)))
    for i in range(12):
        for j in range(10):
            splats.append((-0.5 + i * 0.08, j * 0.08, -1.0, (0.85, 0.2, 0.2)))
    sh = 0.28209479177387814
    scale = math.log(0.05)
    data = b"".join(
        struct.pack(
            "<17f",
            *(x, y, z, 0, 0, 0),
            *((c - 0.5) / sh for c in colour),
            4.0,
            *(scale,) * 3,
            1,
            0,
            0,
            0,
        )
        for x, y, z, colour in splats
    )
    header = ["ply", "format binary_little_endian 1.0", f"element vertex {len(splats)}"]
    header += [f"property float {name}" for name in names] + ["end_header", ""]
    path.write_bytes("\n".join(header).encode() + data)


def main() -> None:
    if len(sys.argv) == 1:
        write_test_splat(ROOT / "room.ply")
        write_room(ROOT, ROOT / "room.ply", ROOT / "report.json", room_version=1)
        return
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    source, out = Path(sys.argv[1]), Path(sys.argv[2])
    # One more than the room built there before, so devices still showing it load this one.
    previous = out / "manifest.json"
    version = 1
    if previous.is_file():
        version = json.loads(previous.read_text(encoding="utf-8"))["room_version"] + 1
    write_room(out, source / "room.ply", source / "report.json", room_version=version)


if __name__ == "__main__":
    main()
