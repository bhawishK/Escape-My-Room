"""Room preparation jobs: turn a saved capture into a candidate room, one job at a time.

A job is a durable record under `<data>/jobs/<job id>/job.json`, rewritten atomically on every
change. One background thread runs queued jobs in order, so request handlers and the shared-room
lock never wait for a worker. A worker runs named stages and then yields a candidate prepared
room; the candidate is inspected here and never replaces the active room.

The only worker so far is the deterministic fixture worker. It is a test configuration chosen by
server settings, and everything it produces is labelled as fixture output, not AI inference.
"""

import hashlib
import json
import os
import queue
import re
import secrets
import threading
import time
from pathlib import Path, PurePosixPath
from typing import Literal, Protocol, Self

from pydantic import Field

from backend.captures import CaptureStore
from backend.errors import Refusal
from backend.prepared_room import LoadedRoom, PreparedRoomError, load_prepared_room
from backend.protocol import WireModel
from backend.records import RecordFolder, StoredRecord, now, seconds_between

JOB_ID = re.compile(r"^job_[0-9a-f]{32}$")
FIXTURE_LABEL = "Fixture output, not AI inference"

type StageName = Literal["scene_understanding", "geometry", "stabilization", "export"]
type JobState = Literal["queued", "running", "awaiting_review", "failed"]
# `fixture` is a failure the fixture worker was configured to produce; `worker` is an unexpected
# crash inside a worker; `interrupted` is a job a service restart cut off.
type ErrorKind = Literal[
    "configuration",
    "resource",
    "provider",
    "inference",
    "validation",
    "fixture",
    "worker",
    "interrupted",
]
type ArtifactMediaType = Literal["application/json", "model/gltf-binary"]


def stage_title(stage: StageName) -> str:
    return stage.replace("_", " ")


class PreparationError(Refusal):
    """A preparation request cannot be accepted; the message is shown to the user."""


class Artifact(WireModel):
    """A file a stage produced, relative to the job folder."""

    path: str
    media_type: ArtifactMediaType
    description: str
    size_bytes: int


class Stage(WireModel):
    name: StageName
    status: Literal["pending", "running", "done", "failed"] = "pending"
    started_at: str | None = None
    finished_at: str | None = None
    # While a stage runs, this is the time so far.
    elapsed_seconds: float | None = None
    artifacts: list[Artifact] = Field(default_factory=lambda: list[Artifact]())


class JobError(WireModel):
    stage: StageName | None
    kind: ErrorKind
    message: str


class JobRequest(WireModel):
    """What a client asks to prepare."""

    capture_id: str
    overview_image_id: str


class JobInput(JobRequest):
    """The request plus the capture content it refers to, which identifies the job's input."""

    image_sha256: list[str]
    instructions_sha256: str


class WorkerConfig(WireModel):
    worker: Literal["fixture"]
    version: str
    stage_seconds: float
    fail_stage: StageName | None = None


class CandidateEntity(WireModel):
    id: str
    label: str
    kind: Literal["static", "movable"]
    selectable: bool
    width: float
    height: float
    depth: float


class Candidate(WireModel):
    source: Literal["fixture"]
    label: str
    room_version: int
    manifest: str
    entities: list[CandidateEntity]

    @classmethod
    def from_room(
        cls, room: LoadedRoom, source: Literal["fixture"], label: str, manifest: str
    ) -> Self:
        return cls(
            source=source,
            label=label,
            room_version=room.room_version,
            manifest=manifest,
            entities=[
                CandidateEntity(
                    id=entity.id,
                    label=entity.label,
                    kind=entity.kind,
                    selectable=entity.selectable,
                    width=entity.size.width,
                    height=entity.size.height,
                    depth=entity.size.depth,
                )
                for entity in room.entities
            ],
        )


class PreparationJob(StoredRecord):
    id: str = Field(pattern=JOB_ID.pattern)
    updated_at: str
    finished_at: str | None = None
    # Time since submission, including any wait in the queue; up to now while still active.
    elapsed_seconds: float | None = None
    state: JobState
    input: JobInput
    config: WorkerConfig
    input_hash: str
    stages: list[Stage]
    error: JobError | None = None
    candidate: Candidate | None = None

    @property
    def active(self) -> bool:
        return self.state in ("queued", "running")

    def with_live_timings(self, at: str) -> Self:
        """A copy whose running stage and unfinished job report elapsed time up to `at`."""
        job = self.model_copy(deep=True)
        if job.active:
            job.elapsed_seconds = seconds_between(job.created_at, at)
        for stage in job.stages:
            if stage.status == "running" and stage.started_at is not None:
                stage.elapsed_seconds = seconds_between(stage.started_at, at)
        return job


