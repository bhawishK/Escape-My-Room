"""Load the prepared room manifest and reject assets that do not match it.

Two manifest forms are accepted. The original stand-in room names one .gltf for every entity and
has exactly one movable entity. Schema 2 gives each entity its own .glb, a rotation, and any number
of movable entities. Both become the same shared entity records. Either form may list the printed
tracking markers the phone camera locates itself against.

Frame for both: meters, right-handed, +Y up, +Z toward the viewer. An entity's position and
rotation place the center of its bottom face in the room. Rotations are unit quaternions in
(x, y, z, w) order. The referenced node's own transform and its ancestors' transforms are
placement, which the manifest owns; descendant transforms are part of the asset.
"""

import json
import math
from collections.abc import Sequence
from pathlib import Path
from typing import Literal, Protocol, Self

from pydantic import BaseModel, Field, ValidationError, model_validator

from backend.gltf import IDENTITY, AssetError, GltfDocument, read_asset
from backend.protocol import Position, WireModel

UNITS = "meters"
FRAME = "y_up_right_handed"
PIVOT = "bottom_center"
QUATERNION_ORDER = "xyzw"
ASSET_URL_PREFIX = "/assets/prepared-room"
ENTITY_ID = r"^[a-z][a-z0-9_]{0,31}$"
BOUNDS_TOLERANCE = 1e-4


class PreparedRoomError(Exception):
    """The prepared room cannot be served consistently."""


class EntitySize(WireModel):
    width: float = Field(gt=0, le=100)
    height: float = Field(gt=0, le=100)
    depth: float = Field(gt=0, le=100)


class Rotation(WireModel):
    """A unit quaternion in (x, y, z, w) order, normalized on load."""

    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    w: float = 1.0

    @model_validator(mode="after")
    def normalize(self) -> Self:
        norm = math.sqrt(self.x**2 + self.y**2 + self.z**2 + self.w**2)
        if abs(norm - 1) > 1e-3:
            raise ValueError("Rotation must be a unit quaternion")
        self.x, self.y, self.z, self.w = (
            self.x / norm,
            self.y / norm,
            self.z / norm,
            self.w / norm,
        )
        return self


class SceneEntity(WireModel):
    """One room object as both clients receive it."""

    id: str = Field(pattern=ENTITY_ID)
    label: str
    asset_url: str
    node: str
    kind: Literal["static", "movable"]
    selectable: bool
    size: EntitySize
    position: Position
    rotation: Rotation


class TrackingMarker(WireModel):
    """A printed AprilTag (36h11) fixed in the room, which the phone camera measures itself against.

    The position is the center of the tag's black square. In the tag's own frame +X points to the
    right of the printed tag, +Y to its top, and +Z out of the printed face; the rotation turns that
    frame into the room. Size is the edge of the black square.
    """

    id: int = Field(ge=0, le=586)
    label: str = Field(min_length=1, max_length=64)
    size: float = Field(gt=0, le=1)
    position: Position
    rotation: Rotation


class _MarkedManifest(WireModel):
    """The tracking markers either manifest form may list."""

    markers: list[TrackingMarker] = Field(
        default_factory=lambda: list[TrackingMarker](), max_length=32
    )

    @model_validator(mode="after")
    def check_markers(self) -> Self:
        if len({marker.id for marker in self.markers}) != len(self.markers):
            raise ValueError("Tracking marker IDs must be unique")
        return self


class LoadedRoom(BaseModel):
    room_version: int
    entities: list[SceneEntity]
    markers: list[TrackingMarker]


class _Entity(Protocol):
    @property
    def id(self) -> str: ...
    @property
    def kind(self) -> Literal["static", "movable"]: ...
    @property
    def selectable(self) -> bool: ...


