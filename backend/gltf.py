"""Read just enough of a glTF 2.0 asset to check the nodes a room manifest points at.

Matrices are column-major 4x4 tuples, as in glTF. Quaternions are (x, y, z, w).
"""

import json
import math
import struct
from pathlib import Path
from typing import cast

type JSONObject = dict[str, object]
type Matrix = tuple[float, ...]
type Vector = tuple[float, float, float]

IDENTITY: Matrix = (1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0)

GLB_MAGIC = b"glTF"
GLB_JSON_CHUNK = 0x4E4F534A
GLB_BIN_CHUNK = 0x004E4942


class AssetError(Exception):
    """The asset cannot be read or used as the manifest declares."""


def _object(value: object) -> JSONObject | None:
    return cast(JSONObject, value) if isinstance(value, dict) else None


def _objects(value: object) -> list[JSONObject] | None:
    if not isinstance(value, list):
        return None
    items = [_object(item) for item in cast(list[object], value)]
    return None if any(item is None for item in items) else cast(list[JSONObject], items)


def _numbers(value: object, count: int) -> tuple[float, ...] | None:
    if not isinstance(value, list):
        return None
    items = cast(list[object], value)
    if len(items) != count:
        return None
    numbers: list[float] = []
    for item in items:
        if isinstance(item, bool) or not isinstance(item, int | float):
            return None
        if not math.isfinite(item):
            return None
        numbers.append(float(item))
    return tuple(numbers)


def _index(value: object, size: int) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value < size:
        return None
    return value


def multiply(a: Matrix, b: Matrix) -> Matrix:
    return tuple(
        sum(a[k * 4 + row] * b[column * 4 + k] for k in range(4))
        for column in range(4)
        for row in range(4)
    )


def transform_point(m: Matrix, point: Vector) -> Vector:
    x, y, z = point
    return (
        m[0] * x + m[4] * y + m[8] * z + m[12],
        m[1] * x + m[5] * y + m[9] * z + m[13],
        m[2] * x + m[6] * y + m[10] * z + m[14],
    )


def compose(translation: Vector, rotation: tuple[float, ...], scale: Vector) -> Matrix:
    x, y, z, w = rotation
    sx, sy, sz = scale
    return (
        (1 - 2 * (y * y + z * z)) * sx,
        (2 * (x * y + z * w)) * sx,
        (2 * (x * z - y * w)) * sx,
        0.0,
        (2 * (x * y - z * w)) * sy,
        (1 - 2 * (x * x + z * z)) * sy,
        (2 * (y * z + x * w)) * sy,
        0.0,
        (2 * (x * z + y * w)) * sz,
        (2 * (y * z - x * w)) * sz,
        (1 - 2 * (x * x + y * y)) * sz,
        0.0,
        translation[0],
        translation[1],
        translation[2],
        1.0,
    )


