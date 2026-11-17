"""Furniture the designer places in the room (#181): the built-in catalogue, and placed pieces.

The catalogue is `assets/furniture/catalogue.json`, written with its models by
`assets/furniture/build_furniture.py`. A placed piece is an ordinary movable room entity, so
selection, holding, carrying and physics treat it as they treat the box.
"""

import json
import math
import threading
from dataclasses import dataclass
from pathlib import Path

from pydantic import Field

from backend.prepared_room import EntitySize, Rotation, SceneEntity, floor_bounds, floor_top
from backend.protocol import Position, WireModel

FURNITURE_DIR = Path(__file__).resolve().parents[1] / "assets" / "furniture"
# Where the models are served; the glTF names its .bin beside it.
MODELS_URL = "/api/furniture"
# The files that may be served from the furniture folder.
MODEL_SUFFIXES = {".gltf", ".bin"}


class CatalogueItem(WireModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9_]{0,31}$")
    name: str
    # The node in the model to draw for this piece.
    node: str
    size: EntitySize
    model_url: str
    # Made from a description (#186), rather than built in.
    generated: bool = False


class Catalogue:
    """The built-in pieces. One that can't be read is empty and says why, and the room works on
    without furniture."""

    def __init__(self, directory: Path = FURNITURE_DIR) -> None:
        self.directory = directory
        self.items: dict[str, CatalogueItem] = {}
        self.error: str | None = None
        # Generated pieces (#186) are added from a worker thread while requests list them.
        self.lock = threading.Lock()
        try:
            data = json.loads((directory / "catalogue.json").read_text(encoding="utf-8"))
            model_url = f"{MODELS_URL}/{data['asset']}"
            self.items = {
                item["id"]: CatalogueItem.model_validate(item | {"model_url": model_url})
                for item in data["items"]
            }
        except (OSError, ValueError, KeyError, TypeError) as exc:
            self.error = f"The furniture catalogue could not be read: {exc}"

    def add(self, item: CatalogueItem) -> None:
        with self.lock:
            self.items[item.id] = item

    def get(self, item_id: str) -> CatalogueItem | None:
        with self.lock:
            return self.items.get(item_id)

    def listed(self) -> list[CatalogueItem]:
        with self.lock:
            return list(self.items.values())

    def file(self, name: str) -> Path | None:
        """A model file to serve, or None for anything else."""
        path = (self.directory / name).resolve()
        if path.parent != self.directory.resolve() or path.suffix not in MODEL_SUFFIXES:
            return None
        return path if path.is_file() else None


def yaw_rotation(yaw: float) -> Rotation:
    """A turn of `yaw` radians about the vertical, positive to the left."""
    return Rotation(x=0.0, y=math.sin(yaw / 2), z=0.0, w=math.cos(yaw / 2))


def furniture_entity(
    entity_id: str, item: CatalogueItem, position: Position, yaw: float
) -> SceneEntity:
    return SceneEntity(
        id=entity_id,
        label=item.name,
        asset_url=item.model_url,
        node=item.node,
        kind="movable",
        selectable=True,
        size=item.size,
        position=position,
        rotation=yaw_rotation(yaw),
        furniture=item.id,
    )


def footprint(position: Position, size: EntitySize, yaw: float) -> list[tuple[float, float]]:
    """The (x, z) corners of a piece standing at `position`, turned `yaw` to the left."""
    cosine, sine = math.cos(yaw), math.sin(yaw)
    half_w, half_d = size.width / 2, size.depth / 2
    return [
        (position.x + cosine * x + sine * z, position.z - sine * x + cosine * z)
        for x, z in ((-half_w, -half_d), (half_w, -half_d), (half_w, half_d), (-half_w, half_d))
    ]


# Pieces no taller than this, such as rugs, are stood on: other pieces may overlap them.
FLAT_METRES = 0.05
# Where a piece that would overlap another is looked for: rings this far apart, out to this far.
SEARCH_STEP_METRES = 0.1
SEARCH_METRES = 3.0
# Overlaps smaller than this, in metres, are touching.
TOUCHING_METRES = 0.01
# A piece whose rotation tips it further than this from upright is lying over.
UPRIGHT = 0.05


@dataclass(frozen=True)
class Shape:
    """Where a piece takes up room: a turned rectangle across the floor, and a range of heights.
    `axes` are its two directions across the floor, `half` its half-lengths along them."""

    centre: tuple[float, float]
    axes: tuple[tuple[float, float], tuple[float, float]]
    half: tuple[float, float]
    low: float
    high: float


