"""Render-and-ask (#98): views of a splat room from any viewpoint, for Qwen to look at.

`render_views` draws a prepared room's splat, placed as its manifest says, from each `View` in
room metres: the frame the devices use. It runs Spark, the renderer the devices use, in a headless
browser (`frontend/scripts/render-views.mjs`), so it needs Node and a built frontend but no GPU.
The helpers `orbit`, `filmed`, `standing` and `overhead` choose views.

`ask_about_views` then asks Qwen a question about one to seven rendered views through the
OpenRouter adapter, with its answer formats, bounded repairs and failure kinds. The caller records
each reply, with its tokens and cost, through `on_reply`, as `ask` does.
"""

import json
import math
import shutil
import subprocess
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

from backend.grab import Vector, rotate
from backend.openrouter import (
    AnswerFormat,
    OpenRouterClient,
    Picture,
    Reply,
    Unreadable,
    ask,
    say,
    without_thinking,
)
from backend.prepared_room import PreparedRoomError, SplatPlacement, load_prepared_room

FRONTEND = Path(__file__).resolve().parents[1] / "frontend"
RENDER_SCRIPT = FRONTEND / "scripts" / "render-views.mjs"
RENDER_TIMEOUT_SECONDS = 600


@dataclass(frozen=True)
class View:
    """A camera at `position`, looking at `look_at`, with a vertical field of view."""

    position: Vector
    look_at: Vector
    fov_degrees: float = 60.0
    width: int = 640
    height: int = 480


@dataclass(frozen=True)
class RenderedView:
    view: View
    png: bytes
    # Time to draw this view, once the splat was loaded.
    seconds: float


def _camera_axes(view: View) -> tuple[Vector, Vector, Vector]:
    """The view's forward, right and up directions, as the render page's camera has them."""
    f = _unit(_minus(view.look_at, view.position))
    # Looking straight up or down, "up" on screen is the room's -z (see `frontend/src/render.ts`).
    up = (0.0, 0.0, -1.0) if abs(f[1]) > 0.999 else (0.0, 1.0, 0.0)
    right = _unit(_cross(f, up))
    return f, right, _cross(right, f)


def project(view: View, point: Vector) -> tuple[float, float] | None:
    """Where `point` appears in the view, as fractions of its width and height from the top
    left; None when it is behind the camera."""
    forward, right, up = _camera_axes(view)
    offset = _minus(point, view.position)
    depth = _dot(offset, forward)
    if depth <= 0:
        return None
    half_height = math.tan(math.radians(view.fov_degrees) / 2)
    half_width = half_height * view.width / view.height
    x = _dot(offset, right) / (depth * half_width)
    y = _dot(offset, up) / (depth * half_height)
    return (x + 1) / 2, (1 - y) / 2


def _minus(a: Vector, b: Vector) -> Vector:
    return a[0] - b[0], a[1] - b[1], a[2] - b[2]


def _dot(a: Vector, b: Vector) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a: Vector, b: Vector) -> Vector:
    return a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]


def _unit(a: Vector) -> Vector:
    length = math.sqrt(_dot(a, a))
    return a[0] / length, a[1] / length, a[2] / length


def orbit(
    target: Vector, distance: float, count: int = 3, height: float | None = None
) -> list[View]:
    """`count` views around `target`, `distance` away across the floor, all looking at it.

    The cameras stand at `height` (the target's own height by default), the first on the
    target's +z side and the rest evenly round it, counterclockwise seen from above.
    """
    x, y, z = target
    eye = y if height is None else height
    return [
        View(
            position=(
                x + distance * math.sin(2 * math.pi * i / count),
                eye,
                z + distance * math.cos(2 * math.pi * i / count),
            ),
            look_at=target,
        )
        for i in range(count)
    ]


def overhead(target: Vector, height: float = 2.5) -> View:
    """Looking straight down on `target` from `height` above the floor; up on screen is -z."""
    return View(position=(target[0], height, target[2]), look_at=target)


# A standing adult's eyes; the VR solver's real height varies, the room's scale does not.
EYE_HEIGHT = 1.6


def standing(spot: tuple[float, float], look_at: Vector, eye_height: float = EYE_HEIGHT) -> View:
    """What a player standing at `spot` (x, z on the floor) sees when looking at `look_at`."""
    return View(position=(spot[0], eye_height, spot[1]), look_at=look_at)


def placed(placement: SplatPlacement, point: Sequence[float]) -> Vector:
    """A point in the splat's own frame, moved as the splat is: scaled, rotated, then moved."""
    turn, lift, scale = placement.rotation, placement.position, placement.scale
    x, y, z = rotate(
        (turn.x, turn.y, turn.z, turn.w), (scale * point[0], scale * point[1], scale * point[2])
    )
    return x + lift.x, y + lift.y, z + lift.z


