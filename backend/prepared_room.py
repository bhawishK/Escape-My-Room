"""Load the prepared room manifest and reject a model that does not match it."""

import json
from pathlib import Path
from typing import Literal, Self

from pydantic import Field, ValidationError, model_validator

from backend.protocol import Position, WireModel


class PreparedRoomError(Exception):
    """The prepared room cannot be served consistently."""


class EntitySize(WireModel):
    width: float = Field(gt=0, le=100)
    height: float = Field(gt=0, le=100)
    depth: float = Field(gt=0, le=100)


class RoomEntity(WireModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9_]{0,31}$")
    node: str = Field(pattern=r"^[A-Za-z0-9._-]{1,64}$")
    kind: Literal["static", "movable"]
    selectable: bool
    color: str = Field(pattern=r"^#[0-9a-fA-F]{6}$")
    size: EntitySize
    position: Position


class PreparedRoom(WireModel):
    room_version: int = Field(ge=1)
    units: str = Field(pattern=r"^meters$")
    asset: str = Field(pattern=r"^[A-Za-z0-9._-]+\.gltf$")
    entities: list[RoomEntity] = Field(min_length=1)

    @model_validator(mode="after")
    def check_entities(self) -> Self:
        if len({entity.id for entity in self.entities}) != len(self.entities):
            raise ValueError("Entity IDs must be unique")
        if len({entity.node for entity in self.entities}) != len(self.entities):
            raise ValueError("Entity nodes must be unique")
        movable = [entity for entity in self.entities if entity.kind == "movable"]
        if len(movable) != 1:
            raise ValueError("The room needs exactly one movable entity")
        for entity in self.entities:
            if entity.kind == "static" and entity.selectable:
                raise ValueError(f"{entity.id} is static and cannot be selectable")
            if entity.kind == "movable" and not entity.selectable:
                raise ValueError(f"{entity.id} is movable and must be selectable")
        return self


def load_prepared_room(directory: Path) -> PreparedRoom:
    manifest_path = directory / "manifest.json"
    if not manifest_path.is_file():
        raise PreparedRoomError("Prepared room manifest is missing.")
    try:
        room = PreparedRoom.model_validate_json(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValidationError, ValueError) as exc:
        raise PreparedRoomError("Prepared room manifest is invalid.") from exc
    _require_matching_model(directory, room)
    return room


def _translation_matches(translation: object, expected: tuple[float, float, float]) -> bool:
    if not isinstance(translation, list) or len(translation) != 3:
        return False
    try:
        pairs = zip(translation, expected, strict=True)
        return all(abs(float(value) - axis) <= 1e-5 for value, axis in pairs)
    except (TypeError, ValueError):
        return False


def _asset_file(directory: Path, name: str) -> Path:
    path = (directory / name).resolve()
    if path.parent != directory.resolve():
        raise PreparedRoomError("Prepared room asset is missing.")
    return path


def _require_matching_model(directory: Path, room: PreparedRoom) -> None:
    asset_path = _asset_file(directory, room.asset)
    if not asset_path.is_file():
        raise PreparedRoomError("Prepared room asset is missing.")
    try:
        document = json.loads(asset_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise PreparedRoomError("Prepared room model could not be read.") from exc
    nodes = document.get("nodes")
    meshes = document.get("meshes")
    if not isinstance(nodes, list) or not isinstance(meshes, list):
        raise PreparedRoomError("Prepared room model could not be read.")
    named_nodes = {
        node.get("name"): node
        for node in nodes
        if isinstance(node, dict) and isinstance(node.get("name"), str)
    }
    used_meshes: set[int] = set()
    for entity in room.entities:
        node = named_nodes.get(entity.node)
        mesh_index = node.get("mesh") if isinstance(node, dict) else None
        if not isinstance(mesh_index, int) or not 0 <= mesh_index < len(meshes):
            raise PreparedRoomError(f"Prepared room model is missing {entity.id}.")
        if mesh_index in used_meshes:
            raise PreparedRoomError(
                f"Prepared room model does not keep {entity.id} as its own mesh."
            )
        used_meshes.add(mesh_index)
        translation = node.get("translation") if isinstance(node, dict) else None
        expected = (entity.position.x, entity.position.y, entity.position.z)
        if not _translation_matches(translation, expected):
            raise PreparedRoomError(
                f"Prepared room node {entity.node} does not match the manifest position."
            )
    buffers = document.get("buffers")
    if not isinstance(buffers, list) or not buffers or not isinstance(buffers[0], dict):
        raise PreparedRoomError("Prepared room geometry is missing.")
    uri = buffers[0].get("uri")
    buffer_missing = (
        not isinstance(uri, str)
        or uri.startswith(("data:", "/"))
        or not _asset_file(directory, uri).is_file()
    )
    if buffer_missing:
        raise PreparedRoomError("Prepared room geometry is missing.")