def shape_of(position: Position, size: EntitySize, rotation: Rotation) -> Shape:
    """The room a piece standing at `position` takes up. One turned only about the vertical is
    its footprint; one tumbled over takes up its whole extent every way, which is generous."""
    if abs(rotation.x) > UPRIGHT or abs(rotation.z) > UPRIGHT:
        reach = math.hypot(size.width, size.height, size.depth) / 2
        middle = position.y + size.height / 2
        return Shape(
            (position.x, position.z),
            ((1.0, 0.0), (0.0, 1.0)),
            (reach, reach),
            middle - reach,
            middle + reach,
        )
    yaw = 2 * math.atan2(rotation.y, rotation.w)
    cosine, sine = math.cos(yaw), math.sin(yaw)
    # The piece's own x and z directions, turned as three.js turns rotation.y.
    return Shape(
        (position.x, position.z),
        ((cosine, -sine), (sine, cosine)),
        (size.width / 2, size.depth / 2),
        position.y,
        position.y + size.height,
    )


def _reach(shape: Shape, axis: tuple[float, float]) -> float:
    """How far the shape reaches from its centre along `axis`."""
    return sum(
        half * abs(direction[0] * axis[0] + direction[1] * axis[1])
        for half, direction in zip(shape.half, shape.axes, strict=True)
    )


def overlap(a: Shape, b: Shape) -> bool:
    """Whether two shapes overlap by more than touching: in height, and across the floor, where
    turned rectangles overlap unless some edge direction separates them."""
    if a.high <= b.low + TOUCHING_METRES or b.high <= a.low + TOUCHING_METRES:
        return False
    gap = (b.centre[0] - a.centre[0], b.centre[1] - a.centre[1])
    for axis in (*a.axes, *b.axes):
        apart = abs(gap[0] * axis[0] + gap[1] * axis[1])
        if apart >= _reach(a, axis) + _reach(b, axis) - TOUCHING_METRES:
            return False
    return True


def _obstacles(entity: SceneEntity, others: list[SceneEntity]) -> list[Shape]:
    """The shapes the entity must keep clear of: every other movable piece that isn't flat."""
    return [
        shape_of(other.position, other.size, other.rotation)
        for other in others
        if other.id != entity.id and other.kind == "movable" and other.size.height > FLAT_METRES
    ]


def overlapping(entity: SceneEntity, position: Position, others: list[SceneEntity]) -> bool:
    """Whether the entity at `position` would overlap another piece (#183). Flat pieces never
    count, and nor do the room's own static objects or the entity itself."""
    if entity.size.height <= FLAT_METRES:
        return False
    mine = shape_of(position, entity.size, entity.rotation)
    return any(overlap(mine, shape) for shape in _obstacles(entity, others))


def inside_floor(
    bounds: tuple[float, float, float, float] | None,
    position: Position,
    size: EntitySize,
    yaw: float,
) -> bool:
    """Whether all of a piece's turned footprint is on the floor; any place without a floor."""
    if bounds is None:
        return True
    min_x, max_x, min_z, max_z = bounds
    return all(
        min_x <= x <= max_x and min_z <= z <= max_z for x, z in footprint(position, size, yaw)
    )


def free_spot(
    entity: SceneEntity, position: Position, entities: list[SceneEntity]
) -> Position | None:
    """Where the entity can stand near `position` without overlapping another piece (#183):
    there if it can, else the nearest place on the floor found ring by ring. None if nowhere."""
    yaw = 2 * math.atan2(entity.rotation.y, entity.rotation.w)
    bounds = floor_bounds(entities)
    obstacles = [] if entity.size.height <= FLAT_METRES else _obstacles(entity, entities)

    def fits(x: float, z: float) -> bool:
        spot = Position(x=x, y=position.y, z=z)
        if not inside_floor(bounds, spot, entity.size, yaw):
            return False
        mine = shape_of(spot, entity.size, entity.rotation)
        return not any(overlap(mine, shape) for shape in obstacles)

    if fits(position.x, position.z):
        return position
    rings = round(SEARCH_METRES / SEARCH_STEP_METRES)
    for ring in range(1, rings + 1):
        radius = ring * SEARCH_STEP_METRES
        steps = max(8, round(2 * math.pi * radius / SEARCH_STEP_METRES))
        for step in range(steps):
            angle = 2 * math.pi * step / steps
            x, z = position.x + radius * math.cos(angle), position.z + radius * math.sin(angle)
            if fits(x, z):
                return Position(x=x, y=position.y, z=z)
    return None


def on_floor(
    entities: list[SceneEntity], position: Position, size: EntitySize, yaw: float
) -> Position | None:
    """Where a piece asked for at `position` starts: no lower than the floor's top. None when
    any of it would be off the floor. A room without a floor takes any place."""
    if not inside_floor(floor_bounds(entities), position, size, yaw):
        return None
    top = floor_top(entities)
    y = position.y if top is None else max(position.y, top)
    return Position(x=position.x, y=y, z=position.z)
