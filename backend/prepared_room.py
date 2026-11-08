"""Load the prepared room manifest and reject assets that do not match it.

Two manifest forms are accepted. The original stand-in room names one .gltf for every entity and
has exactly one movable entity. Schema 2 gives each entity its own .glb, a rotation, and any number
of movable entities. Both become the same shared entity records.

A schema 2 room may also name a Gaussian splat (.ply or .spz) in the same frame. Devices then draw
the splat as the room's look, while the entities keep their roles: static ones bound walking and
hide what is behind them, movable ones are drawn and can be picked up.

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
# Static entities this thin are floor, as the phone's walking treats them (frontend/src/steps.ts).
FLOOR_THICKNESS = 0.05
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


class PhysicsMaterial(WireModel):
    """What a movable object is made of, for physics (#161). Missing values use the defaults."""

    mass: float | None = Field(default=None, gt=0, le=1000)  # kilograms
    friction: float | None = Field(default=None, ge=0, le=2)
    restitution: float | None = Field(default=None, ge=0, le=1)  # 0 thuds, 1 bounces back


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
    physics: PhysicsMaterial | None = None


def floor_top(entities: list[SceneEntity]) -> float | None:
    """The height of the floor's top surface, or None for a room without a floor."""
    tops = [
        entity.position.y + entity.size.height
        for entity in entities
        if entity.kind == "static" and entity.size.height <= FLOOR_THICKNESS
    ]
    return max(tops) if tops else None


def floor_bounds(entities: list[SceneEntity]) -> tuple[float, float, float, float] | None:
    """The floor's extent as (min x, max x, min z, max z), around each floor piece's corners."""
    xs: list[float] = []
    zs: list[float] = []
    for entity in entities:
        if entity.kind != "static" or entity.size.height > FLOOR_THICKNESS:
            continue
        q, half_w, half_d = entity.rotation, entity.size.width / 2, entity.size.depth / 2
        for x, z in ((-half_w, -half_d), (half_w, -half_d), (half_w, half_d), (-half_w, half_d)):
            # v' = v + 2w(u × v) + 2u × (u × v), with v = (x, 0, z).
            tx, ty, tz = 2 * q.y * z, 2 * (q.z * x - q.x * z), -2 * q.y * x
            xs.append(entity.position.x + x + q.w * tx + (q.y * tz - q.z * ty))
            zs.append(entity.position.z + z + q.w * tz + (q.x * ty - q.y * tx))
    return (min(xs), max(xs), min(zs), max(zs)) if xs else None


class SplatPlacement(WireModel):
    """Where the splat sits in the room: scaled, then rotated, then moved."""

    position: Position = Field(default_factory=lambda: Position(x=0.0, y=0.0, z=0.0))
    rotation: Rotation = Field(default_factory=Rotation)
    scale: float = Field(default=1.0, gt=0, le=100)


class RoomLandmark(WireModel):
    """An object the phone can calibrate by (#120): where it stands on the floor."""

    id: str = Field(min_length=1, max_length=64)
    label: str = Field(min_length=1, max_length=64)
    # Other names Qwen gave it, shown beside its label so two of one label can be told apart.
    aliases: list[str] = Field(default_factory=lambda: list[str](), max_length=8)
    x: float = Field(ge=-100, le=100)
    z: float = Field(ge=-100, le=100)


class _MappedLandmark(BaseModel):
    """One landmark as `backend.landmarks.save_landmarks` writes it. Read here with validation,
    rather than through that module, which brings the renderer and Qwen with it."""

    id: str
    label: str
    centre: tuple[float, float, float]
    aliases: list[str] = []


class _LandmarkMap(BaseModel):
    landmarks: list[_MappedLandmark]


LANDMARKS_FILE = "landmarks.json"


def _load_landmarks(directory: Path) -> list[RoomLandmark]:
    """The room's landmarks from its landmark map (#110), or none when it has no map."""
    path = directory / LANDMARKS_FILE
    if not path.is_file():
        return []
    try:
        mapped = _LandmarkMap.model_validate_json(path.read_text(encoding="utf-8"))
        return [
            RoomLandmark(
                id=mark.id,
                label=mark.label,
                aliases=mark.aliases,
                x=mark.centre[0],
                z=mark.centre[2],
            )
            for mark in mapped.landmarks
        ]
    except (OSError, UnicodeError, ValidationError, ValueError) as exc:
        raise PreparedRoomError(f"Prepared room {LANDMARKS_FILE} is invalid.") from exc


class RoomMap(WireModel):
    """The room seen from above (#124): its image, and the floor area it shows in room metres;
    the image's top is -z and its right +x."""

    url: str
    min_x: float = Field(ge=-100, le=100)
    max_x: float = Field(ge=-100, le=100)
    min_z: float = Field(ge=-100, le=100)
    max_z: float = Field(ge=-100, le=100)


class _MapFile(BaseModel):
    """`map.json` as `backend.room_map.make_map` writes it."""

    image: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}\.png$")
    min_x: float
    max_x: float
    min_z: float
    max_z: float


