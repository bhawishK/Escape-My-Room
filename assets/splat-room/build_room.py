"""Write a prepared room whose look is a Gaussian splat (issue #92): a floor, a box, the splat.

    python assets/splat-room/build_room.py SOURCE OUT

SOURCE holds the notebook's `room.ply` and, optionally, its `report.json`. Both are copied as they
are; with a report, the manifest also places it: turned so the camera path is level, raised so
the floor is at y = 0, and scaled so the phone was held 1.4 m up. The floor entity is sized to
where the splat is, so the phone's walking stays in the room; it is not drawn. The box is placed on
the floor 1 m in front of the viewpoint nearest the origin, so there is something to pick up.
OUT is usually `data/splat-room`; set ESCAPE_ROOM_PREPARED_DIR to it before starting Python.
The manifest's `scale_source` says the scale is assumed from that height.

    python assets/splat-room/build_room.py --rescale ROOM FACTOR SOURCE

makes a built room FACTOR times larger and records SOURCE as where its scale came from (#33);
`python -m backend.room_scale_check` suggests the factor from the room's doors.

With no arguments, writes the committed test room here: a small synthetic splat of a checkered
floor and a red block, for the automated tests.
"""

import importlib.util
import json
import math
import shutil
import struct
import sys
from pathlib import Path
from typing import Any

from backend.room_map import make_map
from backend.room_views import RenderFailure
from backend.splat_file import read_splat, visible_splats

ROOT = Path(__file__).resolve().parent
FLOOR_HEIGHT = 0.02
BOX_SIZE = 0.3
MIN_FLOOR = 2.0
CAMERA_HEIGHT = 1.4
# A phone draws this many splats at most, so 8th Wall keeps its pace (#109): the hallway's
# 400,000 left it about 5 poses a second on the iPhone.
PHONE_SPLATS = 150_000
PHONE_FILE = "room-phone.ply"
# What Spark needs to draw a splat in its base colour; view-dependent colour is left out.
PHONE_PROPERTIES = ["x", "y", "z", "f_dc_0", "f_dc_1", "f_dc_2", "opacity"]
PHONE_PROPERTIES += ["scale_0", "scale_1", "scale_2", "rot_0", "rot_1", "rot_2", "rot_3"]

_spec = importlib.util.spec_from_file_location(
    "multi_asset_room", ROOT.parent / "multi-asset-room" / "build_room.py"
)
assert _spec and _spec.loader
multi_asset = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(multi_asset)


Vector = tuple[float, float, float]
Quaternion = tuple[float, float, float, float]  # x, y, z, w
IDENTITY: Quaternion = (0.0, 0.0, 0.0, 1.0)


def rotate(q: Quaternion, v: Vector) -> Vector:
    """v turned by the unit quaternion q."""
    x, y, z, w = q
    # t = 2 (q.xyz x v); v' = v + w t + q.xyz x t
    tx, ty, tz = 2 * (y * v[2] - z * v[1]), 2 * (z * v[0] - x * v[2]), 2 * (x * v[1] - y * v[0])
    return (
        v[0] + w * tx + (y * tz - z * ty),
        v[1] + w * ty + (z * tx - x * tz),
        v[2] + w * tz + (x * ty - y * tx),
    )