def _check_interaction_flags(entities: Sequence[_Entity]) -> None:
    if len({entity.id for entity in entities}) != len(entities):
        raise ValueError("Entity IDs must be unique")
    for entity in entities:
        if entity.kind == "static" and entity.selectable:
            raise ValueError(f"{entity.id} is static and cannot be selectable")
        if entity.kind == "movable" and not entity.selectable:
            raise ValueError(f"{entity.id} is movable and must be selectable")


class RoomEntity(WireModel):
    id: str = Field(pattern=ENTITY_ID)
    node: str = Field(pattern=r"^[A-Za-z0-9._-]{1,64}$")
    kind: Literal["static", "movable"]
    selectable: bool
    color: str = Field(pattern=r"^#[0-9a-fA-F]{6}$")
    size: EntitySize
    position: Position


class PreparedRoom(_MarkedManifest):
    """The original single-glTF stand-in room."""

    room_version: int = Field(ge=1)
    units: str = Field(pattern=r"^meters$")
    asset: str = Field(pattern=r"^[A-Za-z0-9._-]+\.gltf$")
    entities: list[RoomEntity] = Field(min_length=1)

    @model_validator(mode="after")
    def check_entities(self) -> Self:
        _check_interaction_flags(self.entities)
        if len({entity.node for entity in self.entities}) != len(self.entities):
            raise ValueError("Entity nodes must be unique")
        movable = [entity for entity in self.entities if entity.kind == "movable"]
        if len(movable) != 1:
            raise ValueError("The room needs exactly one movable entity")
        return self


class AssetEntity(WireModel):
    id: str = Field(pattern=ENTITY_ID)
    label: str = Field(min_length=1, max_length=64)
    asset: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}\.glb$")
    # Three.js strips "." and other reserved characters from node names, so they are not allowed.
    node: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    kind: Literal["static", "movable"]
    selectable: bool
    size: EntitySize
    position: Position
    rotation: Rotation


class PreparedScene(_MarkedManifest):
    """Schema 2: one GLB per entity and any number of movable entities."""

    schema_version: Literal[2]
    room_version: int = Field(ge=1)
    units: Literal["meters"]
    frame: Literal["y_up_right_handed"]
    pivot: Literal["bottom_center"]
    quaternion_order: Literal["xyzw"]
    entities: list[AssetEntity] = Field(min_length=1, max_length=64)

    @model_validator(mode="after")
    def check_entities(self) -> Self:
        _check_interaction_flags(self.entities)
        if len({(entity.asset, entity.node) for entity in self.entities}) != len(self.entities):
            raise ValueError("Entity asset nodes must be unique")
        return self


def load_prepared_room(directory: Path) -> LoadedRoom:
    manifest_path = directory / "manifest.json"
    if not manifest_path.is_file():
        raise PreparedRoomError("Prepared room manifest is missing.")
    try:
        text = manifest_path.read_text(encoding="utf-8")
        if "schema_version" in json.loads(text):
            scene: PreparedScene | PreparedRoom = PreparedScene.model_validate_json(text)
        else:
            scene = PreparedRoom.model_validate_json(text)
    except (OSError, UnicodeError, ValidationError, ValueError, TypeError) as exc:
        raise PreparedRoomError("Prepared room manifest is invalid.") from exc
    try:
        if isinstance(scene, PreparedScene):
            return _load_scene(directory, scene)
        return _load_legacy(directory, scene)
    except AssetError as exc:
        raise PreparedRoomError(str(exc)) from exc