class StageFailure(Exception):
    """A stage failed in a way the worker can describe."""

    def __init__(self, kind: ErrorKind, message: str) -> None:
        super().__init__(message)
        self.kind: ErrorKind = kind


class Workspace:
    """The job folder a worker writes into."""

    def __init__(self, folder: Path) -> None:
        self.folder = folder

    def write(
        self, relative: str, data: bytes, media_type: ArtifactMediaType, description: str
    ) -> Artifact:
        path = self.folder / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return Artifact(
            path=relative, media_type=media_type, description=description, size_bytes=len(data)
        )


class PreparationWorker(Protocol):
    """Turns one capture into a candidate room through named stages."""

    config: WorkerConfig
    stages: tuple[StageName, ...]

    def run_stage(self, stage: StageName, job: JobInput, workspace: Workspace) -> list[Artifact]:
        """Run one stage, returning its artifacts or raising StageFailure."""
        ...

    def candidate(self, workspace: Workspace) -> Candidate:
        """Describe the candidate room the finished stages produced."""
        ...


class FixtureWorker:
    """Deterministic development worker: waits briefly per stage and copies a fixture room."""

    stages: tuple[StageName, ...] = ("scene_understanding", "geometry", "stabilization", "export")

    def __init__(self, fixture_room: Path, config: WorkerConfig) -> None:
        self.fixture_room = fixture_room
        self.config = config

    def run_stage(self, stage: StageName, job: JobInput, workspace: Workspace) -> list[Artifact]:
        time.sleep(self.config.stage_seconds)
        if stage == self.config.fail_stage:
            raise StageFailure(
                "fixture",
                f"The fixture worker was configured to fail at the {stage_title(stage)} stage.",
            )
        note = {"stage": stage, "label": FIXTURE_LABEL, "capture_id": job.capture_id}
        artifacts = [
            workspace.write(
                f"artifacts/{stage}.json",
                json.dumps(note, indent=2).encode(),
                "application/json",
                f"{FIXTURE_LABEL}: {stage_title(stage)} stage note",
            )
        ]
        if stage == "export":
            for source in sorted(self.fixture_room.iterdir()):
                if source.suffix in (".json", ".glb"):
                    artifacts.append(
                        workspace.write(
                            f"candidate/{source.name}",
                            source.read_bytes(),
                            "model/gltf-binary" if source.suffix == ".glb" else "application/json",
                            f"{FIXTURE_LABEL}: candidate {source.name}",
                        )
                    )
        return artifacts

    def candidate(self, workspace: Workspace) -> Candidate:
        try:
            room = load_prepared_room(workspace.folder / "candidate")
        except PreparedRoomError as exc:
            raise StageFailure("validation", f"The candidate room is not valid: {exc}") from exc
        return Candidate.from_room(room, "fixture", FIXTURE_LABEL, "candidate/manifest.json")


def worker_from_environment(repository: Path) -> PreparationWorker | None:
    """The worker chosen by server settings, or None when preparation is not configured."""
    if os.environ.get("ESCAPE_ROOM_PREPARATION_WORKER") != "fixture":
        return None
    config = WorkerConfig.model_validate(
        {
            "worker": "fixture",
            "version": "fixture-1",
            "stage_seconds": float(os.environ.get("ESCAPE_ROOM_FIXTURE_STAGE_SECONDS") or 1.0),
            "fail_stage": os.environ.get("ESCAPE_ROOM_FIXTURE_FAIL_STAGE") or None,
        }
    )
    return FixtureWorker(repository / "assets" / "multi-asset-room", config)


