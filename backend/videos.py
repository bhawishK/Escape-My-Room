"""Room videos (#136): uploaded in chunks, checked with ffprobe, and kept as a capture.

The free Cloudflare tunnel refuses requests over 100 MB, so a video arrives in chunks (8 MB by
default). `start` reserves a file of the video's size; each chunk is written at its own offset, so a
chunk sent twice after a dropped connection does no harm. `complete` checks that every chunk came,
asks ffprobe what the file is, and only then moves it into place as a video capture:
`<captures>/<capture id>/video.<mp4|mov>` beside `capture.json`. A refused video leaves nothing; a
failure on the server's side (such as no ffprobe) keeps the upload, to finish later. Finishing
again after the answer was lost returns the same capture.

Video captures share the captures folder with photo captures; each store reads only its own kind.
"""

import hashlib
import json
import math
import os
import re
import secrets
import shutil
import subprocess
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePath
from typing import Any, Literal

from pydantic import Field

from backend.captures import CAPTURE_ID
from backend.errors import Refusal
from backend.protocol import WireModel
from backend.records import RecordFolder, StoredRecord, now, write_json

UPLOAD_ID = re.compile(r"^upl_[0-9a-f]{32}$")
SUFFIXES = {"video/mp4": ".mp4", "video/quicktime": ".mov"}
MAX_INSTRUCTIONS = 4000
# An upload not completed within this long is given up and its file removed.
ABANDONED_AFTER = timedelta(days=1)

type VideoMediaType = Literal["video/mp4", "video/quicktime"]


class VideoError(Refusal):
    """A video request cannot be accepted; the message is shown to the user."""


@dataclass(frozen=True)
class VideoLimits:
    max_bytes: int = 2 * 1024**3
    max_seconds: float = 300
    chunk_bytes: int = 8 * 1024**2

    @classmethod
    def from_environment(cls) -> "VideoLimits":
        def setting(name: str, default: float) -> float:
            value = os.environ.get(f"ESCAPE_ROOM_VIDEO_{name}")
            return float(value) if value else default

        defaults = cls()
        return cls(
            max_bytes=int(setting("MAX_BYTES", defaults.max_bytes)),
            max_seconds=setting("MAX_SECONDS", defaults.max_seconds),
            chunk_bytes=int(setting("CHUNK_BYTES", defaults.chunk_bytes)),
        )


class VideoInfo(WireModel):
    seconds: float
    # As the video is seen, upright: a portrait phone video is taller than wide.
    width: int
    height: int
    frames_per_second: float
    codec: str


class UploadRequest(WireModel):
    filename: str
    size_bytes: int
    media_type: str


class CompleteRequest(WireModel):
    instructions: str = ""


class VideoUpload(StoredRecord):
    id: str = Field(pattern=UPLOAD_ID.pattern)
    filename: str
    size_bytes: int
    media_type: VideoMediaType
    chunk_bytes: int
    chunks: int
    received: list[int]


class VideoCapture(StoredRecord):
    id: str = Field(pattern=CAPTURE_ID.pattern)
    kind: Literal["video"] = "video"
    instructions: str
    original_filename: str
    media_type: VideoMediaType
    size_bytes: int
    sha256: str
    video: VideoInfo
    # The upload it was finished from, so finishing again finds it.
    upload_id: str = Field(pattern=UPLOAD_ID.pattern)

    @property
    def file(self) -> PurePath:
        return PurePath(f"video{SUFFIXES[self.media_type]}")


type Probe = Callable[[Path, str], VideoInfo]


def parse_ffprobe(output: dict[str, Any]) -> VideoInfo:
    """The video's facts from `ffprobe -print_format json -show_format -show_streams`."""
    container = output.get("format", {}).get("format_name", "")
    if not {"mov", "mp4"} & set(container.split(",")):
        raise VideoError(
            f"Upload an MP4 or MOV video, as the phone's camera records; this one is {container}."
        )
    stream = next((s for s in output["streams"] if s.get("codec_type") == "video"), None)
    if stream is None:
        raise VideoError("The file has no video in it.")
    width, height = int(stream["width"]), int(stream["height"])
    rotation = next(
        (side["rotation"] for side in stream.get("side_data_list", []) if "rotation" in side), 0
    )
    if int(rotation) % 180:
        width, height = height, width
    numerator, denominator = (int(part) for part in stream["avg_frame_rate"].split("/"))
    return VideoInfo(
        seconds=round(float(output["format"]["duration"]), 3),
        width=width,
        height=height,
        frames_per_second=round(numerator / denominator, 2),
        codec=stream["codec_name"],
    )


def ffprobe(path: Path, name: str) -> VideoInfo:
    command = ["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams"]
    try:
        result = subprocess.run([*command, str(path)], capture_output=True, check=False, timeout=60)
    except FileNotFoundError as exc:
        raise VideoError("The server cannot check videos: ffprobe is not installed.", 503) from exc
    if result.returncode != 0:
        raise VideoError(f"{name} could not be read as a video.")
    return parse_ffprobe(json.loads(result.stdout))


def fixture_probe(path: Path, name: str) -> VideoInfo:
    """A test configuration standing in for ffprobe: an MP4 `ftyp` box followed by the JSON ffprobe
    would print. Anything else is not a video."""
    data = path.read_bytes()
    if data[4:8] != b"ftyp":
        raise VideoError(f"{name} could not be read as a video.")
    size = int.from_bytes(data[:4], "big")
    return parse_ffprobe(json.loads(data[size:]))


def probe_from_environment() -> Probe:
    return fixture_probe if os.environ.get("ESCAPE_ROOM_VIDEO_PROBE") == "fixture" else ffprobe


