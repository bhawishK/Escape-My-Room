"""Hazards made from a picture (#222, part of #221): a video of the hazard, then its 3D animation.

The furniture generator's jobs (#186) extended with two steps. A hazard's target is either an
object already in the room, whose picture is cut from the room's own splat (#223), or a new
object, whose picture is drawn from words as furniture's is. The picture becomes a short video of
the hazard (Wan 2.2, #224) and the video a sequence of 3D Gaussian splat frames (L4GM, #226).

A job goes queued → image_ready → video_ready → ready, one at a time in the order asked. Each
step's output is kept, so a failed step still shows what came before it. A finished hazard's
frames are kept with the server's data.
"""

import os
import re
import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, model_serializer, model_validator

from backend.furniture_generation import (
    DEFAULT_TIMEOUT_SECONDS,
    GenerationError,
    Generator,
    run_step,
)
from backend.hazard_placement import Box, Placement, place, true_size_box
from backend.splat_frames import check, prune, read_frame, to_spz
from backend.video_gate import gate, read_frames

HazardState = Literal["queued", "image_ready", "video_ready", "ready", "failed", "cancelled"]
# States a job can still be cancelled in.
GOING: tuple[HazardState, ...] = ("queued", "image_ready", "video_ready")
# The frame rate L4GM's frames keep: the video's (#226).
FRAMES_PER_SECOND = 16.0
ASSET_ID = re.compile(r"hz_[0-9a-f]{8}")
JOB_ID = re.compile(r"[0-9a-f]{12}")


class HazardTarget(BaseModel):
    """What the hazard happens to: an object in the room (`entity`) or a new one (`description`)."""

    entity: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_]{0,31}$")
    description: str | None = Field(default=None, min_length=3, max_length=200)

    @model_validator(mode="after")
    def one_of(self) -> "HazardTarget":
        if (self.entity is None) == (self.description is None):
            raise ValueError("Name an object in the room (entity) or describe a new one, not both.")
        return self

    @model_serializer
    def only_the_one_given(self) -> dict[str, str]:
        """Shown as it was asked for: `{"entity": ...}` or `{"description": ...}`."""
        return (
            {"entity": self.entity}
            if self.entity is not None
            else {"description": self.description or ""}
        )


class HazardRequest(BaseModel):
    target: HazardTarget
    # What happens to it, as the video is asked for: "catches fire".
    hazard: str = Field(min_length=3, max_length=120)
    # Where on the floor (x, z) a new object stands; an object in the room stays where it is.
    at: tuple[float, float] = (0.0, 0.0)


class HazardAsset(BaseModel):
    """A finished hazard: its frames, served at `frame_url` with `{n}` the frame's number."""

    id: str
    target: HazardTarget
    hazard: str
    frames: int
    frames_per_second: float
    frame_url: str
    # How like its video the 4D result looked, at its start, middle and end (#227).
    check: list[float] = Field(default_factory=lambda: [])
    # All its frames, as served (SPZ), in bytes.
    size_bytes: int = 0
    # Where the frames go in the room, and the object they replace (#228).
    placement: Placement | None = None
    # How long it plays, and whether it starts again; a hazard plays once and holds its end.
    seconds: float = 0.0
    loops: bool = False
    # The live room's folder it was made in (#234): a fire on a room object is reused only there.
    room: str | None = None


class HazardJob(BaseModel):
    id: str
    target: HazardTarget
    hazard: str
    state: HazardState = "queued"
    error: str | None = None
    image_url: str | None = None
    video_url: str | None = None
    # The quality gate's measures for each video candidate, and which it chose (#225).
    video_check: dict[str, object] | None = None
    asset: HazardAsset | None = None
    # Where a new object stands (from the request).
    at: tuple[float, float] = (0.0, 0.0)
    # The live room's folder when the job started, for an object in the room.
    room: str | None = None


@dataclass(frozen=True)
class RoomPicture:
    """An object in the room pictured (#223): the picture, the object's box, and the floor
    direction from the object towards where the picture was taken from."""

    png: bytes
    box: Box
    facing: tuple[float, float]


# What every hazard video is also asked for (#224): the 4D step needs a still camera, the same
# object and a plain background (spike #220). The hazard is only filled in before it.
VIDEO_TEMPLATE = (
    "the {name} {hazard}; static camera, fixed viewpoint, the {name} itself does not change "
    "shape or move, the plain white background stays white and still"
)
# Each hazard's video is made this many times, with these seeds; the quality gate (#225) keeps
# the better. Each one uses video quota.
VIDEO_SEEDS = (7, 11, 23, 41)