class PreparationService:
    def __init__(self, root: Path, captures: CaptureStore, worker: PreparationWorker | None):
        self.root = root
        self.captures = captures
        self.worker = worker
        self._records = RecordFolder(root, PreparationJob, JOB_ID, "job")
        self._queue: queue.Queue[str] = queue.Queue()
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._mark_interrupted()

    def submit(self, request: JobRequest) -> PreparationJob:
        capture = self.captures.get(request.capture_id)
        if request.overview_image_id not in {image.id for image in capture.images}:
            raise PreparationError("Choose an overview photo from this capture.")
        if self.worker is None:
            raise PreparationError("Room preparation is not configured on this server.", 503)
        job_input = JobInput(
            capture_id=capture.id,
            overview_image_id=request.overview_image_id,
            image_sha256=[image.sha256 for image in capture.images],
            instructions_sha256=hashlib.sha256(capture.instructions.encode()).hexdigest(),
        )
        identity = {"input": job_input.model_dump(), "config": self.worker.config.model_dump()}
        submitted = now()
        job = PreparationJob(
            id=f"job_{secrets.token_hex(16)}",
            created_at=submitted,
            updated_at=submitted,
            state="queued",
            input=job_input,
            config=self.worker.config,
            input_hash=hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest(),
            stages=[Stage(name=name) for name in self.worker.stages],
        )
        (self.root / job.id).mkdir(parents=True)
        self._records.save(job)
        self._queue.put(job.id)
        self._start()
        return job

    def get(self, job_id: str) -> PreparationJob:
        job = self._records.read(job_id)
        if job is None:
            raise PreparationError("That preparation job does not exist.", 404)
        return job.with_live_timings(now())

    def newest_first(self) -> list[PreparationJob]:
        at = now()
        return [job.with_live_timings(at) for job in self._records.newest_first()]

    def file(self, job_id: str, relative: str) -> Path:
        """A file inside the job folder, refusing paths that leave it."""
        job = self.get(job_id)
        parts = PurePosixPath(relative).parts
        if not parts or any(part in ("", ".", "..") for part in parts):
            raise PreparationError("That preparation file does not exist.", 404)
        path = self.root / job.id / Path(*parts)
        if not path.is_file():
            raise PreparationError("That preparation file does not exist.", 404)
        return path

    def _mark_interrupted(self) -> None:
        """Fail jobs a previous service process left unfinished; they are not resumed."""
        for job in self._records.newest_first():
            if not job.active:
                continue
            stage = next((stage for stage in job.stages if stage.status == "running"), None)
            if stage is not None:
                stage.status = "failed"
                stage.finished_at = now()
            job.error = JobError(
                stage=stage.name if stage is not None else None,
                kind="interrupted",
                message="The service restarted before this job finished. Submit it again.",
            )
            self._finish(job, "failed")

    def _start(self) -> None:
        with self._lock:
            if self._thread is None:
                self._thread = threading.Thread(target=self._run_forever, daemon=True)
                self._thread.start()

    def _run_forever(self) -> None:
        while True:
            self._run(self._queue.get())

    def _run(self, job_id: str) -> None:
        worker = self.worker
        job = self._records.read(job_id)
        if worker is None or job is None:
            return
        workspace = Workspace(self.root / job.id)
        self._update(job, state="running")
        for stage in job.stages:
            stage.status = "running"
            stage.started_at = now()
            self._update(job)
            started = time.monotonic()
            try:
                stage.artifacts = worker.run_stage(stage.name, job.input, workspace)
                if stage is job.stages[-1]:
                    job.candidate = worker.candidate(workspace)
            except StageFailure as exc:
                error = JobError(stage=stage.name, kind=exc.kind, message=str(exc))
            except Exception as exc:  # noqa: BLE001 - one bad job must not stop the worker thread
                message = f"The preparation worker stopped unexpectedly ({type(exc).__name__})."
                error = JobError(stage=stage.name, kind="worker", message=message)
            else:
                error = None
            stage.elapsed_seconds = round(time.monotonic() - started, 3)
            stage.finished_at = now()
            stage.status = "done" if error is None else "failed"
            if error is not None:
                job.error = error
                self._finish(job, "failed")
                return
            self._update(job)
        self._finish(job, "awaiting_review")

    def _finish(self, job: PreparationJob, state: JobState) -> None:
        job.finished_at = now()
        job.elapsed_seconds = seconds_between(job.created_at, job.finished_at)
        self._update(job, state=state)

    def _update(self, job: PreparationJob, state: JobState | None = None) -> None:
        if state is not None:
            job.state = state
        job.updated_at = now()
        self._records.save(job)