class GltfDocument:
    """A parsed asset whose node hierarchy is a forest."""

    def __init__(self, name: str, document: object) -> None:
        self.name = name
        root = _object(document)
        nodes = _objects(root.get("nodes")) if root else None
        meshes = _objects(root.get("meshes")) if root else None
        accessors = _objects(root.get("accessors", [])) if root else None
        if root is None or nodes is None or meshes is None or accessors is None:
            raise self.unreadable()
        self.document = root
        self.nodes = nodes
        self.meshes = meshes
        self.accessors = accessors
        self.parents: dict[int, int] = {}
        for parent, node in enumerate(nodes):
            children = node.get("children", [])
            if not isinstance(children, list):
                raise self.unreadable()
            for child in cast(list[object], children):
                index = _index(child, len(nodes))
                if index is None or index == parent or index in self.parents:
                    raise self.unreadable()
                self.parents[index] = parent
        for start in range(len(nodes)):
            if len(self.ancestors(start)) >= len(nodes):
                raise self.unreadable()

    def unreadable(self) -> AssetError:
        return AssetError(f"Prepared room asset {self.name} could not be read.")

    def ancestors(self, index: int) -> list[int]:
        found: list[int] = []
        while index in self.parents and len(found) < len(self.nodes):
            index = self.parents[index]
            found.append(index)
        return found

    def find_node(self, name: str) -> int | None:
        """Return the only node with this name, as the browser resolves entities by name.

        Three.js gives nodes, meshes, scenes and cameras one name namespace per file and renames
        a later duplicate, so a node sharing such a name would not be found reliably.
        """
        matches = [index for index, node in enumerate(self.nodes) if node.get("name") == name]
        others = {
            mesh.get("name", f"mesh_{index}") for index, mesh in enumerate(self.meshes)
        } | {
            item.get("name")
            for key in ("scenes", "cameras")
            for item in _objects(self.document.get(key, [])) or []
        }
        return matches[0] if len(matches) == 1 and name not in others else None

    def local_matrix(self, index: int) -> Matrix:
        node = self.nodes[index]
        if "matrix" in node:
            if any(key in node for key in ("translation", "rotation", "scale")):
                raise self.unreadable()
            matrix = _numbers(node["matrix"], 16)
            if matrix is None:
                raise self.unreadable()
            return matrix
        translation = _numbers(node.get("translation", [0, 0, 0]), 3)
        rotation = _numbers(node.get("rotation", [0, 0, 0, 1]), 4)
        scale = _numbers(node.get("scale", [1, 1, 1]), 3)
        if translation is None or rotation is None or scale is None:
            raise self.unreadable()
        norm = math.sqrt(sum(value * value for value in rotation))
        if abs(norm - 1) > 1e-3:
            raise self.unreadable()
        return compose(
            (translation[0], translation[1], translation[2]),
            tuple(value / norm for value in rotation),
            (scale[0], scale[1], scale[2]),
        )

    def has_transform(self, index: int) -> bool:
        matrix = self.local_matrix(index)
        return any(abs(a - b) > 1e-6 for a, b in zip(matrix, IDENTITY, strict=True))

    def local_bounds(self, index: int) -> tuple[Vector, Vector] | None:
        """Bounds of this node's subtree in the node's own frame, from accessor min/max.

        The node's own transform is excluded; descendant transforms are applied. Returns None when
        the subtree has no mesh.
        """
        corners: list[Vector] = []
        pending: list[tuple[int, Matrix]] = [(index, IDENTITY)]
        while pending:
            current, matrix = pending.pop()
            node = self.nodes[current]
            if "mesh" in node:
                mesh = _index(node["mesh"], len(self.meshes))
                if mesh is None:
                    raise self.unreadable()
                for low, high in self._mesh_extents(mesh):
                    corners.extend(
                        transform_point(matrix, (x, y, z))
                        for x in (low[0], high[0])
                        for y in (low[1], high[1])
                        for z in (low[2], high[2])
                    )
            pending.extend(
                (child, multiply(matrix, self.local_matrix(child)))
                for child, parent in self.parents.items()
                if parent == current
            )
        if not corners:
            return None
        low = (min(c[0] for c in corners), min(c[1] for c in corners), min(c[2] for c in corners))
        high = (max(c[0] for c in corners), max(c[1] for c in corners), max(c[2] for c in corners))
        return low, high

    def _mesh_extents(self, mesh: int) -> list[tuple[Vector, Vector]]:
        primitives = _objects(self.meshes[mesh].get("primitives"))
        if not primitives:
            raise self.unreadable()
        extents: list[tuple[Vector, Vector]] = []
        for primitive in primitives:
            attributes = _object(primitive.get("attributes")) or {}
            accessor = _index(attributes.get("POSITION"), len(self.accessors))
            if accessor is None:
                raise self.unreadable()
            low = _numbers(self.accessors[accessor].get("min"), 3)
            high = _numbers(self.accessors[accessor].get("max"), 3)
            if low is None or high is None:
                raise self.unreadable()
            extents.append(((low[0], low[1], low[2]), (high[0], high[1], high[2])))
        return extents


def read_asset(path: Path) -> GltfDocument:
    """Read a self-contained .glb, or a .gltf whose single buffer is a file beside it."""
    name = path.name
    if not path.is_file():
        raise AssetError(f"Prepared room asset {name} is missing.")
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise AssetError(f"Prepared room asset {name} could not be read.") from exc
    binary: bytes | None = None
    if path.suffix == ".glb":
        document, binary = _split_glb(name, data)
    else:
        try:
            document = json.loads(data.decode("utf-8"))
        except (UnicodeError, ValueError) as exc:
            raise AssetError(f"Prepared room asset {name} could not be read.") from exc
    asset = GltfDocument(name, document)
    buffers = _objects(asset.document.get("buffers"))
    if not buffers or len(buffers) != 1:
        raise AssetError(f"Prepared room asset {name} geometry is missing.")
    length = buffers[0].get("byteLength")
    uri = buffers[0].get("uri")
    if path.suffix == ".glb":
        missing = (
            binary is None or uri is not None or not isinstance(length, int) or len(binary) < length
        )
    else:
        missing = (
            not isinstance(uri, str)
            or uri.startswith(("data:", "/"))
            or (path.parent / uri).resolve().parent != path.parent.resolve()
            or not (path.parent / uri).is_file()
        )
    if missing:
        raise AssetError(f"Prepared room asset {name} geometry is missing.")
    return asset


def _split_glb(name: str, data: bytes) -> tuple[object, bytes | None]:
    unreadable = AssetError(f"Prepared room asset {name} could not be read.")
    if len(data) < 20:
        raise unreadable
    magic, version, length = struct.unpack_from("<4sII", data, 0)
    if magic != GLB_MAGIC or version != 2 or length != len(data):
        raise unreadable
    chunks: list[tuple[int, bytes]] = []
    offset = 12
    while offset < length:
        if offset + 8 > length:
            raise unreadable
        size, kind = struct.unpack_from("<II", data, offset)
        offset += 8
        if offset + size > length:
            raise unreadable
        chunks.append((kind, data[offset : offset + size]))
        offset += size
    if not chunks or chunks[0][0] != GLB_JSON_CHUNK:
        raise unreadable
    try:
        document = json.loads(chunks[0][1].decode("utf-8"))
    except (UnicodeError, ValueError) as exc:
        raise unreadable from exc
    binary = chunks[1][1] if len(chunks) > 1 and chunks[1][0] == GLB_BIN_CHUNK else None
    return document, binary