MAP_FILE = "map.json"


def _load_map(directory: Path) -> RoomMap | None:
    """The room's map, or None when it has none."""
    path = directory / MAP_FILE
    if not path.is_file():
        return None
    try:
        drawn = _MapFile.model_validate_json(path.read_text(encoding="utf-8"))
        if (
            not (directory / drawn.image).is_file()
            or drawn.min_x >= drawn.max_x
            or drawn.min_z >= drawn.max_z
        ):
            raise ValueError("map image missing or empty bounds")
        return RoomMap(
            url=f"{ASSET_URL_PREFIX}/{drawn.image}",
            min_x=drawn.min_x,
            max_x=drawn.max_x,
            min_z=drawn.min_z,
            max_z=drawn.max_z,
        )
    except (OSError, UnicodeError, ValidationError, ValueError) as exc:
        raise PreparedRoomError(f"Prepared room {MAP_FILE} is invalid.") from exc


class LoadedRoom(BaseModel):
    room_version: int
    entities: list[SceneEntity]
    splat_url: str | None = None
    splat_placement: SplatPlacement | None = None
    # A lighter splat for phones, when the room has one (#109); phones draw the full one otherwise.
    splat_phone_url: str | None = None
    # The room seen from above, when it has a map (#124).
    map: RoomMap | None = None
    # Objects the phone can calibrate by standing at two of them (#120).
    landmarks: list[RoomLandmark] = Field(default_factory=lambda: list[RoomLandmark]())


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
    physics: PhysicsMaterial | None = None


class PreparedRoom(WireModel):
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
    physics: PhysicsMaterial | None = None


# A splat file in the room's folder.
SPLAT_FILE = r"^[A-Za-z0-9_-]{1,64}\.(ply|spz)$"


class SplatAsset(SplatPlacement):
    """The splat file, and its placement when it was trained tilted or at another scale."""

    asset: str = Field(pattern=SPLAT_FILE)
    # A lighter copy for phones, so 8th Wall keeps its pace beside it (#109).
    phone_asset: str | None = Field(default=None, pattern=SPLAT_FILE)
    # Where the scale came from, for people: assumed, suggested from objects, or measured (#33).
    scale_source: str | None = Field(default=None, max_length=200)


# How each splat format's file starts: PLY's text header, and SPZ's gzip wrapper.
SPLAT_MAGIC = {".ply": (b"ply\n", "PLY"), ".spz": (b"\x1f\x8b", "SPZ")}


class PreparedScene(WireModel):
    """Schema 2: one GLB per entity and any number of movable entities, and perhaps a splat."""

    schema_version: Literal[2]
    room_version: int = Field(ge=1)
    units: Literal["meters"]
    frame: Literal["y_up_right_handed"]
    pivot: Literal["bottom_center"]
    quaternion_order: Literal["xyzw"]
    entities: list[AssetEntity] = Field(min_length=1, max_length=64)
    splat: SplatAsset | None = None

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
        loaded = (
            _load_scene(directory, scene)
            if isinstance(scene, PreparedScene)
            else _load_legacy(directory, scene)
        )
    except AssetError as exc:
        raise PreparedRoomError(str(exc)) from exc
    loaded.landmarks = _load_landmarks(directory)
    loaded.map = _load_map(directory)
    return loaded


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
                physics=entity.physics,
            )
            for entity in room.entities
        ],
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
    if scene.splat is not None:
        _check_splat(directory, scene.splat.asset)
        if scene.splat.phone_asset is not None:
            _check_splat(directory, scene.splat.phone_asset)
    return LoadedRoom(
        room_version=scene.room_version,
        splat_url=None if scene.splat is None else f"{ASSET_URL_PREFIX}/{scene.splat.asset}",
        splat_phone_url=None
        if scene.splat is None or scene.splat.phone_asset is None
        else f"{ASSET_URL_PREFIX}/{scene.splat.phone_asset}",
        splat_placement=None
        if scene.splat is None
        else SplatPlacement.model_validate(
            scene.splat.model_dump(include=set(SplatPlacement.model_fields))
        ),
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
                physics=entity.physics,
            )
            for entity in scene.entities
        ],
    )


def _check_splat(directory: Path, name: str) -> None:
    path = directory / name
    if not path.is_file():
        raise PreparedRoomError(f"Prepared room splat {name} is missing.")
    magic, kind = SPLAT_MAGIC[path.suffix]
    with path.open("rb") as file:
        if file.read(len(magic)) != magic:
            raise PreparedRoomError(f"Prepared room splat {name} is not a {kind} splat.")


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
