"""Write the issue 23 multi-asset room: one GLB per entity, plus the schema 2 manifest.

Each GLB holds its object in the entity's own frame: meters, right-handed, +Y up, with the center of
the bottom face at the origin. The manifest alone places entities, so the referenced node and its
ancestors have no transform. Child nodes keep translations and rotations the browser must
preserve: the book block is centered and lifted, and the mug handle is turned 90 degrees.
"""

import importlib.util
import json
import math
import struct
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
ROOM_VERSION = 1

# Reuse the stand-in room's outward-wound box geometry and color conversion.
_spec = importlib.util.spec_from_file_location(
    "stand_in_room", ROOT.parent / "prepared-room" / "build_room.py"
)
assert _spec and _spec.loader
stand_in = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(stand_in)


def turn(axis: str, degrees: float) -> list[float]:
    """A unit quaternion in (x, y, z, w) order for a turn about one axis."""
    half = math.radians(degrees) / 2
    quaternion = [0.0, 0.0, 0.0, math.cos(half)]
    quaternion["xyz".index(axis)] = math.sin(half)
    return quaternion


def part(name: str, size: tuple[float, float, float], color: str, **node: Any) -> dict[str, Any]:
    """A box mesh node. ``centered`` geometry spans -h/2..h/2; otherwise it sits on y = 0."""
    return {"name": name, "box": size, "color": color, **node}


ENTITIES: list[dict[str, Any]] = [
    {
        "id": "floor",
        "label": "Floor",
        "kind": "static",
        "selectable": False,
        "size": {"width": 3.0, "height": 0.02, "depth": 3.0},
        "position": {"x": 0.0, "y": -0.02, "z": 0.0},
        "rotation": turn("y", 0),
        "parts": [part("floor_slab", (3.0, 0.02, 3.0), "#8d9399")],
    },
    {
        "id": "table",
        "label": "Table",
        "kind": "static",
        "selectable": False,
        "size": {"width": 1.0, "height": 0.75, "depth": 0.6},
        "position": {"x": 0.0, "y": 0.0, "z": -1.0},
        "rotation": turn("y", 0),
        "parts": [
            part("table_top", (1.0, 0.04, 0.6), "#8b5a2b", translation=[0.0, 0.71, 0.0]),
            *(
                part(f"table_leg_{i}", (0.05, 0.71, 0.05), "#5c4033", translation=[x, 0.0, z])
                for i, (x, z) in enumerate(
                    [(-0.475, -0.275), (0.475, -0.275), (-0.475, 0.275), (0.475, 0.275)], 1
                )
            ),
        ],
    },
    {
        "id": "mug",
        "label": "Mug",
        "kind": "movable",
        "selectable": True,
        "size": {"width": 0.092, "height": 0.1, "depth": 0.08},
        "position": {"x": 0.25, "y": 0.75, "z": -0.95},
        "rotation": turn("y", 0),
        "parts": [
            part("mug_body", (0.08, 0.1, 0.08), "#66e6cf", translation=[-0.006, 0.0, 0.0]),
            part(
                "mug_handle",
                (0.06, 0.012, 0.02),
                "#3fb8a3",
                centered=True,
                translation=[0.04, 0.05, 0.0],
                rotation=turn("z", 90),
            ),
        ],
    },
    {
        "id": "book",
        "label": "Book",
        "kind": "movable",
        "selectable": True,
        "size": {"width": 0.2, "height": 0.04, "depth": 0.15},
        "position": {"x": -0.2, "y": 0.75, "z": -1.05},
        "rotation": turn("y", 30),
        "parts": [
            part(
                "book_block", (0.2, 0.04, 0.15), "#c0392b", centered=True, translation=[0, 0.02, 0]
            )
        ],
    },
]


