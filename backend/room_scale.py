"""Room scale from objects of known size (#33).

A splat room's scale is first guessed from the camera height the notebook assumes (1.4 m), which
was 10-25% off in our rooms. Here Qwen finds doors in views rendered from the room
(render-and-ask, #98), the splat measures how tall each one is, and the suggested scale makes them
as tall as a typical interior door. The master confirms it, gives a measured height instead, or
keeps the approximation (`backend/room_scale_check.py`).
"""

import json
import math
import re
import statistics
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from backend.openrouter import AnswerFormat, OpenRouterClient, Reply, Unreadable, without_thinking
from backend.prepared_room import load_prepared_room
from backend.room_views import (
    View,
    ask_about_views,
    filmed,
    placed,
    point_at,
    project,
    render_views,
)
from backend.splat_file import Vector, visible_splats

# Fractions of a view: left, top, right, bottom.
type Box = tuple[float, float, float, float]

# A box's sides often take in the door frame and the wall; its middle is the door itself.
SIDE_MARGIN = 0.2
MIN_SPLATS = 20
# The nearest quarter of what a box shows is the object; further splats show through or past it.
NEAR_SHARE = 0.25


def room_splats(room_dir: Path) -> list[Vector]:
    """The centres of the room's visible splats, placed in the room as the devices place them."""
    room = load_prepared_room(room_dir)
    if room.splat_url is None or room.splat_placement is None:
        raise ValueError("The prepared room has no splat.")
    placement = room.splat_placement
    path = room_dir / room.splat_url.rsplit("/", 1)[-1]
    return [placed(placement, point) for point in visible_splats(path)]


@dataclass(frozen=True)
class Measurement:
    # How far the object's top is above the floor (y = 0), in room metres.
    height: float
    # How far in front of the camera it was measured.
    depth: float
    # How many splats the box held.
    splats: int


def measure_height(splats: list[Vector], view: View, box: Box) -> Measurement | None:
    """How high the top edge of the object in `box` is above the floor, or None when the box
    shows too little of the splat to measure."""
    left, top, right, bottom = box
    inset = (right - left) * SIDE_MARGIN
    depths: list[float] = []
    for point in splats:
        seen = project(view, point)
        if seen and left + inset <= seen[0] <= right - inset and top <= seen[1] <= bottom:
            depths.append(_depth(view, point))
    if len(depths) < MIN_SPLATS:
        return None
    depths.sort()
    depth = statistics.median(depths[: max(1, int(len(depths) * NEAR_SHARE))])
    top_point = point_at(view, (left + right) / 2, top, depth)
    return Measurement(height=top_point[1], depth=depth, splats=len(depths))


def _depth(view: View, point: Vector) -> float:
    """How far `point` is in front of the camera, along its line of sight."""
    look = [view.look_at[i] - view.position[i] for i in range(3)]
    length = sum(c * c for c in look) ** 0.5
    return sum((point[i] - view.position[i]) * look[i] for i in range(3)) / length


# A typical interior door: 2.03 m (6 ft 8 in) in the US, 1.98-2.04 m in Europe.
DOOR_HEIGHT = 2.03

FIND_DOORS = (
    "Find every door a person walks through in this image, open or closed: room, hall and "
    "entrance doors, not cupboard, wardrobe or cabinet doors. "
    'Output ONLY a JSON list like [{"label": "door", "bbox_2d": [x1, y1, x2, y2]}], with '
    "coordinates from 0 to 1000 relative to the image width and height. "
    "Output [] if there is no door."
)


