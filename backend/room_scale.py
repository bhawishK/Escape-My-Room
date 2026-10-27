"""Room scale from objects of known size (#33).

A splat room's scale is first guessed from the camera height the notebook assumes (1.4 m), which
was 10-25% off in our rooms. Here Qwen finds doors in views rendered from the room
(render-and-ask, #98), the splat measures how tall each one is, and the suggested scale makes them
as tall as a typical interior door. The master confirms it, gives a measured height instead, or
keeps the approximation (`backend/room_scale_check.py`).
"""

import math
import statistics
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from backend.boxes import Box, read_boxes
from backend.grab import Vector
from backend.openrouter import AnswerFormat, OpenRouterClient, Reply
from backend.prepared_room import load_prepared_room
from backend.room_views import (
    View,
    ask_about_views,
    depth,
    filmed,
    in_room,
    point_at,
    project,
    render_views,
)
from backend.splat_file import visible_splats

# A typical interior door: 2.03 m (6 ft 8 in) in the US, 1.98-2.04 m in Europe.
DOOR_HEIGHT = 2.03

FIND_DOORS = (
    "Find every door a person walks through in this image, open or closed: room, hall and "
    "entrance doors, not cupboard, wardrobe or cabinet doors. "
    'Output ONLY a JSON list like [{"label": "door", "bbox_2d": [x1, y1, x2, y2]}], with '
    "coordinates from 0 to 1000 relative to the image width and height. "
    "Output [] if there is no door."
)

# A box's sides often take in the door frame and the wall; its middle is the door itself.
SIDE_MARGIN = 0.2
MIN_SPLATS = 20
# The nearest quarter of what a box shows is the object; further splats show through or past it.
NEAR_SHARE = 0.25
# A box this close to the top of the view may have lost the door's top edge.
CUT_OFF = 0.01
# Eye height of the scan views: a whole door fits in their 80 degrees from a step or two away.
SCAN_EYE = 1.1


def room_splats(room_dir: Path) -> list[Vector]:
    """The centres of the room's visible splats, placed in the room as the devices place them."""
    room = load_prepared_room(room_dir)
    if room.splat_url is None or room.splat_placement is None:
        raise ValueError("The prepared room has no splat.")
    placement = room.splat_placement
    path = room_dir / room.splat_url.rsplit("/", 1)[-1]
    return [in_room(placement, point) for point in visible_splats(path)]


@dataclass(frozen=True)
class Measurement:
    # How far the object's top is above the floor (y = 0), in room metres.
    height: float
    # How far in front of the camera it was measured.
    depth: float
    # How many splats the box held.
    splats: int


def box_depth(
    splats: list[Vector], view: View, box: Box, near_share: float = NEAR_SHARE
) -> tuple[float, int] | None:
    """How far in front of the camera the object in `box` is, and how many splats the box's
    middle held; None when it held too few to tell. The depth is the median of the nearest
    `near_share` of them: further splats show past or through the object."""
    left, top, right, bottom = box
    inset = (right - left) * SIDE_MARGIN
    depths: list[float] = []
    for point in splats:
        seen = project(view, point)
        if seen and left + inset <= seen[0] <= right - inset and top <= seen[1] <= bottom:
            depths.append(depth(view, point))
    if len(depths) < MIN_SPLATS:
        return None
    depths.sort()
    return statistics.median(depths[: max(1, int(len(depths) * near_share))]), len(depths)


def measure_height(splats: list[Vector], view: View, box: Box) -> Measurement | None:
    """How high the top edge of the object in `box` is above the floor, or None when the box
    shows too little of the splat to measure."""
    found = box_depth(splats, view, box)
    if found is None:
        return None
    ahead, count = found
    left, top, right, _ = box
    top_point = point_at(view, (left + right) / 2, top, ahead)
    return Measurement(height=top_point[1], depth=ahead, splats=count)


def read_door_boxes(text: str) -> list[Box]:
    """Qwen's door boxes, as fractions of the view; its coordinates run from 0 to 1000."""
    return [box for _, box in read_boxes(text, ["door"])]


DOOR_BOXES = AnswerFormat(
    "door boxes",
    read_door_boxes,
    "Your answer did not follow the format. Output ONLY a JSON list like "
    '[{"label": "door", "bbox_2d": [x1, y1, x2, y2]}] with coordinates from 0 to 1000, '
    "or [] if there is no door.",
)


@dataclass(frozen=True)
class Door:
    """A door Qwen found: measured, or with the reason it was not."""

    # Which of the views it was seen in, counted from 1.
    view_number: int
    box: Box
    measured: Measurement | None
    skipped: str | None = None


@dataclass(frozen=True)
class Suggestion:
    # Multiply the room's scale by this; None when no door could be measured.
    factor: float | None
    typical_height: float
    doors: list[Door]
    views: list[View]
    # Every view looked at, as PNGs, for the master to check.
    pngs: list[bytes]

    @property
    def measured(self) -> list[Door]:
        return [door for door in self.doors if door.skipped is None]


def scan_views(room_dir: Path) -> list[View]:
    """Eight level views round each place the room was filmed from.

    The places are the first, middle and last filmed cameras, or the origin when the room keeps no
    record of its filming: the walk is centred there. Away from the filming the splat has gaps,
    and its floor, sized to every splat, can reach well outside the room.
    """
    cameras = filmed(room_dir)
    picks = sorted({0, len(cameras) // 2, len(cameras) - 1}) if cameras else []
    return views_round(
        [(cameras[i].position[0], cameras[i].position[2]) for i in picks] or [(0.0, 0.0)]
    )


def views_round(spots: list[tuple[float, float]]) -> list[View]:
    """Eight level views round each spot (x, z on the floor), wide enough to see a whole door
    from a step or two away."""
    return [
        View(
            position=(x, SCAN_EYE, z),
            look_at=(x + math.sin(turn), SCAN_EYE, z - math.cos(turn)),
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
    doors: list[Door] = []
    for number, shot in enumerate(rendered, start=1):
        for box in ask_about_views(client, [shot], FIND_DOORS, DOOR_BOXES, on_reply):
            doors.append(_measured_door(splats, shot.view, number, box, typical_height))
    heights = [door.measured.height for door in doors if door.measured and not door.skipped]
    factor = typical_height / statistics.median(heights) if heights else None
    return Suggestion(factor, typical_height, doors, views, [shot.png for shot in rendered])


def _measured_door(
    splats: list[Vector], view: View, number: int, box: Box, typical_height: float
) -> Door:
    if box[1] < CUT_OFF:
        return Door(number, box, None, "its top is cut off by the edge of the view")
    measured = measure_height(splats, view, box)
    if measured is None:
        return Door(number, box, None, "too little of the splat inside its box")
    if not typical_height / 2 < measured.height < typical_height * 2:
        return Door(number, box, measured, "too far from a door's height")
    return Door(number, box, measured)
