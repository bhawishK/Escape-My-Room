"""A picture of an object in the room, cut from the room's own splat (#223, part of #221).

The hazard's video starts from this picture (#222, #224), so its quality decides the hazard's.
Spike #220 found what works: render only the splats inside the object's box, on pure white,
which cuts the object out with no segmentation; look at the side of it people see, a little from
above; and drop the largest splats, the haze of stray streaks round it.

The side is the object's open side: the one with the most free floor in front of it, away from
walls and other furniture, preferring a long side. The camera may stand beyond the walls, since
only the object is drawn. Objects the video barely showed are refused with the reason, rather
than pictured badly.
"""

import io
import math
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image

from backend.prepared_room import FLOOR_THICKNESS, SceneEntity, floor_bounds, load_prepared_room
from backend.reconstruction.splat import read_ply, write_ply
from backend.room_views import View, render_views

PICTURE_SIDE = 768
# A little from above: level enough for the 4D step's multi-view model, high enough to show a
# bed's or a desk's top.
ELEVATION_DEGREES = 20.0
FOV_DEGREES = 40.0
# Room beyond the object's own size in the frame.
FRAMING = 1.1
# The box's margin round the object, and the floor kept out of the cut.
MARGIN_M = 0.06
ABOVE_FLOOR_M = 0.04
# A long side is worth this much extra free floor when choosing the side to look at.
LONG_SIDE_BONUS_M = 0.3
# The largest splats dropped as haze: the top 1%.
HAZE_PERCENTILE = 99.0
# Refusals.
MIN_SPLATS = 100
NEEDLE_RATIO = 10.0
MAX_NEEDLE_SHARE = 0.5
MIN_COVERAGE = 0.02
# Training packs splats onto what the video saw clearly. In room 10 the well-filmed bed was
# 12.9 times as dense as the room's average, and the barely filmed bed, desk and chair 0.2 to 0.8
# times, all streaks; an object must be at least this many times as dense to be pictured.
MIN_DENSITY_RATIO = 2.0
# The room's average density is taken over its floor up to this height.
ROOM_HEIGHT_M = 2.5


class PictureRefused(Exception):
    """The object can't be pictured well enough; the message says why, for the user."""


@dataclass(frozen=True)
class ObjectPicture:
    png: bytes
    view: View
    # Splats in the cut, after the haze is dropped.
    splats: int
    # How much of the picture the object covers.
    coverage: float


def _yaw(entity: SceneEntity) -> float:
    return 2 * math.atan2(entity.rotation.y, entity.rotation.w)


def _turn(yaw: float, x: float, z: float) -> tuple[float, float]:
    """A floor direction in an object's frame, turned into the room's, as three.js turns about y."""
    return x * math.cos(yaw) + z * math.sin(yaw), -x * math.sin(yaw) + z * math.cos(yaw)


def _hit(entity: SceneEntity, start: tuple[float, float], direction: tuple[float, float]) -> float:
    """How far along the ray its footprint starts, or infinity if it misses."""
    yaw = _yaw(entity)
    # The ray in the entity's own frame (turned back by its yaw), round its centre.
    sx, sz = start[0] - entity.position.x, start[1] - entity.position.z
    local_start = _turn(-yaw, sx, sz)
    local_dir = _turn(-yaw, *direction)
    near, far = 0.0, math.inf
    for axis, half in ((0, entity.size.width / 2), (1, entity.size.depth / 2)):
        d, s = local_dir[axis], local_start[axis]
        if abs(d) < 1e-9:
            if abs(s) > half:
                return math.inf
            continue
        t1, t2 = (-half - s) / d, (half - s) / d
        near, far = max(near, min(t1, t2)), min(far, max(t1, t2))
    return near if near <= far else math.inf


def open_side(entities: Sequence[SceneEntity], entity_id: str) -> tuple[float, float]:
    """The floor direction from the object to look at it from: the side with the most free floor
    in front of it, up to the floor's edge or the next piece, a long side counting a little more."""
    target = next(entity for entity in entities if entity.id == entity_id)
    yaw = _yaw(target)
    bounds = floor_bounds(list(entities))
    others = [
        entity
        for entity in entities
        if entity.id != entity_id and entity.size.height > FLOOR_THICKNESS
    ]
    long_along_x = target.size.width >= target.size.depth
    best: tuple[float, tuple[float, float]] | None = None
    for local, half, long_side in (
        ((0.0, 1.0), target.size.depth / 2, long_along_x),
        ((0.0, -1.0), target.size.depth / 2, long_along_x),
        ((1.0, 0.0), target.size.width / 2, not long_along_x),
        ((-1.0, 0.0), target.size.width / 2, not long_along_x),
    ):
        direction = _turn(yaw, *local)
        start = (target.position.x + direction[0] * half, target.position.z + direction[1] * half)
        free = 5.0
        if bounds is not None:
            min_x, max_x, min_z, max_z = bounds
            for value, low, high, d in (
                (start[0], min_x, max_x, direction[0]),
                (start[1], min_z, max_z, direction[1]),
            ):
                if d > 1e-9:
                    free = min(free, (high - value) / d)
                elif d < -1e-9:
                    free = min(free, (low - value) / d)
        for other in others:
            free = min(free, _hit(other, start, direction))
        score = max(free, 0.0) + (LONG_SIDE_BONUS_M if long_side else 0.0)
        if best is None or score > best[0] + 1e-9:
            best = (score, (round(direction[0], 9) + 0.0, round(direction[1], 9) + 0.0))
    assert best is not None
    return best[1]