def level_from_walk(positions: list[Vector]) -> tuple[Quaternion, float]:
    """The turn that makes the camera path level, and its angle in degrees.

    A walk-through keeps the phone at a steady height, so the path's best-fit plane is horizontal
    in the real room. The notebook levels by the floor it finds instead, and a floor barely in
    shot can leave the room tilted (28 degrees in the hallway video). The path is trusted only
    when it spans at least 0.8 m both ways and keeps within 0.15 m of its plane.
    """
    n = len(positions)
    if n < 10:
        return IDENTITY, 0.0
    mx, my, mz = (sum(p[i] for p in positions) / n for i in range(3))
    xx = sum((p[0] - mx) ** 2 for p in positions)
    zz = sum((p[2] - mz) ** 2 for p in positions)
    xz = sum((p[0] - mx) * (p[2] - mz) for p in positions)
    xy = sum((p[0] - mx) * (p[1] - my) for p in positions)
    zy = sum((p[2] - mz) * (p[1] - my) for p in positions)
    span_x = max(p[0] for p in positions) - min(p[0] for p in positions)
    span_z = max(p[2] for p in positions) - min(p[2] for p in positions)
    det = xx * zz - xz * xz
    if span_x < 0.8 or span_z < 0.8 or det <= 0:
        return IDENTITY, 0.0
    # Height as a plane over x and z: y = my + a (x - mx) + b (z - mz).
    a, b = (xy * zz - zy * xz) / det, (zy * xx - xy * xz) / det
    off = [p[1] - my - a * (p[0] - mx) - b * (p[2] - mz) for p in positions]
    if math.sqrt(sum(d * d for d in off) / n) > 0.15:
        return IDENTITY, 0.0
    length = math.sqrt(a * a + 1 + b * b)
    nx, ny, nz = -a / length, 1 / length, -b / length
    # The shortest turn taking the plane's normal to +Y: about normal x Y = (-nz, 0, nx).
    sine = math.hypot(nx, nz)
    if sine < 1e-6:
        return IDENTITY, 0.0
    angle = math.atan2(sine, ny)
    half = math.sin(angle / 2) / sine
    return (-nz * half, 0.0, nx * half, math.cos(angle / 2)), math.degrees(angle)


