"""A 2D map of a prepared room (#124): its splat seen from straight above, cut at waist height.

    python -m backend.room_map ROOM_DIR

Writes `map.png` and `map.json` (the image and the floor area it shows, in room metres) into the
room, which Python serves with it. Both devices draw the map with the room's objects as icons and
the players as dots. The image is rendered from high above with a narrow view, so it is all but
flat. Its top is the room's -z and its right +x.

From above, a whole splat shows its ceiling and the large, stretched splats that float away from
where it was filmed (the hallway's map was unreadable). So, as a floor plan is drawn, the map keeps
only splats from just under the floor to waist height, and none larger than SPLAT_MAX; and it
covers where the room's splats are, not the floor entity, which is sized to every stray splat.
"""

import json
import math
import sys
import tempfile
from array import array
from pathlib import Path

from backend.prepared_room import MAP_FILE, SplatPlacement, load_prepared_room
from backend.room_views import View, in_room, render_views
from backend.splat_file import read_splat

MAP_IMAGE = "map.png"
LONG_SIDE = 512
# How high above the floor the map is drawn from, in metres.
ABOVE = 40.0
# The plan is cut at waist height: only splats from just under the floor to here are drawn.
BELOW_FLOOR = -0.2
CUT_HEIGHT = 1.2
# Splats larger than this, in metres, are streaks and floaters, not the room.
SPLAT_MAX = 0.15
# The map covers the middle of the kept splats, without the outer KEEP_OUT at each end, plus MARGIN.
KEEP_OUT = 0.02
MARGIN = 0.5


def make_map(room_dir: Path) -> dict[str, object]:
    """Renders the room's map and writes it with its bounds; returns the bounds."""
    room = load_prepared_room(room_dir)
    if room.splat_url is None or room.splat_placement is None:
        raise ValueError("The room has no splat to draw a map from.")
    name = room.splat_url.rsplit("/", 1)[-1]
    names, values = read_splat(room_dir / name)
    kept, xs, zs = _plan_splats(names, values, room.splat_placement)
    if len(xs) < 20:
        raise ValueError("Too few splats near the floor to draw a map.")
    # Where the room is: the middle of its splats, with the origin and its objects on the map too.
    spots_x = [*_middle(xs), 0.0, *(mark.x for mark in room.landmarks)]
    spots_z = [*_middle(zs), 0.0, *(mark.z for mark in room.landmarks)]
    min_x, max_x = min(spots_x) - MARGIN, max(spots_x) + MARGIN
    min_z, max_z = min(spots_z) - MARGIN, max(spots_z) + MARGIN
    wide, deep = max_x - min_x, max_z - min_z
    scale = LONG_SIDE / max(wide, deep)
    middle = ((min_x + max_x) / 2, (min_z + max_z) / 2)
    view = View(
        position=(middle[0], ABOVE, middle[1]),
        look_at=(middle[0], 0.0, middle[1]),
        fov_degrees=math.degrees(2 * math.atan(deep / 2 / ABOVE)),
        width=max(1, round(wide * scale)),
        height=max(1, round(deep * scale)),
    )
    with tempfile.TemporaryDirectory(prefix="room-map-") as cut:
        [shot] = render_views(_plan_room(room_dir, Path(cut), name, names, kept), [view])
    (room_dir / MAP_IMAGE).write_bytes(shot.png)
    bounds: dict[str, object] = {
        "image": MAP_IMAGE,
        "min_x": round(min_x, 3),
        "max_x": round(max_x, 3),
        "min_z": round(min_z, 3),
        "max_z": round(max_z, 3),
    }
    (room_dir / MAP_FILE).write_text(json.dumps(bounds, indent=2) + "\n", encoding="utf-8")
    return bounds


def _plan_splats(
    names: list[str], values: array[float], placement: SplatPlacement
) -> tuple[bytes, list[float], list[float]]:
    """The splats a floor plan draws, as PLY rows, and their places on the floor."""
    stride = len(names)
    x, y, z = (names.index(axis) for axis in "xyz")
    scales = [names.index(f"scale_{axis}") for axis in range(3)]
    rows: list[bytes] = []
    xs: list[float] = []
    zs: list[float] = []
    for start in range(0, len(values), stride):
        size = math.exp(max(values[start + s] for s in scales)) * placement.scale
        if size > SPLAT_MAX:
            continue
        at = in_room(placement, (values[start + x], values[start + y], values[start + z]))
        if not BELOW_FLOOR <= at[1] <= CUT_HEIGHT:
            continue
        rows.append(values[start : start + stride].tobytes())
        xs.append(at[0])
        zs.append(at[2])
    return b"".join(rows), xs, zs


def _middle(values: list[float]) -> tuple[float, float]:
    """The lowest and highest of the values, without the outer KEEP_OUT at each end."""
    ordered = sorted(values)
    cut = int(len(ordered) * KEEP_OUT)
    return ordered[cut], ordered[-1 - cut]


def _plan_room(room_dir: Path, out: Path, name: str, names: list[str], rows: bytes) -> Path:
    """A copy of the room whose splat holds only the plan's splats, to render the map from."""
    count = len(rows) // (4 * len(names))
    header = ["ply", "format binary_little_endian 1.0", f"element vertex {count}"]
    header += [f"property float {column}" for column in names] + ["end_header", ""]
    (out / name).write_bytes("\n".join(header).encode() + rows)
    manifest = json.loads((room_dir / "manifest.json").read_text(encoding="utf-8"))
    # Only the splat is drawn; the rest of the room is not needed to render it.
    manifest["splat"].pop("phone_asset", None)
    (out / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    for entity in manifest["entities"]:
        source = room_dir / entity["asset"]
        if source.is_file() and not (out / entity["asset"]).exists():
            (out / entity["asset"]).write_bytes(source.read_bytes())
    return out


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(2)
    print(json.dumps(make_map(Path(sys.argv[1]))))