def point_at(view: View, x: float, y: float, depth: float) -> Vector:
    """The point seen at fractions (x, y) of the view, `depth` metres in front of the camera."""
    forward, right, up = _camera_axes(view)
    half_height = math.tan(math.radians(view.fov_degrees) / 2)
    half_width = half_height * view.width / view.height
    across, rise = (2 * x - 1) * half_width * depth, (1 - 2 * y) * half_height * depth
    px, py, pz = (
        view.position[i] + depth * forward[i] + across * right[i] + rise * up[i] for i in range(3)
    )
    return px, py, pz


def filmed(room_dir: Path) -> list[View]:
    """The views the room's video was filmed from, from the notebook's `report.json`, if any.

    The notebook records each camera in the splat's own frame, so each is moved by the
    manifest's splat placement, as the splat is: scaled, then rotated, then moved.
    """
    report = room_dir / "report.json"
    if not report.is_file():
        return []
    placement = load_prepared_room(room_dir).splat_placement
    if placement is None:
        return []
    turn = placement.rotation
    q = (turn.x, turn.y, turn.z, turn.w)
    views: list[View] = []
    for camera in json.loads(report.read_text(encoding="utf-8")).get("cameras", []):
        position = placed(placement, tuple(camera["position"]))
        forward = rotate(q, tuple(camera["forward"]))
        look_at = (position[0] + forward[0], position[1] + forward[1], position[2] + forward[2])
        views.append(View(position=position, look_at=look_at))
    return views


class RenderFailure(Exception):
    """The views could not be rendered; the message says why."""


def render_views(room_dir: Path, views: Sequence[View]) -> list[RenderedView]:
    """Each view of the prepared room's splat, as a PNG."""
    try:
        room = load_prepared_room(room_dir)
    except PreparedRoomError as exc:
        raise RenderFailure(str(exc)) from exc
    if room.splat_url is None or room.splat_placement is None:
        raise RenderFailure("The prepared room has no splat to render.")
    dist = FRONTEND / "dist"
    if not (dist / "render.html").is_file():
        raise RenderFailure("The render page is not built: run `npm run build` in frontend.")
    node = shutil.which("node")
    if node is None:
        raise RenderFailure("Rendering room views needs Node.js, which was not found.")
    with tempfile.TemporaryDirectory(prefix="room-views-") as out:
        request = {
            "dist": str(dist),
            "room_dir": str(room_dir.resolve()),
            "splat": room.splat_url.rsplit("/", 1)[-1],
            "placement": room.splat_placement.model_dump(),
            "views": [asdict(view) for view in views],
            "out_dir": out,
        }
        try:
            result = subprocess.run(
                [node, str(RENDER_SCRIPT)],
                input=json.dumps(request),
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=RENDER_TIMEOUT_SECONDS,
                cwd=FRONTEND,
            )
        except subprocess.TimeoutExpired as exc:
            raise RenderFailure(f"Rendering took over {RENDER_TIMEOUT_SECONDS} s.") from exc
        if result.returncode != 0:
            raise RenderFailure(f"Rendering failed: {result.stderr.strip() or 'no reason given'}")
        rendered = json.loads(result.stdout)["views"]
        return [
            RenderedView(view, Path(item["file"]).read_bytes(), item["seconds"])
            for view, item in zip(views, rendered, strict=True)
        ]


MAX_SHORT_ANSWER = 120


def read_short_answer(text: str) -> str:
    """One line of a few words, such as an object's name."""
    answer = without_thinking(text).strip()
    if not answer:
        raise Unreadable("the answer is empty")
    if "\n" in answer or len(answer) > MAX_SHORT_ANSWER:
        raise Unreadable("the answer is longer than one short line")
    return answer


# Added to a question for a short answer: unasked, Qwen explains at length (seen on 26 October).
SHORT_ANSWER_REQUEST = "Answer in one short line of a few words, with no explanation."
# A few words, for questions such as "what object is at the centre of this view?".
SHORT_ANSWER = AnswerFormat(
    "short answer",
    read_short_answer,
    f"Your answer did not follow the format. {SHORT_ANSWER_REQUEST}",
)


def ask_about_views[T](
    client: OpenRouterClient,
    views: Sequence[RenderedView],
    question: str,
    answer: AnswerFormat[T],
    on_reply: Callable[[Reply, str | None], None],
) -> T:
    """Qwen's answer to `question` about the views, each labelled "View n", in `answer`'s format."""
    limit = client.config.max_images
    if not 1 <= len(views) <= limit:
        raise ValueError(f"Qwen is asked about 1 to {limit} views at a time, not {len(views)}.")
    parts: list[Picture | str] = []
    for number, view in enumerate(views, start=1):
        parts += [f"View {number}:", Picture.from_png(view.png, client.config.max_image_side)]
    parts.append(question)
    return ask(client, [say("user", *parts)], answer, on_reply)
