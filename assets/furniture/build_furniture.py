"""Write the built-in furniture (#181): `catalogue.json`, `furniture.gltf` and `furniture.bin`.

Each piece is one glTF node named after its catalogue id, made of a few coloured boxes. The node's
origin is the centre of its bottom face, as room entities' are, and it faces -z: a sofa's back is
at +z. Every piece fills exactly its catalogue size, so its box collider fits it.

Run it again after changing a piece: python assets/furniture/build_furniture.py
"""

import importlib.util
import json
import struct
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location(
    "build_room", ROOT.parent / "prepared-room" / "build_room.py"
)
assert _spec is not None and _spec.loader is not None
_build_room = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_build_room)
box_vertices = _build_room.box_vertices
linear_color = _build_room.linear_color

# A part: (width, height, depth) and the centre of its bottom face (x, y, z), in the piece's frame.
Part = tuple[tuple[float, float, float], tuple[float, float, float]]


def legs(width: float, depth: float, height: float, leg: float) -> list[Part]:
    """Four square legs at the corners of a width × depth footprint."""
    x, z = width / 2 - leg / 2, depth / 2 - leg / 2
    return [((leg, height, leg), (sx * x, 0.0, sz * z)) for sx in (-1, 1) for sz in (-1, 1)]


# id, name, (width, depth, height), colour, parts.
PIECES: list[tuple[str, str, tuple[float, float, float], str, list[Part]]] = [
    (
        "sofa", "Sofa", (2.0, 0.9, 0.85), "#5b7f6e",
        [
            ((2.0, 0.42, 0.9), (0.0, 0.0, 0.0)),
            ((2.0, 0.43, 0.2), (0.0, 0.42, 0.35)),
            ((0.2, 0.2, 0.7), (-0.9, 0.42, -0.1)),
            ((0.2, 0.2, 0.7), (0.9, 0.42, -0.1)),
        ],
    ),
    (
        "armchair", "Armchair", (0.85, 0.85, 0.9), "#a0674b",
        [
            ((0.85, 0.42, 0.85), (0.0, 0.0, 0.0)),
            ((0.85, 0.48, 0.18), (0.0, 0.42, 0.335)),
            ((0.15, 0.2, 0.67), (-0.35, 0.42, -0.09)),
            ((0.15, 0.2, 0.67), (0.35, 0.42, -0.09)),
        ],
    ),
    (
        "table", "Table", (1.4, 0.8, 0.75), "#9c7650",
        [*legs(1.4, 0.8, 0.71, 0.06), ((1.4, 0.04, 0.8), (0.0, 0.71, 0.0))],
    ),
    (
        "chair", "Chair", (0.45, 0.5, 0.9), "#6f5a46",
        [
            *legs(0.45, 0.5, 0.42, 0.04),
            ((0.45, 0.04, 0.5), (0.0, 0.42, 0.0)),
            ((0.45, 0.44, 0.04), (0.0, 0.46, 0.23)),
        ],
    ),
    (
        "lamp", "Floor lamp", (0.35, 0.35, 1.6), "#d9c9a3",
        [
            ((0.3, 0.03, 0.3), (0.0, 0.0, 0.0)),
            ((0.03, 1.27, 0.03), (0.0, 0.03, 0.0)),
            ((0.35, 0.3, 0.35), (0.0, 1.3, 0.0)),
        ],
    ),
    (
        "shelf", "Bookshelf", (0.8, 0.35, 1.8), "#7d6248",
        [
            ((0.03, 1.8, 0.35), (-0.385, 0.0, 0.0)),
            ((0.03, 1.8, 0.35), (0.385, 0.0, 0.0)),
            ((0.74, 1.8, 0.02), (0.0, 0.0, 0.165)),
            *[((0.74, 0.03, 0.33), (0.0, y, -0.01)) for y in (0.0, 0.44, 0.88, 1.32, 1.77)],
        ],
    ),
    (
        "rug", "Rug", (2.0, 1.4, 0.01), "#b5525a",
        [((2.0, 0.01, 1.4), (0.0, 0.0, 0.0))],
    ),
]


def main() -> None:
    blob = bytearray()
    accessors: list[dict[str, Any]] = []
    views: list[dict[str, int]] = []
    meshes: list[dict[str, Any]] = []
    materials: list[dict[str, Any]] = []
    nodes: list[dict[str, Any]] = []
    roots: list[int] = []
    items: list[dict[str, Any]] = []

    def add_view(data: bytes, target: int) -> int:
        while len(blob) % 4:
            blob.append(0)
        views.append({"buffer": 0, "byteOffset": len(blob), "byteLength": len(data), "target": target})
        blob.extend(data)
        return len(views) - 1

    for piece_id, name, (width, depth, height), colour, parts in PIECES:
        material = len(materials)
        materials.append(
            {
                "name": piece_id,
                "pbrMetallicRoughness": {
                    "baseColorFactor": linear_color(colour),
                    "metallicFactor": 0.0,
                    "roughnessFactor": 0.85,
                },
            }
        )
        children: list[int] = []
        for index, ((w, h, d), (x, y, z)) in enumerate(parts):
            positions, normals, indices = box_vertices(w, h, d)
            count = len(positions) // 3
            position = add_view(struct.pack(f"<{len(positions)}f", *positions), 34962)
            normal = add_view(struct.pack(f"<{len(normals)}f", *normals), 34962)
            index_view = add_view(struct.pack(f"<{len(indices)}H", *indices), 34963)
            accessors.extend(
                [
                    {
                        "bufferView": position, "componentType": 5126, "count": count,
                        "type": "VEC3", "min": [-w / 2, 0.0, -d / 2], "max": [w / 2, h, d / 2],
                    },
                    {"bufferView": normal, "componentType": 5126, "count": count, "type": "VEC3"},
                    {
                        "bufferView": index_view, "componentType": 5123,
                        "count": len(indices), "type": "SCALAR",
                    },
                ]
            )
            first = len(accessors) - 3
            meshes.append(
                {
                    "name": f"{piece_id}-{index}",
                    "primitives": [
                        {
                            "attributes": {"POSITION": first, "NORMAL": first + 1},
                            "indices": first + 2,
                            "material": material,
                            "mode": 4,
                        }
                    ],
                }
            )
            nodes.append(
                {"name": f"{piece_id}-{index}", "mesh": len(meshes) - 1, "translation": [x, y, z]}
            )
            children.append(len(nodes) - 1)
        nodes.append({"name": piece_id, "children": children})
        roots.append(len(nodes) - 1)
        items.append(
            {
                "id": piece_id,
                "name": name,
                "node": piece_id,
                "size": {"width": width, "height": height, "depth": depth},
            }
        )

    gltf = {
        "asset": {"version": "2.0", "generator": "Escape My Room build_furniture.py"},
        "scene": 0,
        "scenes": [{"name": "furniture", "nodes": roots}],
        "nodes": nodes,
        "meshes": meshes,
        "materials": materials,
        "accessors": accessors,
        "bufferViews": views,
        "buffers": [{"uri": "furniture.bin", "byteLength": len(blob)}],
    }
    (ROOT / "furniture.bin").write_bytes(bytes(blob))
    (ROOT / "furniture.gltf").write_text(json.dumps(gltf, indent=1) + "\n", encoding="utf-8")
    catalogue = {"asset": "furniture.gltf", "items": items}
    (ROOT / "catalogue.json").write_text(json.dumps(catalogue, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
