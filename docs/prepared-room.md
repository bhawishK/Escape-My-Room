# Prepared room decision

Issue 2 loads this one prepared room. It is a stand-in, not a scan of a physical room. Later issues may replace the shapes with a real reconstruction if the IDs below stay the same.

## Coordinate frame

- Units are meters.
- The origin is the center of the floor.
- +X is right, +Y is up, +Z is toward the viewer. This matches the current diagnostic camera, which sits on +Z and looks toward -Z.
- glTF is Y-up and right-handed.
- An entity position is the center of that object's bottom face. Furniture and the box rest on the floor at y = 0.
- The floor is the exception: it is a 0.02 m slab whose top surface is y = 0, so its position is `(0, -0.02, 0)`.

Room version is the integer `1`.

## Entities

Mesh names inside the model file are not IDs. These manifest IDs are the identities both clients must use.

| ID | Kind | Selectable | Size (width × height × depth) | Position (bottom center) |
| --- | --- | --- | --- | --- |
| `floor` | static | no | 4.00 × 0.02 × 4.00 m | `(0, -0.02, 0)` |
| `desk` | static | no | 1.20 × 0.75 × 0.60 m | `(0, 0, -1.20)` |
| `cabinet` | static | no | 0.80 × 1.20 × 0.40 m | `(1.40, 0, -1.20)` |
| `box` | movable | yes | 0.20 × 0.20 × 0.20 m | `(-0.50, 0, -0.40)` |

Width is along X, height along Y, depth along Z. The desk and cabinet sit toward the far side of the floor and do not overlap. The box sits on the floor in front of the desk, closer to the viewer. Only `box` may later be moved. Moving it must not move `floor`, `desk`, or `cabinet`.

Selection behavior is issue 5. The selectable flag is recorded now so the manifest can distinguish the box from the furniture.

## Asset files

`assets/prepared-room/build_room.py` writes three files from the table above:

- `manifest.json` holds room version `1` and the entity IDs, kinds, flags, sizes, and positions. This file is the identity contract.
- `room.gltf` holds four separate meshes. Each mesh origin is the center of that object's bottom face. A node name is only a pointer; it is not the entity ID.
- `room.bin` holds the vertex data for those meshes.

Node translations in `room.gltf` are copied from the manifest positions, so opening the model shows the same layout as the table.

## Stand-in colors

| ID | Color |
| --- | --- |
| `floor` | `#8d9399` |
| `desk` | `#8b5a2b` |
| `cabinet` | `#5c4033` |
| `box` | `#66e6cf` |

## How the files are produced

From the repository root, run `python3 assets/prepared-room/build_room.py`. It rebuilds `manifest.json`, `room.gltf`, and `room.bin` from the entity table in this document. Change a size or position in that script, then run it again. Do not edit the model and the manifest separately.

Python loads the manifest when the server starts. It refuses the room if the model is missing, a listed object has no mesh of its own, or a model position disagrees with the manifest. Both devices then see the same error instead of two different rooms.

## What was checked

Automated checks cover the shared version and entity list, a box move that leaves the floor, desk, and cabinet in place, rejection of a furniture move, a wrong room version being removed from the session, and a missing model file.

A desktop browser at `http://127.0.0.1:8000` showed the gray floor, brown desk, darker cabinet, and teal box after **Connect phone**, with the status `Room version 1 · floor, desk, cabinet, box (movable)`. iPhone and Quest observations for this room are not recorded yet. Open the same HTTPS address used for the connection test and confirm both devices show that same status.
