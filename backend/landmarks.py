"""Landmarks from Qwen's object boxes (#110): a splat room's recognisable objects placed in 3D,
and a camera located from the boxes of the landmarks it sees.

8th Wall moves the phone's view smoothly but drifts, misjudges scale and freezes while lost. Qwen
recognises the room's objects reliably, so a few of them with known places can locate the camera
now and then and correct it (#101). This module is the laptop spike that measures how well.
"""

import itertools
import json
import math
import re
import statistics
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

from backend.boxes import Box, box_format, find_objects
from backend.grab import Vector
from backend.openrouter import OpenRouterClient, Reply
from backend.room_scale import box_depth, room_splats, scan_views
from backend.room_views import (
    RenderedView,
    View,
    ask_about_views,
    point_at,
    project,
    render_views,
)

# A door's top edge is measured at its nearest splats (#33); an object's middle is found at the
# median of the nearer half, which measured 5-10 cm from the test block's middle at any angle.
NEAR_HALF = 0.5


def place_box(splats: list[Vector], view: View, box: Box) -> Vector | None:
    """Where the object in `box` stands in the room: the box's centre, at the depth of the nearer
    half of its splats. None when the box shows too little of the splat."""
    found = box_depth(splats, view, box, NEAR_HALF)
    if found is None:
        return None
    left, top, right, bottom = box
    return point_at(view, (left + right) / 2, (top + bottom) / 2, found[0])


@dataclass(frozen=True)
class Landmark:
    id: str
    label: str
    # Its middle, in room metres.
    centre: Vector
    # How many sightings it was placed from; one sighting is weaker evidence.
    seen: int = 1
    # Other names Qwen gave it, any of which finds it.
    aliases: tuple[str, ...] = ()

    def answers_to(self, label: str) -> bool:
        return label == self.label or label in self.aliases


@dataclass(frozen=True)
class Fix:
    """Where a camera was found to be from the landmarks it saw."""

    position: Vector
    # Its turn about the vertical: 0 faces -z, as the room view starts, and positive turns to +x.
    heading: float
    # The landmarks it was found from.
    landmarks: list[str]
    # How far the landmarks' centres fall from their boxes' centres, as a fraction of the view.
    rms: float
    # How many sightings agreed. Two fit some pose exactly, so a fix from two is unchecked.
    agreeing: int


# A sighting: Qwen's label for an object and its box in the view.
type Sighting = tuple[str, Box]

# The phone is held about this high; this is a gentle preference, so a fix never hangs on it.
HELD_AT = 1.4
HEIGHT_WEIGHT = 0.02
# Box centres are found to a few hundredths of the view: a sighting further than AGREE from its
# landmark is a wrong box, and a fix whose agreeing sightings miss by more than MAX_RMS is wrong.
AGREE = 0.06
MAX_RMS = 0.04
# How far a fix from two landmarks may be from the rough place given: 8th Wall drifts less than this
# between fixes.
NEAR_WITHIN = 1.0
STARTS = 8


def pose_view(
    position: Vector,
    heading: float,
    pitch: float,
    fov_degrees: float = 60.0,
    width: int = 640,
    height: int = 480,
) -> View:
    """The view of a camera at `position`, turned `heading` and tilted `pitch` (up is positive)."""
    x, y, z = position
    ahead = (
        math.sin(heading) * math.cos(pitch),
        math.sin(pitch),
        -math.cos(heading) * math.cos(pitch),
    )
    look_at = (x + ahead[0], y + ahead[1], z + ahead[2])
    return View(position, look_at, fov_degrees, width, height)