def write_glb(path: Path, root_name: str, parts: list[dict[str, Any]]) -> None:
    blob = bytearray()
    document: dict[str, Any] = {
        "asset": {"version": "2.0", "generator": "escape-my-room multi-asset room"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"name": root_name, "children": []}],
        "meshes": [],
        "materials": [],
        "accessors": [],
        "bufferViews": [],
    }

    def view(data: bytes, target: int) -> int:
        while len(blob) % 4:
            blob.append(0)
        document["bufferViews"].append(
            {"buffer": 0, "byteOffset": len(blob), "byteLength": len(data), "target": target}
        )
        blob.extend(data)
        return len(document["bufferViews"]) - 1

    for item in parts:
        width, height, depth = item["box"]
        positions, normals, indices = stand_in.box_vertices(width, height, depth)
        lift = height / 2 if item.get("centered") else 0.0
        positions = [value - lift if i % 3 == 1 else value for i, value in enumerate(positions)]
        accessors = document["accessors"]
        accessors.append(
            {
                "bufferView": view(struct.pack(f"<{len(positions)}f", *positions), 34962),
                "componentType": 5126,
                "count": len(positions) // 3,
                "type": "VEC3",
                "min": [-width / 2, -lift, -depth / 2],
                "max": [width / 2, height - lift, depth / 2],
            }
        )
        accessors.append(
            {
                "bufferView": view(struct.pack(f"<{len(normals)}f", *normals), 34962),
                "componentType": 5126,
                "count": len(normals) // 3,
                "type": "VEC3",
            }
        )
        accessors.append(
            {
                "bufferView": view(struct.pack(f"<{len(indices)}H", *indices), 34963),
                "componentType": 5123,
                "count": len(indices),
                "type": "SCALAR",
            }
        )
        document["materials"].append(
            {
                "name": f"{item['name']}-material",
                "pbrMetallicRoughness": {
                    "baseColorFactor": stand_in.linear_color(item["color"]),
                    "metallicFactor": 0.0,
                    "roughnessFactor": 0.8,
                },
            }
        )
        first = len(accessors) - 3
        document["meshes"].append(
            {
                "name": f"{item['name']}-mesh",
                "primitives": [
                    {
                        "attributes": {"POSITION": first, "NORMAL": first + 1},
                        "indices": first + 2,
                        "material": len(document["materials"]) - 1,
                        "mode": 4,
                    }
                ],
            }
        )
        node: dict[str, Any] = {"name": item["name"], "mesh": len(document["meshes"]) - 1}
        for key in ("translation", "rotation"):
            if key in item:
                node[key] = item[key]
        document["nodes"][0]["children"].append(len(document["nodes"]))
        document["nodes"].append(node)

    while len(blob) % 4:
        blob.append(0)
    document["buffers"] = [{"byteLength": len(blob)}]
    text = json.dumps(document, separators=(",", ":")).encode("utf-8")
    text += b" " * (-len(text) % 4)
    length = 12 + 8 + len(text) + 8 + len(blob)
    path.write_bytes(
        struct.pack("<4sII", b"glTF", 2, length)
        + struct.pack("<II", len(text), 0x4E4F534A)
        + text
        + struct.pack("<II", len(blob), 0x004E4942)
        + bytes(blob)
    )


def main() -> None:
    entities = []
    for entity in ENTITIES:
        asset = f"{entity['id']}.glb"
        write_glb(ROOT / asset, entity["id"], entity["parts"])
        x, y, z, w = entity["rotation"]
        entities.append(
            {
                "id": entity["id"],
                "label": entity["label"],
                "asset": asset,
                "node": entity["id"],
                "kind": entity["kind"],
                "selectable": entity["selectable"],
                "size": entity["size"],
                "position": entity["position"],
                "rotation": {"x": x, "y": y, "z": z, "w": w},
            }
        )
    manifest = {
        "schema_version": 2,
        "room_version": ROOM_VERSION,
        "units": "meters",
        "frame": "y_up_right_handed",
        "pivot": "bottom_center",
        "quaternion_order": "xyzw",
        "entities": entities,
    }
    (ROOT / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {len(entities)} entities")


if __name__ == "__main__":
    main()