def video_prompt(name: str, hazard: str) -> str:
    """What the video is asked to show: the hazard, then the fixed wording the quality needs."""
    return VIDEO_TEMPLATE.format(name=name, hazard=hazard.strip().rstrip(".;,"))


def video_candidates() -> int:
    """How many videos each hazard makes (ESCAPE_ROOM_HAZARD_VIDEO_CANDIDATES, default 2)."""
    chosen = int(os.environ.get("ESCAPE_ROOM_HAZARD_VIDEO_CANDIDATES") or 2)
    return max(1, min(len(VIDEO_SEEDS), chosen))


def no_room_picture(entity_id: str) -> RoomPicture:
    """Until #223 cuts pictures from the room's splat, a room object has none."""
    raise GenerationError("room_picture")


class HazardGeneration:
    """Hazard jobs, one at a time in the order asked, and the hazards they made."""

    def __init__(
        self,
        root: Path,
        generator: Generator | None,
        room_picture: Callable[[str], RoomPicture] = no_room_picture,
        object_name: Callable[[str], str] = lambda entity_id: entity_id.replace("_", " "),
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        room_name: Callable[[], str | None] = lambda: None,
        on_finished: Callable[[HazardJob], None] = lambda job: None,
    ) -> None:
        self.root = root
        self.generator = generator
        # The live room's folder, recorded with each fire made on one of its objects (#234).
        self.room_name = room_name
        # Called from the job's thread when a job ends: ready, failed or cancelled.
        self.on_finished = on_finished
        # The picture of an object in the room, and its name for the video prompt.
        self.room_picture = room_picture
        self.object_name = object_name
        self.timeout = timeout
        self.jobs: dict[str, HazardJob] = {}
        self.lock = threading.Lock()
        self.pending: list[str] = []
        self.wake = threading.Condition(self.lock)
        threading.Thread(target=self._run, daemon=True, name="hazard-jobs").start()

    @property
    def available(self) -> bool:
        return self.generator is not None

    def start(self, request: HazardRequest) -> HazardJob:
        job = HazardJob(
            id=uuid.uuid4().hex[:12],
            target=request.target,
            hazard=request.hazard.strip(),
            at=request.at,
            room=self.room_name() if request.target.entity is not None else None,
        )
        with self.lock:
            self.jobs[job.id] = job
            self.pending.append(job.id)
            self.wake.notify()
        return job.model_copy()

    def get(self, job_id: str) -> HazardJob | None:
        with self.lock:
            job = self.jobs.get(job_id)
            return None if job is None else job.model_copy()

    def cancel(self, job_id: str) -> HazardJob | None:
        """Stop a job that hasn't finished: it ends cancelled, and no hazard is kept."""
        with self.lock:
            job = self.jobs.get(job_id)
            if job is None:
                return None
            if job.state in GOING:
                job.state = "cancelled"
                if job_id in self.pending:
                    self.pending.remove(job_id)
            return job.model_copy()

    def cached(self, room: str, entity: str, hazard: str) -> HazardAsset | None:
        """The newest fire already made for `entity` in `room` with this hazard, if any (#234)."""
        found: list[tuple[float, HazardAsset]] = []
        for path in (self.root / "hazards").glob("hz_*/hazard.json"):
            try:
                asset = HazardAsset.model_validate_json(path.read_text(encoding="utf-8"))
                made = path.stat().st_mtime
            except (OSError, ValueError):
                continue
            same = asset.room == room and asset.target.entity == entity
            if same and asset.hazard == hazard.strip() and asset.placement is not None:
                found.append((made, asset))
        return max(found, key=lambda pair: pair[0])[1] if found else None

    def file(self, job_id: str, name: Literal["picture.png", "video.mp4"]) -> Path | None:
        if not JOB_ID.fullmatch(job_id):
            return None
        path = self.root / "jobs" / job_id / name
        return path if path.is_file() else None

    def asset(self, asset_id: str) -> HazardAsset | None:
        """A finished hazard kept on the server, or None if there is none by that id."""
        if not ASSET_ID.fullmatch(asset_id):
            return None
        path = self.root / "hazards" / asset_id / "hazard.json"
        try:
            return HazardAsset.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def frame(self, asset_id: str, number: int) -> Path | None:
        if not ASSET_ID.fullmatch(asset_id) or number < 0:
            return None
        path = self.root / "hazards" / asset_id / "frames" / f"{number:03d}.spz"
        return path if path.is_file() else None

    def _run(self) -> None:
        while True:
            with self.lock:
                while not self.pending:
                    self.wake.wait()
                job_id = self.pending.pop(0)
            try:
                self._make(job_id)
            except Exception:  # noqa: BLE001 - one bad job must never stop the ones after it
                self._fail(job_id, "The hazard couldn't be made. Try again.")
            finished = self.get(job_id)
            if finished is not None and finished.state not in GOING:
                self.on_finished(finished)

    def _still(self, job_id: str, state: HazardState) -> bool:
        with self.lock:
            return self.jobs[job_id].state == state

    def _advance(self, job_id: str, before: HazardState, after: HazardState, **fields: str) -> bool:
        """Move the job on a step, unless it was cancelled meanwhile."""
        with self.lock:
            current = self.jobs[job_id]
            if current.state != before:
                return False
            current.state = after
            for name, value in fields.items():
                setattr(current, name, value)
            return True

    def _make(self, job_id: str) -> None:
        generator = self.generator
        job = self.get(job_id)
        if generator is None or job is None or job.state != "queued":
            return
        folder = self.root / "jobs" / job_id
        folder.mkdir(parents=True, exist_ok=True)
        target = job.target
        try:
            if target.entity is not None:
                entity = target.entity
                pictured = run_step(lambda: self.room_picture(entity), "room_picture", self.timeout)
                picture, box, facing, hide = pictured.png, pictured.box, pictured.facing, entity
                name = self.object_name(entity)
            else:
                description = target.description or ""
                picture = run_step(lambda: generator.image(description), "image", self.timeout)
                box, facing, hide = true_size_box(description, job.at), (0.0, 1.0), None
                name = description
            (folder / "picture.png").write_bytes(picture)
            if not self._advance(
                job_id, "queued", "image_ready", image_url=f"/api/hazards/jobs/{job_id}/image"
            ):
                return
            prompt = video_prompt(name, job.hazard)
            videos: list[bytes] = []
            first_failure: GenerationError | None = None
            for number, seed in enumerate(VIDEO_SEEDS[: video_candidates()]):
                try:
                    made = run_step(
                        lambda seed=seed: generator.video(picture, prompt, seed),
                        "video",
                        self.timeout,
                    )
                except GenerationError as exc:
                    if exc.reason == "quota":
                        raise
                    first_failure = first_failure or exc
                    continue
                (folder / f"video-{number}.mp4").write_bytes(made)
                videos.append(made)
                if not self._still(job_id, "image_ready"):
                    return
            if not videos:
                raise first_failure or GenerationError("video")
            # The quality gate (#225) keeps the best candidate, trimmed and on white.
            checked = run_step(lambda: gate(videos, picture), "video_gate", self.timeout)
            video = checked.video
            (folder / "video.mp4").write_bytes(video)
            with self.lock:
                self.jobs[job_id].video_check = {
                    "chosen": checked.chosen,
                    "candidates": checked.candidates,
                }
            if not self._advance(
                job_id, "image_ready", "video_ready", video_url=f"/api/hazards/jobs/{job_id}/video"
            ):
                return
            frames = run_step(lambda: generator.animate(video), "animate", self.timeout)
            if len(frames) < 2:
                raise GenerationError("animate")
            # Checked against its video, then made light for phones (#227).
            try:
                splats = [read_frame(frame) for frame in frames]
            except (ValueError, StopIteration) as exc:
                raise GenerationError("animate") from exc
            scores = check(splats, read_frames(video))
            placement = place(splats[0], box, facing, hide)
            frames = [to_spz(prune(splat)) for splat in splats]
            asset_id = f"hz_{uuid.uuid4().hex[:8]}"
            kept = self.root / "hazards" / asset_id
            (kept / "frames").mkdir(parents=True, exist_ok=True)
            for number, frame in enumerate(frames):
                (kept / "frames" / f"{number:03d}.spz").write_bytes(frame)
            asset = HazardAsset(
                id=asset_id,
                target=target,
                hazard=job.hazard,
                frames=len(frames),
                frames_per_second=FRAMES_PER_SECOND,
                frame_url=f"/api/hazards/{asset_id}/frames/{{n}}.spz",
                check=scores,
                size_bytes=sum(len(frame) for frame in frames),
                placement=placement,
                seconds=round(len(frames) / FRAMES_PER_SECOND, 3),
                room=job.room,
            )
            (kept / "hazard.json").write_text(asset.model_dump_json(indent=2), encoding="utf-8")
            with self.lock:
                current = self.jobs[job_id]
                if current.state != "video_ready":
                    return
                current.state = "ready"
                current.asset = asset
        except GenerationError as exc:
            self._fail(job_id, exc.message)
        except OSError:
            self._fail(job_id, "The hazard couldn't be saved on the server.")

    def _fail(self, job_id: str, message: str) -> None:
        """End a job that is still going as failed; a cancelled or finished one stays so."""
        with self.lock:
            current = self.jobs[job_id]
            if current.state in GOING:
                current.state = "failed"
                current.error = message
