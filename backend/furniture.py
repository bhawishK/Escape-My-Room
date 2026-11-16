"""Furniture the designer places in the room (#181): the built-in catalogue, and placed pieces.

The catalogue is `assets/furniture/catalogue.json`, written with its models by
`assets/furniture/build_furniture.py`. A placed piece is an ordinary movable room entity, so
selection, holding, carrying and physics treat it as they treat the box.
"""

import json
import math
import threading
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


def on_floor(
    entities: list[SceneEntity], position: Position, size: EntitySize, yaw: float
) -> Position | None:
    """Where a piece asked for at `position` starts: no lower than the floor's top. None when
    any of it would be off the floor. A room without a floor takes any place."""
    bounds = floor_bounds(entities)
    if bounds is not None:
        min_x, max_x, min_z, max_z = bounds
        if not all(
            min_x <= x <= max_x and min_z <= z <= max_z for x, z in footprint(position, size, yaw)
        ):
            return None
    top = floor_top(entities)
    y = position.y if top is None else max(position.y, top)
    return Position(x=position.x, y=y, z=position.z)