def solve_pose(
    sightings: Sequence[Sighting],
    landmarks: Sequence[Landmark],
    pitch: float,
    fov_degrees: float = 60.0,
    width: int = 640,
    height: int = 480,
    near: Vector | None = None,
) -> Fix | None:
    """The camera's position and heading from the boxes of the landmarks it sees, with its tilt
    known (the phone measures it from gravity).

    Qwen's boxes are mostly within a few hundredths of the view, but now and then one is off
    centre or names the wrong object, so the fit is robust: every pair of sightings, matched to
    landmarks every way round (two doors), gives candidate poses; the one most other sightings
    agree with is refitted on those. Three agreeing landmarks fix the pose. Two fit more than one
    pose exactly (on the hallway most such fixes were metres off), so they fix it only within
    NEAR_WITHIN of `near`, a rough place such as 8th Wall's. None otherwise.
    """
    seen = [
        (box, [mark for mark in landmarks if mark.answers_to(label)])
        for label, box in _one_per_box(sightings)
    ]
    seen = [(box, choices) for box, choices in seen if choices]
    if len(seen) < 2:
        return None
    best: tuple[tuple[int, float, float], list[float], list[tuple[Box, Landmark]]] | None = None
    for (box_a, marks_a), (box_b, marks_b) in itertools.combinations(seen, 2):
        for mark_a, mark_b in itertools.product(marks_a, marks_b):
            if mark_a.id == mark_b.id:
                continue
            for pose in _poses(
                [(box_a, mark_a), (box_b, mark_b)], pitch, fov_degrees, width, height
            ):
                view = pose_view(
                    (pose[0], pose[1], pose[2]), pose[3], pitch, fov_degrees, width, height
                )
                agreeing = _agreeing(view, seen)
                if len({mark.id for _, mark in agreeing}) < 2:
                    continue
                misfit = sum(_miss(view, box, mark) for box, mark in agreeing)
                away = math.dist(pose[:3], near) if near else 0.0
                # Most sightings agreeing first; among equals, nearest the rough place, then best.
                score = (len(agreeing), -away, -misfit)
                if best is None or score > best[0]:
                    best = (score, pose, agreeing)
    if best is None:
        return None
    _, start, agreeing = best
    p, _ = _least_squares(_residuals(agreeing, pitch, fov_degrees, width, height), start)
    view = pose_view((p[0], p[1], p[2]), p[3], pitch, fov_degrees, width, height)
    rms = math.sqrt(sum(_miss(view, box, mark) ** 2 for box, mark in agreeing) / len(agreeing))
    if rms > MAX_RMS:
        return None
    # Two sightings fit more than one pose exactly: only the rough place can choose between them.
    if len(agreeing) < 3 and (near is None or math.dist(p[:3], near) > NEAR_WITHIN):
        return None
    heading = math.atan2(math.sin(p[3]), math.cos(p[3]))
    return Fix((p[0], p[1], p[2]), heading, [mark.id for _, mark in agreeing], rms, len(agreeing))


def _poses(
    pairs: list[tuple[Box, Landmark]],
    pitch: float,
    fov_degrees: float,
    width: int,
    height: int,
    keep: int = STARTS,
) -> list[list[float]]:
    """Poses (x, y, z, heading) that fit the boxes to their landmarks, from starts all round
    them, best first: two landmarks fit more than one pose exactly."""
    residuals = _residuals(pairs, pitch, fov_degrees, width, height)

    cx = statistics.mean(mark.centre[0] for _, mark in pairs)
    cz = statistics.mean(mark.centre[2] for _, mark in pairs)
    fitted: list[tuple[float, list[float]]] = []
    for turn in range(STARTS):
        heading = 2 * math.pi * turn / STARTS
        start = [cx - 2.5 * math.sin(heading), HELD_AT, cz + 2.5 * math.cos(heading), heading]
        p, cost = _least_squares(residuals, start)
        if all(math.dist(p[:3], other[:3]) > 0.05 for _, other in fitted):
            fitted.append((cost, p))
    fitted.sort(key=lambda item: item[0])
    return [p for _, p in fitted[:keep]]


def _residuals(
    pairs: list[tuple[Box, Landmark]], pitch: float, fov_degrees: float, width: int, height: int
) -> Callable[[list[float]], list[float]]:
    """How far each landmark's centre falls from its box's centre, across and down, for a pose
    (x, y, z, heading); and, gently, how far the camera is from being held at HELD_AT."""

    def residuals(p: list[float]) -> list[float]:
        view = pose_view((p[0], p[1], p[2]), p[3], pitch, fov_degrees, width, height)
        out: list[float] = []
        for (left, top, right, bottom), mark in pairs:
            seen_at = project(view, mark.centre)
            if seen_at is None:
                out += [1.0, 1.0]
            else:
                out += [seen_at[0] - (left + right) / 2, seen_at[1] - (top + bottom) / 2]
        return [*out, HEIGHT_WEIGHT * (p[1] - HELD_AT)]

    return residuals