def read_door_boxes(text: str) -> list[Box]:
    """Qwen's door boxes, as fractions of the view; its coordinates run from 0 to 1000."""
    answer = re.sub(r"^```(?:json)?\s*|\s*```$", "", without_thinking(text).strip())
    try:
        items: object = json.loads(answer)
    except json.JSONDecodeError as exc:
        raise Unreadable("the answer is not a JSON list") from exc
    if not isinstance(items, list):
        raise Unreadable("the answer is not a JSON list")
    boxes: list[Box] = []
    for item in cast(list[object], items):
        if not isinstance(item, dict):
            raise Unreadable("every item must be a door")
        fields = cast(dict[str, object], item)
        if str(fields.get("label", "")).casefold() != "door":
            raise Unreadable("every item must be a door")
        edges = fields.get("bbox_2d")
        numbers = [
            float(edge)
            for edge in (cast(list[object], edges) if isinstance(edges, list) else [])
            if isinstance(edge, int | float) and 0 <= edge <= 1000
        ]
        if len(numbers) != 4 or len(cast(list[object], edges)) != 4:
            raise Unreadable("bbox_2d must be four numbers from 0 to 1000")
        left, top, right, bottom = (edge / 1000 for edge in numbers)
        if left >= right or top >= bottom:
            raise Unreadable("bbox_2d must be [x1, y1, x2, y2] with x1 < x2 and y1 < y2")
        boxes.append((left, top, right, bottom))
    return boxes


DOOR_BOXES = AnswerFormat(
    "door boxes",
    read_door_boxes,
    "Your answer did not follow the format. Output ONLY a JSON list like "
    '[{"label": "door", "bbox_2d": [x1, y1, x2, y2]}] with coordinates from 0 to 1000, '
    "or [] if there is no door.",
)

# A box this close to the top of the view may have lost the door's top edge.
CUT_OFF = 0.01


@dataclass(frozen=True)
class Evidence:
    view: View
    # Which of the views it was seen in, counted from 1.
    view_number: int
    box: Box
    measured: Measurement


@dataclass(frozen=True)
class Suggestion:
    # Multiply the room's scale by this; None when no door could be measured.
    factor: float | None
    typical_height: float
    evidence: list[Evidence]
    # Doors Qwen found that were not measured, and why.
    skipped: list[str]
    # Every view looked at, as PNGs, for the master to check.
    pngs: list[bytes]


def scan_views(room_dir: Path) -> list[View]:
    """Eight level views round each place the room was filmed from, wide enough to see a whole
    door from a step or two away.

    The places are the first, middle and last filmed cameras, or the origin when the room keeps no
    record of its filming: the walk is centred there. Away from the filming the splat has gaps,
    and its floor, sized to every splat, can reach well outside the room.
    """
    cameras = filmed(room_dir)
    picks = sorted({0, len(cameras) // 2, len(cameras) - 1}) if cameras else []
    spots = [(cameras[i].position[0], cameras[i].position[2]) for i in picks] or [(0.0, 0.0)]
    eye = 1.1
    return [
        View(
            position=(x, eye, z),
            look_at=(x + math.sin(turn), eye, z - math.cos(turn)),
            fov_degrees=80.0,
        )
        for x, z in spots
        for turn in (2 * math.pi * i / 8 for i in range(8))
    ]


def suggest_scale(
    room_dir: Path,
    client: OpenRouterClient,
    on_reply: Callable[[Reply, str | None], None],
    views: list[View] | None = None,
    typical_height: float = DOOR_HEIGHT,
) -> Suggestion:
    """Ask Qwen for the doors in each view, measure each one, and suggest the factor that makes
    the median door `typical_height` tall."""
    views = views or scan_views(room_dir)
    rendered = render_views(room_dir, views)
    splats = room_splats(room_dir)
    evidence: list[Evidence] = []
    skipped: list[str] = []
    for number, shot in enumerate(rendered, start=1):
        for box in ask_about_views(client, [shot], FIND_DOORS, DOOR_BOXES, on_reply):
            if box[1] < CUT_OFF:
                skipped.append(f"View {number}: the door's top is cut off by the edge of the view")
                continue
            measured = measure_height(splats, shot.view, box)
            if measured is None:
                skipped.append(f"View {number}: too little of the splat inside the door's box")
            elif not typical_height / 2 < measured.height < typical_height * 2:
                skipped.append(
                    f"View {number}: measured {measured.height:.2f} m, too far from a door's height"
                )
            else:
                evidence.append(Evidence(shot.view, number, box, measured))
    factor = None
    if evidence:
        factor = typical_height / statistics.median(item.measured.height for item in evidence)
    return Suggestion(factor, typical_height, evidence, skipped, [shot.png for shot in rendered])
