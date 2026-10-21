"""Write a larger stand-in room, 6 m square, for walking with measured phone tracking.

The desk, cabinet and box are where the 4 m room has them, so the starting view and room
alignment still match. More furniture around the edges gives the larger floor landmarks, with
open floor in the middle to walk on. The files are written by the 4 m room's writer.
"""

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ROOM_VERSION = 2


def furniture(name: str, color: str, size: tuple[float, float, float], at: tuple[float, float]) -> dict[str, object]:
    """A static box standing on the floor: size as width, height, depth; `at` as x, z of its centre."""
    width, height, depth = size
    return {
        "id": name,
        "node": name,
        "kind": "static",
        "selectable": False,
        "color": color,
        "size": {"width": width, "height": height, "depth": depth},
        "position": {"x": at[0], "y": 0.0, "z": at[1]},
    }


ENTITIES = [
    {
        "id": "floor",
        "node": "floor",
        "kind": "static",
        "selectable": False,
        "color": "#8d9399",
        "size": {"width": 6.0, "height": 0.02, "depth": 6.0},
        "position": {"x": 0.0, "y": -0.02, "z": 0.0},
    },
    # As in the 4 m room.
    furniture("desk", "#8b5a2b", (1.2, 0.75, 0.6), (0.0, -1.2)),
    furniture("cabinet", "#5c4033", (0.8, 1.2, 0.4), (1.4, -1.2)),
    # The far wall, behind the desk.
    furniture("bookshelf", "#6b4f3a", (1.2, 1.9, 0.35), (-2.4, -2.7)),
    furniture("sideboard", "#a0785a", (1.6, 0.5, 0.45), (0.0, -2.7)),
    furniture("plant", "#3f7d4f", (0.4, 1.2, 0.4), (2.6, -2.6)),
    # The left side, a sofa facing a low table.
    furniture("sofa", "#4a5d7e", (0.9, 0.85, 1.8), (-2.45, 1.2)),
    furniture("coffee_table", "#7a6a58", (1.0, 0.45, 0.6), (-1.3, 1.2)),
    # The right side.
    furniture("dining_table", "#9c7b55", (1.4, 0.75, 0.9), (2.1, 1.4)),
    furniture("side_table", "#7d6b5d", (0.5, 0.55, 0.5), (2.6, -0.6)),
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


def main() -> None:
    spec = importlib.util.spec_from_file_location("prepared_room_builder", ROOT.parent / "prepared-room" / "build_room.py")
    if spec is None or spec.loader is None:
        raise RuntimeError("the 4 m room's writer is missing")
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    builder.write_room(ROOT, ENTITIES, ROOM_VERSION, "large-room")


if __name__ == "__main__":
    main()