def _load_legacy(directory: Path, room: PreparedRoom) -> LoadedRoom:
    asset = _read(directory, room.asset)
    nodes: dict[str, int] = {}
    used_meshes: set[object] = set()
    for entity in room.entities:
        index = asset.find_node(entity.node)
        if index is None or "mesh" not in asset.nodes[index]:
            raise PreparedRoomError(f"Prepared room model is missing {entity.id}.")
        mesh = asset.nodes[index]["mesh"]
        if mesh in used_meshes:
            raise PreparedRoomError(
                f"Prepared room model does not keep {entity.id} as its own mesh."
            )
        used_meshes.add(mesh)
        # This form's node translation duplicates the manifest position; it has no rotation.
        position = (entity.position.x, entity.position.y, entity.position.z)
        placement = (*IDENTITY[:12], *position, 1.0)
        matrix = asset.local_matrix(index)
        moved = any(asset.has_transform(ancestor) for ancestor in asset.ancestors(index))
        if moved or any(abs(a - b) > 1e-5 for a, b in zip(matrix, placement, strict=True)):
            raise PreparedRoomError(
                f"Prepared room node {entity.node} does not match the manifest position."
            )
        nodes[entity.id] = index
    _check_nodes(asset, nodes, {entity.id: entity.size for entity in room.entities})
    url = f"{ASSET_URL_PREFIX}/{room.asset}"
    return LoadedRoom(
        room_version=room.room_version,
        entities=[
            SceneEntity(
                id=entity.id,
                label=entity.id,
                asset_url=url,
                node=entity.node,
                kind=entity.kind,
                selectable=entity.selectable,
                size=entity.size,
                position=entity.position,
                rotation=Rotation(),
            )
            for entity in room.entities
        ],
        markers=room.markers,
    )


def _load_scene(directory: Path, scene: PreparedScene) -> LoadedRoom:
    for name in dict.fromkeys(entity.asset for entity in scene.entities):
        asset = _read(directory, name)
        entities = [entity for entity in scene.entities if entity.asset == name]
        nodes: dict[str, int] = {}
        for entity in entities:
            index = asset.find_node(entity.node)
            if index is None:
                raise PreparedRoomError(f"Prepared room asset {name} is missing {entity.id}.")
            if any(asset.has_transform(node) for node in (index, *asset.ancestors(index))):
                raise PreparedRoomError(
                    f"Prepared room node {entity.node} in {name} is transformed; "
                    "the manifest alone places entities."
                )
            nodes[entity.id] = index
        _check_nodes(asset, nodes, {entity.id: entity.size for entity in entities})
    return LoadedRoom(
        room_version=scene.room_version,
        entities=[
            SceneEntity(
                id=entity.id,
                label=entity.label,
                asset_url=f"{ASSET_URL_PREFIX}/{entity.asset}",
                node=entity.node,
                kind=entity.kind,
                selectable=entity.selectable,
                size=entity.size,
                position=entity.position,
                rotation=entity.rotation,
            )
            for entity in scene.entities
        ],
        markers=scene.markers,
    )


def _read(directory: Path, name: str) -> GltfDocument:
    path = (directory / name).resolve()
    if path.parent != directory.resolve():
        raise AssetError(f"Prepared room asset {name} is missing.")
    return read_asset(path)


def _check_nodes(asset: GltfDocument, nodes: dict[str, int], sizes: dict[str, EntitySize]) -> None:
    """Each entity's subtree is separate, has geometry, and matches its size and pivot."""
    owners = {index: entity_id for entity_id, index in nodes.items()}
    for entity_id, index in nodes.items():
        for ancestor in asset.ancestors(index):
            if ancestor in owners:
                raise PreparedRoomError(
                    f"Prepared room {entity_id} is nested inside {owners[ancestor]}."
                )
        bounds = asset.local_bounds(index)
        if bounds is None:
            raise PreparedRoomError(f"Prepared room {entity_id} has no geometry.")
        size = sizes[entity_id]
        expected = (
            (-size.width / 2, 0.0, -size.depth / 2),
            (size.width / 2, size.height, size.depth / 2),
        )
        for actual_corner, expected_corner in zip(bounds, expected, strict=True):
            if any(
                abs(a - b) > BOUNDS_TOLERANCE
                for a, b in zip(actual_corner, expected_corner, strict=True)
            ):
                raise PreparedRoomError(
                    f"Prepared room {entity_id} geometry does not match its size "
                    "with a bottom-center pivot."
                )