def _miss(view: View, box: Box, mark: Landmark) -> float:
    """How far the landmark's centre falls from its box's centre, as a fraction of the view."""
    seen_at = project(view, mark.centre)
    if seen_at is None:
        return math.inf
    return math.dist(seen_at, ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2))


def _agreeing(view: View, seen: list[tuple[Box, list[Landmark]]]) -> list[tuple[Box, Landmark]]:
    """Each sighting whose box a landmark of its label falls near, with that landmark."""
    agreeing: list[tuple[Box, Landmark]] = []
    for box, choices in seen:
        mark = min(choices, key=lambda choice: _miss(view, box, choice))
        if _miss(view, box, mark) < AGREE and all(mark.id != other.id for _, other in agreeing):
            agreeing.append((box, mark))
    return agreeing


def _least_squares(
    residuals: Callable[[list[float]], list[float]], start: list[float], steps: int = 60
) -> tuple[list[float], float]:
    """Levenberg-Marquardt with a numerical Jacobian: the parameters that make the residuals
    smallest, from `start`, and the sum of their squares there."""
    p, damping = list(start), 1e-3
    r = residuals(p)
    cost = sum(v * v for v in r)
    for _ in range(steps):
        columns = []
        for i in range(len(p)):
            nudged = list(p)
            nudged[i] += 1e-6
            columns.append([(a - b) / 1e-6 for a, b in zip(residuals(nudged), r, strict=True)])
        n = len(p)
        normal = [
            [sum(a * b for a, b in zip(columns[i], columns[j], strict=True)) for j in range(n)]
            for i in range(n)
        ]
        gradient = [sum(a * b for a, b in zip(columns[i], r, strict=True)) for i in range(n)]
        while damping < 1e8:
            damped = [
                [normal[i][j] + (damping * normal[i][i] if i == j else 0) for j in range(n)]
                for i in range(n)
            ]
            step = _solve(damped, [-g for g in gradient])
            trial = [a + b for a, b in zip(p, step, strict=True)] if step else p
            trial_r = residuals(trial)
            trial_cost = sum(v * v for v in trial_r)
            if step and trial_cost < cost:
                p, r, cost, damping = trial, trial_r, trial_cost, damping / 10
                break
            damping *= 10
        else:
            break
        if cost < 1e-14:
            break
    return p, cost


def _solve(matrix: list[list[float]], vector: list[float]) -> list[float] | None:
    """x with matrix x = vector, by Gaussian elimination; None when the matrix is singular."""
    n = len(vector)
    rows = [[*matrix[i], vector[i]] for i in range(n)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda row: abs(rows[row][col]))
        if abs(rows[pivot][col]) < 1e-15:
            return None
        rows[col], rows[pivot] = rows[pivot], rows[col]
        for row in range(n):
            if row != col:
                factor = rows[row][col] / rows[col][col]
                rows[row] = [a - factor * b for a, b in zip(rows[row], rows[col], strict=True)]
    return [rows[i][n] / rows[i][i] for i in range(n)]


# Sightings of one label placed closer than this are one object (about a door's width: its middle
# is placed 0.6 m apart from different views); under different labels they must
# be at the same place (a sink 0.5 m below a mirror is two objects).
MERGE_DISTANCE = 0.8
SAME_PLACE = 0.25
# Boxes overlapping this much are one object named twice.
SAME_BOX = 0.8
LANDMARKS_FILE = "landmarks.json"


@dataclass(frozen=True)
class PlacedSighting:
    """A box Qwen gave in one of the map's views, and where it placed the object; None when the
    box held too little of the splat."""

    view_number: int
    label: str
    box: Box
    point: Vector | None


@dataclass(frozen=True)
class LandmarkMap:
    landmarks: list[Landmark]
    sightings: list[PlacedSighting]
    views: list[View]
    # The views as PNGs, for the evidence.
    pngs: list[bytes]


