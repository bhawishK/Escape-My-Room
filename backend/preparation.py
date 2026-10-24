"""Room preparation jobs: turn a saved capture into a candidate room, one job at a time.

A job is a durable record under `<data>/jobs/<job id>/job.json`, rewritten atomically on every
change. One background thread runs queued jobs in order, so request handlers and the shared-room
lock never wait for a worker. A worker runs named stages and then yields a candidate prepared
room; the candidate is inspected here and never replaces the active room.

Server settings choose the worker. The deterministic fixture worker is a test configuration, and
everything it produces is labelled as fixture output, not AI inference. The OpenRouter worker asks
Qwen through OpenRouter for the overview's objects and ends with that inventory for review; every
model request is recorded on the job with its tokens, cost and answer.
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
from typing import Annotated, Literal, Protocol, Self

from pydantic import Field

from backend.captures import CaptureStore
from backend.errors import Refusal
from backend.openrouter import (
    OBJECT_LIST,
    PROMPTS,
    OpenRouterClient,
    OpenRouterConfig,
    Picture,
    ProviderFailure,
    Reply,
    ask,
    say,
)
from backend.prepared_room import LoadedRoom, PreparedRoomError, load_prepared_room
from backend.protocol import WireModel
from backend.records import RecordFolder, StoredRecord, now, seconds_between

JOB_ID = re.compile(r"^job_[0-9a-f]{32}$")
FIXTURE_LABEL = "Fixture output, not AI inference"
OPENROUTER_LABEL = "Qwen through OpenRouter"

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
type ArtifactMediaType = Literal["application/json", "model/gltf-binary", "text/plain"]


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


class FixtureConfig(WireModel):
    worker: Literal["fixture"]
    version: str
    stage_seconds: float
    fail_stage: StageName | None = None


type WorkerConfig = Annotated[FixtureConfig | OpenRouterConfig, Field(discriminator="worker")]


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


class InventoryObject(WireModel):
    id: str
    label: str


class Inventory(WireModel):
    """The objects a model found in the overview, before any segmentation or geometry."""

    source: Literal["openrouter"]
    label: str
    overview_image_id: str
    objects: list[InventoryObject]
    # The accepted answer, relative to the job folder.
    answer: str


class ModelCall(WireModel):
    """One model request: what it cost, and whether its answer was accepted."""

    stage: StageName
    purpose: str
    model: str | None
    provider: str | None
    generation_id: str | None
    prompt_tokens: int | None
    completion_tokens: int | None
    cost_usd: float | None
    latency_seconds: float
    finish_reason: str | None
    accepted: bool
    # Why the answer was refused, when it was.
    problem: str | None
    # The answer as received, relative to the job folder.
    answer: str


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
    inventory: Inventory | None = None
    model_calls: list[ModelCall] = Field(default_factory=lambda: list[ModelCall]())
    # The sum of the costs OpenRouter reported, in US dollars; None when no model was asked.
    cost_usd: float | None = None

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
        # Model requests made since the service last collected them.
        self.calls: list[ModelCall] = []

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
    """Turns one capture into something to review through named stages."""

    @property
    def config(self) -> FixtureConfig | OpenRouterConfig: ...

    @property
    def stages(self) -> tuple[StageName, ...]: ...

    def run_stage(self, stage: StageName, job: JobInput, workspace: Workspace) -> list[Artifact]:
        """Run one stage, returning its artifacts or raising StageFailure."""
        ...

    def outcome(self, workspace: Workspace) -> "Candidate | Inventory":
        """Describe what the finished stages produced for review."""
        ...


class FixtureWorker:
    """Deterministic development worker: waits briefly per stage and copies a fixture room."""

    stages: tuple[StageName, ...] = ("scene_understanding", "geometry", "stabilization", "export")

    def __init__(self, fixture_room: Path, config: FixtureConfig) -> None:
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

    def outcome(self, workspace: Workspace) -> Candidate:
        try:
            room = load_prepared_room(workspace.folder / "candidate")
        except PreparedRoomError as exc:
            raise StageFailure("validation", f"The candidate room is not valid: {exc}") from exc
        return Candidate.from_room(room, "fixture", FIXTURE_LABEL, "candidate/manifest.json")


LIST_OBJECTS_PROMPT = (PROMPTS / "list_objects.txt").read_text(encoding="utf-8").strip()


def instructions_note(instructions: str) -> str:
    return (
        "The person who took this photo describes the room and the objects that matter. "
        "Use it to decide which objects to list, and still follow the rules and output format "
        f"above:\n{instructions}"
    )


def entity_ids(labels: list[str]) -> list[str]:
    """Stable IDs for the labels in order: lowercase words joined by underscores, made unique."""
    ids: list[str] = []
    for label in labels:
        base = re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_") or "object"
        candidate, number = base, 2
        while candidate in ids:
            candidate, number = f"{base}_{number}", number + 1
        ids.append(candidate)
    return ids


class OpenRouterWorker:
    """Asks Qwen through OpenRouter which objects the overview shows."""

    stages: tuple[StageName, ...] = ("scene_understanding",)

    def __init__(self, captures: CaptureStore, config: OpenRouterConfig, api_key: str | None):
        self.captures = captures
        self.config = config
        self.client = OpenRouterClient(config, api_key)

    def run_stage(self, stage: StageName, job: JobInput, workspace: Workspace) -> list[Artifact]:
        capture = self.captures.get(job.capture_id)
        path, _ = self.captures.photo_file(capture.id, job.overview_image_id, "processed")
        overview = Picture.from_file(path, self.config.max_image_side)
        parts: list[Picture | str] = [overview, LIST_OBJECTS_PROMPT]
        if capture.instructions.strip():
            parts.append(instructions_note(capture.instructions.strip()))
        artifacts: list[Artifact] = []

        def record(reply: Reply, problem: str | None) -> None:
            number = len(workspace.calls) + 1
            answer = workspace.write(
                f"artifacts/{stage}/answer-{number}.txt",
                reply.text.encode(),
                "text/plain",
                f"{OPENROUTER_LABEL}: object list answer {number}",
            )
            artifacts.append(answer)
            workspace.calls.append(
                ModelCall(
                    stage=stage,
                    purpose="object list",
                    model=reply.model,
                    provider=reply.provider,
                    generation_id=reply.generation_id,
                    prompt_tokens=reply.prompt_tokens,
                    completion_tokens=reply.completion_tokens,
                    cost_usd=reply.cost_usd,
                    latency_seconds=reply.latency_seconds,
                    finish_reason=reply.finish_reason,
                    accepted=problem is None,
                    problem=problem,
                    answer=answer.path,
                )
            )

        try:
            labels = ask(self.client, [say("user", *parts)], OBJECT_LIST, record)
        except ProviderFailure as exc:
            raise StageFailure(exc.kind, str(exc)) from exc
        inventory = Inventory(
            source="openrouter",
            label=OPENROUTER_LABEL,
            overview_image_id=job.overview_image_id,
            objects=[
                InventoryObject(id=id, label=label)
                for id, label in zip(entity_ids(labels), labels, strict=True)
            ],
            answer=workspace.calls[-1].answer,
        )
        artifacts.append(
            workspace.write(
                f"artifacts/{stage}/inventory.json",
                inventory.model_dump_json(indent=2).encode(),
                "application/json",
                f"{OPENROUTER_LABEL}: object inventory",
            )
        )
        return artifacts

    def outcome(self, workspace: Workspace) -> Inventory:
        return Inventory.model_validate_json(
            (workspace.folder / "artifacts" / "scene_understanding" / "inventory.json").read_bytes()
        )


def worker_from_environment(repository: Path, captures: CaptureStore) -> PreparationWorker | None:
    """The worker chosen by server settings, or None when preparation is not configured."""
    worker = os.environ.get("ESCAPE_ROOM_PREPARATION_WORKER")
    if worker == "openrouter":
        return OpenRouterWorker(
            captures, OpenRouterConfig.from_environment(), os.environ.get("OPENROUTER_API_KEY")
        )
    if worker != "fixture":
        return None
    config = FixtureConfig.model_validate(
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
                    outcome = worker.outcome(workspace)
                    if isinstance(outcome, Inventory):
                        job.inventory = outcome
                    else:
                        job.candidate = outcome
            except StageFailure as exc:
                error = JobError(stage=stage.name, kind=exc.kind, message=str(exc))
            except Exception as exc:  # noqa: BLE001 - one bad job must not stop the worker thread
                message = f"The preparation worker stopped unexpectedly ({type(exc).__name__})."
                error = JobError(stage=stage.name, kind="worker", message=message)
            else:
                error = None
            self._collect_calls(job, workspace)
            stage.elapsed_seconds = round(time.monotonic() - started, 3)
            stage.finished_at = now()
            stage.status = "done" if error is None else "failed"
            if error is not None:
                job.error = error
                self._finish(job, "failed")
                return
            self._update(job)
        self._finish(job, "awaiting_review")

    def _collect_calls(self, job: PreparationJob, workspace: Workspace) -> None:
        """Move the stage's model requests onto the job, failed stages included: they cost money."""
        if not workspace.calls:
            return
        job.model_calls += workspace.calls
        workspace.calls = []
        costs = [call.cost_usd for call in job.model_calls if call.cost_usd is not None]
        job.cost_usd = round(sum(costs), 6) if costs else None

    def _finish(self, job: PreparationJob, state: JobState) -> None:
        job.finished_at = now()
        job.elapsed_seconds = seconds_between(job.created_at, job.finished_at)
        self._update(job, state=state)

    def _update(self, job: PreparationJob, state: JobState | None = None) -> None:
        if state is not None:
            job.state = state
        job.updated_at = now()
        self._records.save(job)