def floor_height(heights: list[float], camera: float) -> float:
    """The most crowded level at least 0.6 below the camera: the largest flat surface, the floor."""
    low = sorted(heights)[len(heights) // 200]
    top = camera - 0.6
    candidates = [h for h in heights if low <= h <= top]
    if len(candidates) < 20:
        return 0.0
    bins = 40
    width = (top - low) / bins
    counts = [0] * bins
    for h in candidates:
        counts[min(int((h - low) / width), bins - 1)] += 1
    peak = low + (counts.index(max(counts)) + 0.5) * width
    near = sorted(h for h in candidates if abs(h - peak) <= width)
    return near[len(near) // 2]


def placement(splat: Path, cameras: list[dict]) -> dict[str, Any]:
    """Level by the walk, put the floor at y = 0, and scale so the phone was held 1.4 m up."""
    if not cameras:
        return {"rotation": IDENTITY, "scale": 1.0, "lift": 0.0, "tilt": 0.0, "source": None}
    turn, tilt = level_from_walk([tuple(c["position"]) for c in cameras])
    camera = sum(rotate(turn, tuple(c["position"]))[1] for c in cameras) / len(cameras)
    floor = floor_height([rotate(turn, p)[1] for p in visible_splats(splat)], camera)
    if camera - floor <= 0.2:
        return {"rotation": turn, "scale": 1.0, "lift": 0.0, "tilt": tilt, "source": None}
    scale = CAMERA_HEIGHT / (camera - floor)
    source = f"assumed: the phone was held {CAMERA_HEIGHT} m up"
    return {
        "rotation": turn,
        "scale": scale,
        "lift": -scale * floor,
        "tilt": tilt,
        "source": source,
    }


def placed(place: dict[str, Any], point: Vector) -> Vector:
    x, y, z = rotate(place["rotation"], point)
    s = place["scale"]
    return (s * x, s * y + place["lift"], s * z)


def floor_extent(points: list[Vector]) -> tuple[float, float, float, float]:
    """The middle 90% of the room's visible splats across x and z, at least MIN_FLOOR wide."""
    near = [p for p in points if -0.3 < p[1] < 2.6]
    if len(near) < 20:
        raise SystemExit("The splat has too few visible splats near the floor.")

    def middle(items: list[float]) -> tuple[float, float]:
        items.sort()
        low, high = items[len(items) // 20], items[len(items) * 19 // 20]
        centre, half = (low + high) / 2, max(high - low, MIN_FLOOR) / 2
        return centre - half, centre + half

    (min_x, max_x), (min_z, max_z) = middle([p[0] for p in near]), middle([p[2] for p in near])
    return min_x, max_x, min_z, max_z


def box_place(
    cameras: list[dict], place: dict[str, Any], extent: tuple[float, float, float, float]
) -> tuple[float, float]:
    """1 m in front of the viewpoint filmed nearest the room origin, kept on the floor."""
    min_x, max_x, min_z, max_z = extent
    x, z = (min_x + max_x) / 2, (min_z + max_z) / 2
    if cameras:
        # The frame filmed nearest the walk's centre: alignment happens there, at the origin.
        camera = min(cameras, key=lambda c: math.hypot(*placed(place, tuple(c["position"]))[::2]))
        position = placed(place, tuple(camera["position"]))
        forward = rotate(place["rotation"], tuple(camera.get("forward", (0.0, 0.0, -1.0))))
        length = math.hypot(forward[0], forward[2]) or 1.0
        x, z = position[0] + forward[0] / length, position[2] + forward[2] / length
    margin = BOX_SIZE
    return min(max(x, min_x + margin), max_x - margin), min(max(z, min_z + margin), max_z - margin)


def write_room(out: Path, splat: Path, report: Path, room_version: int) -> None:
    out.mkdir(parents=True, exist_ok=True)
    if splat.resolve() != (out / "room.ply").resolve():
        shutil.copyfile(splat, out / "room.ply")
    cameras = []
    if report.is_file():
        cameras = json.loads(report.read_text(encoding="utf-8")).get("cameras", [])
        # Kept with the room: render-and-ask (#98) looks from where the video was filmed.
        if report.resolve() != (out / "report.json").resolve():
            shutil.copyfile(report, out / "report.json")
    place = placement(out / "room.ply", cameras)
    extent = floor_extent([placed(place, p) for p in visible_splats(out / "room.ply")])
    min_x, max_x, min_z, max_z = extent
    width, depth = max_x - min_x, max_z - min_z
    box_x, box_z = box_place(cameras, place, extent)
    write_floor(out, width, depth)
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
    splat_entry: dict[str, Any] = {"asset": "room.ply"}
    if place["rotation"] != IDENTITY or place["scale"] != 1.0 or place["lift"] != 0.0:
        splat_entry |= {
            "position": {"x": 0.0, "y": place["lift"], "z": 0.0},
            "rotation": dict(zip("xyzw", place["rotation"], strict=True)),
            "scale": place["scale"],
            "scale_source": place["source"],
        }
    manifest = {
        "schema_version": 2,
        "room_version": room_version,
        "units": "meters",
        "frame": "y_up_right_handed",
        "pivot": "bottom_center",
        "quaternion_order": "xyzw",
        "splat": splat_entry,
        "entities": [
            entity("floor", "Floor", "static", (width, FLOOR_HEIGHT, depth), centre),
            entity("box", "Box", "movable", (BOX_SIZE,) * 3, (box_x, 0.0, box_z)),
        ],
    }
    write_phone_splat(out / "room.ply", out / PHONE_FILE, PHONE_SPLATS)
    manifest["splat"]["phone_asset"] = PHONE_FILE
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    # The room seen from above, for both devices' map (#124). It needs the renderer (Node and a
    # built frontend), so a room is still written without it.
    try:
        make_map(out)
    except RenderFailure as exc:
        print(f"no map: {exc}")
    print(
        f"wrote {out}: levelled {place['tilt']:.1f} deg by the camera path, "
        f"scale x{place['scale']:.2f}, floor {width:.1f} x {depth:.1f} m, "
        f"box at ({box_x:.2f}, {box_z:.2f})"
    )


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


def write_floor(out: Path, width: float, depth: float) -> None:
    multi_asset.write_glb(
        out / "floor.glb",
        "floor",
        [multi_asset.part("floor_slab", (width, FLOOR_HEIGHT, depth), "#8d9399")],
    )


MIN_FACTOR, MAX_FACTOR = 0.2, 5.0
KEPT = "; kept by the master"


def keep_scale(room: Path) -> None:
    """Note that the master kept the room's scale as it is. Devices never see the note, so the
    room is not changed otherwise."""
    path = room / "manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    source = manifest["splat"].get("scale_source") or "not recorded"
    if not source.endswith(KEPT):
        manifest["splat"]["scale_source"] = source + KEPT
        path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


def rescale(room: Path, factor: float, source: str) -> None:
    """Make a built room `factor` times larger about its origin, and record where that came from.

    The splat and the floor grow; the floor stays at y = 0 and the box, a real-sized prop, keeps
    its size and moves out with the floor. The room version counts up so devices reload it.
    A factor outside MIN_FACTOR to MAX_FACTOR is refused: no correction we have seen comes close.
    """
    if not MIN_FACTOR <= factor <= MAX_FACTOR:
        raise ValueError(
            f"A scale factor of {factor} is not between {MIN_FACTOR} and {MAX_FACTOR}."
        )
    path = room / "manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    splat = manifest["splat"]
    if factor * splat.get("scale", 1.0) > 100:
        raise ValueError(f"A scale factor of {factor} would make the splat over 100 times larger.")
    position = splat.get("position", {"x": 0.0, "y": 0.0, "z": 0.0})
    splat["position"] = {axis: factor * value for axis, value in position.items()}
    splat.setdefault("rotation", dict(zip("xyzw", IDENTITY, strict=True)))
    splat["scale"] = factor * splat.get("scale", 1.0)
    splat["scale_source"] = source
    for entity in manifest["entities"]:
        at = entity["position"]
        entity["position"] = {"x": factor * at["x"], "y": at["y"], "z": factor * at["z"]}
        if entity["id"] == "floor":
            size = entity["size"]
            size["width"], size["depth"] = factor * size["width"], factor * size["depth"]
            write_floor(room, size["width"], size["depth"])
    manifest["room_version"] += 1
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"rescaled {room} by x{factor:.3f}: {source}")


def write_phone_splat(source: Path, out: Path, count: int) -> int:
    """The `count` splats of `source` that show most, with base colours only, as a PLY at `out`.

    A splat shows by how opaque it is and how much of the view it covers: its opacity after the
    sigmoid times its area face-on, the product of its two largest sizes. (By volume, a large
    see-through splat would outrank a small opaque one.) Returns how many were written.
    """
    names, values = read_splat(source)
    stride = len(names)
    columns = [names.index(name) for name in PHONE_PROPERTIES]
    opacity = names.index("opacity")
    scales = [names.index(f"scale_{axis}") for axis in range(3)]

    def visibility(start: int) -> float:
        opaque = 1 / (1 + math.exp(-values[start + opacity]))
        _, *largest = sorted(values[start + s] for s in scales)
        return opaque * math.exp(min(sum(largest), 50.0))

    starts = range(0, len(values), stride)
    kept = sorted(sorted(starts, key=visibility, reverse=True)[:count])
    header = ["ply", "format binary_little_endian 1.0", f"element vertex {len(kept)}"]
    header += [f"property float {name}" for name in PHONE_PROPERTIES] + ["end_header", ""]
    row = struct.Struct(f"<{len(columns)}f")
    rows = (row.pack(*(values[start + c] for c in columns)) for start in kept)
    out.write_bytes("\n".join(header).encode() + b"".join(rows))
    return len(kept)


def add_phone_splat(room: Path, count: int = PHONE_SPLATS) -> None:
    """Writes a built room's phone splat and names it in the manifest; devices reload the room."""
    path = room / "manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    written = write_phone_splat(room / manifest["splat"]["asset"], room / PHONE_FILE, count)
    manifest["splat"]["phone_asset"] = PHONE_FILE
    manifest["room_version"] += 1
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {room / PHONE_FILE}: {written} splats for phones")


def main() -> None:
    if len(sys.argv) == 1:
        write_test_splat(ROOT / "room.ply")
        write_room(ROOT, ROOT / "room.ply", ROOT / "report.json", room_version=1)
        return
    if len(sys.argv) == 5 and sys.argv[1] == "--rescale":
        rescale(Path(sys.argv[2]), float(sys.argv[3]), sys.argv[4])
        return
    if len(sys.argv) in (3, 4) and sys.argv[1] == "--phone":
        add_phone_splat(Path(sys.argv[2]), int(sys.argv[3]) if len(sys.argv) == 4 else PHONE_SPLATS)
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