class VideoStore:
    def __init__(self, root: Path, limits: VideoLimits, probe: Probe) -> None:
        self.root = root
        self.limits = limits
        self.probe = probe
        self.uploads = root / ".uploads"
        self._records = RecordFolder(root, VideoCapture, CAPTURE_ID, "capture")
        self._pending = RecordFolder(self.uploads, VideoUpload, UPLOAD_ID, "upload")
        # One lock per upload, so checking one large video never holds up another's chunks.
        self._locks: dict[str, threading.Lock] = {}
        self._locks_lock = threading.Lock()

    def start(self, request: UploadRequest) -> VideoUpload:
        name = PurePath(request.filename.replace("\\", "/")).name[:255] or "video"
        if request.media_type not in SUFFIXES:
            raise VideoError(f"Upload an MP4 or MOV video; {name} is {request.media_type}.", 415)
        if request.size_bytes <= 0:
            raise VideoError(f"{name} is empty.")
        if request.size_bytes > self.limits.max_bytes:
            raise VideoError(
                f"{name} is {size_text(request.size_bytes)}; "
                f"the limit is {size_text(self.limits.max_bytes)}.",
                413,
            )
        self._forget_abandoned()
        upload = VideoUpload.model_validate(
            {
                "id": f"upl_{secrets.token_hex(16)}",
                "created_at": now(),
                "filename": name,
                "size_bytes": request.size_bytes,
                "media_type": request.media_type,
                "chunk_bytes": self.limits.chunk_bytes,
                "chunks": math.ceil(request.size_bytes / self.limits.chunk_bytes),
                "received": [],
            }
        )
        folder = self.uploads / upload.id
        folder.mkdir(parents=True)
        with open(folder / "video.part", "wb") as file:
            file.truncate(upload.size_bytes)
        self._pending.save(upload)
        return upload

    def put_chunk(self, upload_id: str, number: int, data: bytes) -> None:
        with self._lock(upload_id):
            upload = self._upload(upload_id)
            if not 0 <= number < upload.chunks:
                raise VideoError(f"This upload has chunks 0 to {upload.chunks - 1}.")
            start = number * upload.chunk_bytes
            expected = min(upload.chunk_bytes, upload.size_bytes - start)
            if len(data) != expected:
                raise VideoError(f"Chunk {number} should be {expected} bytes; {len(data)} came.")
            with open(self.uploads / upload.id / "video.part", "r+b") as file:
                file.seek(start)
                file.write(data)
            if number not in upload.received:
                upload.received = sorted([*upload.received, number])
                self._pending.save(upload)

    def complete(self, upload_id: str, request: CompleteRequest) -> VideoCapture:
        if len(request.instructions) > MAX_INSTRUCTIONS:
            raise VideoError(f"Keep room instructions under {MAX_INSTRUCTIONS} characters.", 413)
        with self._lock(upload_id):
            finished = next(
                (c for c in self._records.newest_first() if c.upload_id == upload_id), None
            )
            if finished is not None:
                return finished
            upload = self._upload(upload_id)
            missing = sorted(set(range(upload.chunks)) - set(upload.received))
            if missing:
                raise VideoError(
                    f"{len(missing)} of {upload.chunks} chunks have not arrived yet, "
                    f"starting with chunk {missing[0]}.",
                    409,
                )
            folder = self.uploads / upload.id
            try:
                capture = self._check(upload, folder / "video.part", request.instructions)
            except VideoError as exc:
                if exc.status < 500:
                    shutil.rmtree(folder, ignore_errors=True)
                raise
            incoming = self.root / f".incoming-{capture.id}"
            incoming.mkdir()
            (folder / "video.part").replace(incoming / capture.file)
            write_json(incoming / "capture.json", capture)
            incoming.rename(self.root / capture.id)
            shutil.rmtree(folder, ignore_errors=True)
            return capture

    def newest_first(self) -> list[VideoCapture]:
        return self._records.newest_first()

    def get(self, capture_id: str) -> VideoCapture | None:
        return self._records.read(capture_id)

    def _check(self, upload: VideoUpload, path: Path, instructions: str) -> VideoCapture:
        info = self.probe(path, upload.filename)
        if info.seconds > self.limits.max_seconds:
            raise VideoError(
                f"{upload.filename} is {duration_text(info.seconds)} long; "
                f"keep it under {duration_text(self.limits.max_seconds)}.",
                413,
            )
        digest = hashlib.sha256()
        with open(path, "rb") as file:
            for block in iter(lambda: file.read(1024 * 1024), b""):
                digest.update(block)
        return VideoCapture(
            id=f"cap_{secrets.token_hex(16)}",
            created_at=now(),
            instructions=instructions,
            original_filename=upload.filename,
            media_type=upload.media_type,
            size_bytes=upload.size_bytes,
            sha256=digest.hexdigest(),
            video=info,
            upload_id=upload.id,
        )

    def _lock(self, upload_id: str) -> threading.Lock:
        with self._locks_lock:
            return self._locks.setdefault(upload_id, threading.Lock())

    def _upload(self, upload_id: str) -> VideoUpload:
        upload = self._pending.read(upload_id)
        if upload is None:
            raise VideoError("That upload does not exist. Choose the video again.", 404)
        return upload

    def _forget_abandoned(self) -> None:
        cutoff = datetime.now(UTC) - ABANDONED_AFTER
        for upload in self._pending.newest_first():
            if datetime.fromisoformat(upload.created_at) < cutoff:
                shutil.rmtree(self.uploads / upload.id, ignore_errors=True)


def size_text(size: float) -> str:
    if size < 1024**2:
        return f"{size / 1024:,.0f} KB"
    return f"{size / 1024**2:,.0f} MB"


def duration_text(seconds: float) -> str:
    minutes, rest = divmod(round(seconds), 60)
    return f"{minutes} min {rest} s" if minutes else f"{rest} s"