def object_view(entity: SceneEntity, direction: tuple[float, float]) -> View:
    """Looking at the object's middle from `direction`, a little from above, framing all of it."""
    size, position = entity.size, entity.position
    centre = (position.x, position.y + size.height / 2, position.z)
    radius = 0.5 * math.sqrt(size.width**2 + size.height**2 + size.depth**2)
    distance = FRAMING * radius / math.sin(math.radians(FOV_DEGREES / 2))
    up = math.radians(ELEVATION_DEGREES)
    eye = (
        centre[0] + direction[0] * math.cos(up) * distance,
        centre[1] + math.sin(up) * distance,
        centre[2] + direction[1] * math.cos(up) * distance,
    )
    return View(
        position=eye,
        look_at=centre,
        fov_degrees=FOV_DEGREES,
        width=PICTURE_SIDE,
        height=PICTURE_SIDE,
        background="#ffffff",
    )


def _quaternion_matrix(x: float, y: float, z: float, w: float) -> np.ndarray:
    return np.array(
        [
            [1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y)],
            [2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)],
            [2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)],
        ]
    )


def _density_ratio(
    points: np.ndarray, inside: np.ndarray, target: SceneEntity, entities: Sequence[SceneEntity]
) -> float:
    """How many times as dense in splats the object's box is as the room on average."""
    size = target.size
    box = (
        (size.width + 2 * MARGIN_M)
        * (size.depth + 2 * MARGIN_M)
        * (size.height + MARGIN_M - ABOVE_FLOOR_M)
    )
    bounds = floor_bounds(list(entities))
    if bounds is None:
        return math.inf
    min_x, max_x, min_z, max_z = bounds
    in_room = (
        (points[:, 0] >= min_x)
        & (points[:, 0] <= max_x)
        & (points[:, 2] >= min_z)
        & (points[:, 2] <= max_z)
        & (points[:, 1] >= 0)
        & (points[:, 1] <= ROOM_HEIGHT_M)
    )
    average = in_room.sum() / ((max_x - min_x) * (max_z - min_z) * ROOM_HEIGHT_M)
    return math.inf if average <= 0 else float(inside.sum() / box / average)


def object_picture(
    room_dir: Path, entities: Sequence[SceneEntity], entity_id: str
) -> ObjectPicture:
    """The object's picture on white, or PictureRefused with the reason."""
    target = next((entity for entity in entities if entity.id == entity_id), None)
    if target is None:
        raise PictureRefused(f"There's no {entity_id} in the room.")
    room = load_prepared_room(room_dir)
    placement = room.splat_placement
    if room.splat_url is None or placement is None:
        raise PictureRefused("This room has no splat to cut the object from.")
    splat = read_ply(room_dir / room.splat_url.rsplit("/", 1)[-1])
    q = placement.rotation
    rotation = _quaternion_matrix(q.x, q.y, q.z, q.w)
    offset = np.array([placement.position.x, placement.position.y, placement.position.z])
    points = (splat["means"] * placement.scale) @ rotation.T + offset

    # Inside the object's box, turned with it, above the floor.
    yaw = _yaw(target)
    dx, dz = points[:, 0] - target.position.x, points[:, 2] - target.position.z
    local_x = dx * math.cos(-yaw) + dz * math.sin(-yaw)
    local_z = -dx * math.sin(-yaw) + dz * math.cos(-yaw)
    size = target.size
    inside = (
        (np.abs(local_x) < size.width / 2 + MARGIN_M)
        & (np.abs(local_z) < size.depth / 2 + MARGIN_M)
        & (points[:, 1] > target.position.y + ABOVE_FLOOR_M)
        & (points[:, 1] < target.position.y + size.height + MARGIN_M)
    )
    extents = np.exp(splat["scales"])
    if inside.sum() > 0:
        longest = extents.max(axis=1)
        inside &= longest <= np.percentile(longest[inside], HAZE_PERCENTILE)
    label = target.label.lower()
    count = int(inside.sum())
    if count < MIN_SPLATS or _density_ratio(points, inside, target, entities) < MIN_DENSITY_RATIO:
        raise PictureRefused(
            f"Too little of the room's video shows the {label}, so it can't be pictured well. "
            "Film it again with the coach, closer and from its open side."
        )
    ordered = np.sort(extents[inside], axis=1)
    needles = float((ordered[:, 2] / np.maximum(ordered[:, 1], 1e-9) > NEEDLE_RATIO).mean())
    if needles > MAX_NEEDLE_SHARE:
        raise PictureRefused(
            f"The {label} is mostly streaks in the room's splat, so it can't be pictured well. "
            "Film it again with the coach."
        )

    view = object_view(target, open_side(entities, entity_id))
    with tempfile.TemporaryDirectory(prefix="object-picture-") as folder:
        cut = Path(folder) / "object.ply"
        write_ply(
            cut,
            *(
                splat[key][inside]
                for key in ("means", "scales", "quats", "opacities", "sh0", "shN")
            ),
        )
        [rendered] = render_views(room_dir, [view], splat=cut)
    image = np.asarray(Image.open(io.BytesIO(rendered.png)).convert("RGB"))
    coverage = float((image < 245).any(axis=2).mean())
    if coverage < MIN_COVERAGE:
        raise PictureRefused(
            f"The {label} barely shows in the room's splat, so it can't be pictured well. "
            "Film it again with the coach."
        )
    out = io.BytesIO()
    Image.fromarray(image).save(out, format="PNG")
    return ObjectPicture(png=out.getvalue(), view=view, splats=count, coverage=round(coverage, 4))