def build_landmarks(
    room_dir: Path,
    client: OpenRouterClient,
    on_reply: Callable[[Reply, str | None], None],
    labels: Sequence[str],
    views: list[View] | None = None,
) -> LandmarkMap:
    """Ask Qwen for the labelled objects in each view, place each box in the room, and merge the
    sightings of one object into one landmark at their median."""
    views = views or scan_views(room_dir)
    rendered = render_views(room_dir, views)
    splats = room_splats(room_dir)
    question, answer = find_objects(labels), box_format(labels)
    sightings: list[PlacedSighting] = []
    for number, shot in enumerate(rendered, start=1):
        for label, box in ask_about_views(client, [shot], question, answer, on_reply):
            sightings.append(PlacedSighting(number, label, box, place_box(splats, shot.view, box)))
    return LandmarkMap(_merged(sightings), sightings, views, [shot.png for shot in rendered])


def _merged(sightings: list[PlacedSighting]) -> list[Landmark]:
    """Sightings of one label close together are one object. So are sightings under different
    labels at the same place: Qwen named the hallway's cupboard both a door and a cupboard."""
    groups: list[tuple[list[str], list[Vector]]] = []
    for sighting in sightings:
        if sighting.point is None:
            continue
        for labels, points in groups:
            apart = math.dist(_middle(points), sighting.point)
            if apart < (MERGE_DISTANCE if sighting.label in labels else SAME_PLACE):
                points.append(sighting.point)
                if sighting.label not in labels:
                    labels.append(sighting.label)
                break
        else:
            groups.append(([sighting.label], [sighting.point]))
    landmarks: list[Landmark] = []
    for (label, *aliases), points in groups:
        slug = re.sub(r"[^a-z0-9]+", "_", label.casefold()).strip("_")
        same = sum(mark.label == label for mark in landmarks)
        name = slug if same == 0 else f"{slug}_{same + 1}"
        landmarks.append(Landmark(name, label, _middle(points), len(points), tuple(aliases)))
    return landmarks


def _middle(points: list[Vector]) -> Vector:
    x, y, z = (statistics.median(point[i] for point in points) for i in range(3))
    return x, y, z


def save_landmarks(room_dir: Path, landmarks: list[Landmark]) -> None:
    data = {"landmarks": [asdict(mark) for mark in landmarks]}
    (room_dir / LANDMARKS_FILE).write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def load_landmarks(room_dir: Path) -> list[Landmark]:
    data = json.loads((room_dir / LANDMARKS_FILE).read_text(encoding="utf-8"))
    return [
        Landmark(
            item["id"], item["label"], tuple(item["centre"]), item["seen"], tuple(item["aliases"])
        )
        for item in data["landmarks"]
    ]


@dataclass(frozen=True)
class Located:
    # None when too few landmarks were seen, or they did not fit together.
    fix: Fix | None
    sightings: list[Sighting]


def locate(
    client: OpenRouterClient,
    on_reply: Callable[[Reply, str | None], None],
    shot: RenderedView,
    landmarks: list[Landmark],
    pitch: float,
) -> Located:
    """Where the camera that took `shot` was, from Qwen's boxes for the map's landmarks."""
    labels = sorted({mark.label for mark in landmarks})
    sightings = ask_about_views(client, [shot], find_objects(labels), box_format(labels), on_reply)
    view = shot.view
    fix = solve_pose(sightings, landmarks, pitch, view.fov_degrees, view.width, view.height)
    return Located(fix, sightings)


def _one_per_box(sightings: Sequence[Sighting]) -> list[Sighting]:
    """The sightings without repeats: one object Qwen named twice has two near-identical boxes."""
    kept: list[Sighting] = []
    for label, box in sightings:
        if all(_overlap(box, other) < SAME_BOX for _, other in kept):
            kept.append((label, box))
    return kept


def _overlap(a: Box, b: Box) -> float:
    """How much two boxes overlap: their intersection over their union."""
    width = min(a[2], b[2]) - max(a[0], b[0])
    height = min(a[3], b[3]) - max(a[1], b[1])
    if width <= 0 or height <= 0:
        return 0.0
    shared = width * height
    return shared / ((a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - shared)
