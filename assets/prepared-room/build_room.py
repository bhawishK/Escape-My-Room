"""Write the issue 2 stand-in room: local meshes, glTF nodes, and the manifest.

Mesh node names are not entity IDs. The manifest IDs and positions are the
room contract. Node translations are copied from those positions so a glTF
viewer shows the same layout.
"""

import json
import struct
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
ROOM_VERSION = 1

ENTITIES = [
    {
        "id": "floor",
        "node": "floor",
        "kind": "static",
        "selectable": False,
        "color": "#8d9399",
        "size": {"width": 4.0, "height": 0.02, "depth": 4.0},
        "position": {"x": 0.0, "y": -0.02, "z": 0.0},
    },
    {
        "id": "desk",
        "node": "desk",
        "kind": "static",
        "selectable": False,
        "color": "#8b5a2b",
        "size": {"width": 1.2, "height": 0.75, "depth": 0.6},
        "position": {"x": 0.0, "y": 0.0, "z": -1.2},
    },
    {
        "id": "cabinet",
        "node": "cabinet",
        "kind": "static",
        "selectable": False,
        "color": "#5c4033",
        "size": {"width": 0.8, "height": 1.2, "depth": 0.4},
        "position": {"x": 1.4, "y": 0.0, "z": -1.2},
    },
    {
        "id": "box",
        "node": "box",
        "kind": "movable",
        "selectable": True,
        "color": "#66e6cf",
        "size": {"width": 0.2, "height": 0.2, "depth": 0.2},
        "position": {"x": -0.5, "y": 0.0, "z": -0.4},
    },
]


def srgb_channel(hex_pair: str) -> float:
    value = int(hex_pair, 16) / 255
    if value <= 0.04045:
        return value / 12.92
    return ((value + 0.055) / 1.055) ** 2.4


def linear_color(hex_color: str) -> list[float]:
    return [
        srgb_channel(hex_color[1:3]),
        srgb_channel(hex_color[3:5]),
        srgb_channel(hex_color[5:7]),
        1.0,
    ]


def box_vertices(width: float, height: float, depth: float) -> tuple[list[float], list[float], list[int]]:
    """A box whose origin is the center of its bottom face. Faces wind outward."""
    x0, x1 = -width / 2, width / 2
    y0, y1 = 0.0, height
    z0, z1 = -depth / 2, depth / 2
    faces = [
        ((x0, y1, z1), (x1, y1, z1), (x1, y1, z0), (x0, y1, z0), (0.0, 1.0, 0.0)),
        ((x0, y0, z0), (x1, y0, z0), (x1, y0, z1), (x0, y0, z1), (0.0, -1.0, 0.0)),
        ((x1, y0, z1), (x1, y0, z0), (x1, y1, z0), (x1, y1, z1), (1.0, 0.0, 0.0)),
        ((x0, y0, z0), (x0, y0, z1), (x0, y1, z1), (x0, y1, z0), (-1.0, 0.0, 0.0)),
        ((x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1), (0.0, 0.0, 1.0)),
        ((x1, y0, z0), (x0, y0, z0), (x0, y1, z0), (x1, y1, z0), (0.0, 0.0, -1.0)),
    ]
    positions: list[float] = []
    normals: list[float] = []
    indices: list[int] = []
    for corners in faces:
        normal = corners[4]
        start = len(positions) // 3
        for corner in corners[:4]:
            edge_a = [corners[1][axis] - corners[0][axis] for axis in range(3)]
            edge_b = [corners[2][axis] - corners[0][axis] for axis in range(3)]
            crossed = (
                edge_a[1] * edge_b[2] - edge_a[2] * edge_b[1],
                edge_a[2] * edge_b[0] - edge_a[0] * edge_b[2],
                edge_a[0] * edge_b[1] - edge_a[1] * edge_b[0],
            )
            if any(component * expected < 0 for component, expected in zip(crossed, normal, strict=True)):
                raise RuntimeError("box face is wound inward")
            positions.extend(corner)
            normals.extend(normal)
        indices.extend((start, start + 1, start + 2, start, start + 2, start + 3))
    return positions, normals, indices


def main() -> None:
    write_room(ROOT, ENTITIES, ROOM_VERSION, "prepared-room")


def write_room(root: Path, entities: list[dict[str, Any]], room_version: int, scene: str) -> None:
    """Write `manifest.json`, `room.gltf` and `room.bin` for these boxes, with one movable box."""
    blob = bytearray()
    accessors: list[dict[str, object]] = []
    buffer_views: list[dict[str, int]] = []
    meshes: list[dict[str, object]] = []
    nodes: list[dict[str, object]] = []
    materials: list[dict[str, object]] = []

    for entity in entities:
        size = entity["size"]
        positions, normals, indices = box_vertices(size["width"], size["height"], size["depth"])
        packed = struct.pack(f"<{len(positions)}f", *positions)
        packed += struct.pack(f"<{len(normals)}f", *normals)
        packed += struct.pack(f"<{len(indices)}H", *indices)
        view_start = len(blob)
        blob.extend(packed)

        position_count = len(positions) // 3
        normal_count = len(normals) // 3
        position_view = len(buffer_views)
        buffer_views.append(
            {"buffer": 0, "byteOffset": view_start, "byteLength": position_count * 12, "target": 34962}
        )
        normal_view = len(buffer_views)
        buffer_views.append(
            {
                "buffer": 0,
                "byteOffset": view_start + position_count * 12,
                "byteLength": normal_count * 12,
                "target": 34962,
            }
        )
        index_view = len(buffer_views)
        buffer_views.append(
            {
                "buffer": 0,
                "byteOffset": view_start + (position_count + normal_count) * 12,
                "byteLength": len(indices) * 2,
                "target": 34963,
            }
        )
        position_accessor = len(accessors)
        accessors.append(
            {
                "bufferView": position_view,
                "componentType": 5126,
                "count": position_count,
                "type": "VEC3",
                "min": [-size["width"] / 2, 0.0, -size["depth"] / 2],
                "max": [size["width"] / 2, size["height"], size["depth"] / 2],
            }
        )
        normal_accessor = len(accessors)
        accessors.append(
            {
                "bufferView": normal_view,
                "componentType": 5126,
                "count": normal_count,
                "type": "VEC3",
            }
        )
        index_accessor = len(accessors)
        accessors.append(
            {"bufferView": index_view, "componentType": 5123, "count": len(indices), "type": "SCALAR"}
        )
        material_index = len(materials)
        materials.append(
            {
                "name": entity["id"],
                "pbrMetallicRoughness": {
                    "baseColorFactor": linear_color(entity["color"]),
                    "metallicFactor": 0.0,
                    "roughnessFactor": 0.8,
                },
            }
        )
        mesh_index = len(meshes)
        meshes.append(
            {
                "name": f"{entity['id']}-mesh",
                "primitives": [
                    {
                        "attributes": {"POSITION": position_accessor, "NORMAL": normal_accessor},
                        "indices": index_accessor,
                        "material": material_index,
                        "mode": 4,
                    }
                ],
            }
        )
        position = entity["position"]
        nodes.append(
            {
                "name": entity["node"],
                "mesh": mesh_index,
                "translation": [position["x"], position["y"], position["z"]],
            }
        )

    document = {
        "asset": {"version": "2.0", "generator": "escape-my-room prepared room"},
        "scene": 0,
        "scenes": [{"name": scene, "nodes": list(range(len(nodes)))}],
        "nodes": nodes,
        "meshes": meshes,
        "materials": materials,
        "accessors": accessors,
        "bufferViews": buffer_views,
        "buffers": [{"uri": "room.bin", "byteLength": len(blob)}],
    }
    manifest = {
        "room_version": room_version,
        "units": "meters",
        "asset": "room.gltf",
        "entities": entities,
    }
    if [entity["id"] for entity in entities].count("box") != 1:
        raise RuntimeError("the room needs exactly one box")
    movable = [entity["id"] for entity in entities if entity["kind"] == "movable"]
    if movable != ["box"]:
        raise RuntimeError("only the box is movable")

    (root / "room.bin").write_bytes(blob)
    (root / "room.gltf").write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    (root / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {len(entities)} entities, {len(blob)} bytes")


if __name__ == "__main__":
    main()
