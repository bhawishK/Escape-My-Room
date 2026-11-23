"""Session logs (#259, part of #221): each drill run recorded for studies.

A run starts when a drill's fire starts and ends when it is stopped, removed or called off, the
room changes, or the headset leaves. It is one JSON-lines file in `data/session-logs/`: each line
has `t`, the milliseconds since the run started, and a `kind`:
- `run`: `started` (room version, object, hazard, wall-clock time) or `ended` (with the reason);
- `presence`: a person's tracking, position and facing, at most five times a second each;
- `guide`: the commander's pointed spot, or null when cleared (#248);
- `hand`: the giant hand's position, or null, at most five times a second (#185);
- `hazard`: a fire `started`, `stopped` or `removed`.

Positions and guidance only: no pictures, sound or video. `ESCAPE_ROOM_SESSION_LOGS=0` turns it
off.
"""

import json
import math
import os
import re
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TextIO

RUN_ID = re.compile(r"\d{8}T\d{6}Z-[0-9a-f]{6}")
# Presence and the hand are logged at most this often, per person.
SAMPLE_SECONDS = 0.2


def enabled_from_environment() -> bool:
    return (os.environ.get("ESCAPE_ROOM_SESSION_LOGS") or "1").strip() not in ("0", "false", "no")


class SessionLogs:
    """The run being logged, if any, and the runs kept."""

    def __init__(
        self, root: Path, enabled: bool = True, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self.root = root
        self.enabled = enabled
        self.clock = clock
        self.run: str | None = None
        self.file: TextIO | None = None
        self.started_at = 0.0
        self.last_sample: dict[str, float] = {}

    @property
    def running(self) -> bool:
        return self.file is not None

    def begin(self, room_version: int | None, entity: str | None, hazard: str | None) -> None:
        """Starts a run, unless one is already going."""
        if not self.enabled or self.running:
            return
        self.root.mkdir(parents=True, exist_ok=True)
        now = datetime.now(UTC)
        self.run = f"{now:%Y%m%dT%H%M%SZ}-{uuid.uuid4().hex[:6]}"
        self.file = (self.root / f"{self.run}.jsonl").open("a", encoding="utf-8")
        self.started_at = self.clock()
        self.last_sample = {}
        self._write(
            {
                "kind": "run",
                "event": "started",
                "at": now.isoformat(),
                "room_version": room_version,
                "object": entity,
                "hazard": hazard,
            }
        )

    def end(self, reason: str) -> None:
        if self.file is None:
            return
        self._write({"kind": "run", "event": "ended", "reason": reason})
        self.file.close()
        self.file = None
        self.run = None

    def record(self, kind: str, fields: dict[str, Any], sample: str | None = None) -> None:
        """Logs a line in the run going, if any. Lines given a `sample` key are kept at most every
        SAMPLE_SECONDS for that key; lines without one, such as a hand or a spot going, always."""
        if self.file is None:
            return
        if sample is not None:
            now = self.clock()
            if now - self.last_sample.get(sample, -math.inf) < SAMPLE_SECONDS:
                return
            self.last_sample[sample] = now
        self._write({"kind": kind} | fields)

    def _write(self, line: dict[str, Any]) -> None:
        assert self.file is not None
        stamped = {"t": round((self.clock() - self.started_at) * 1000)} | line
        self.file.write(json.dumps(stamped, separators=(",", ":")) + "\n")
        self.file.flush()

    def path(self, run_id: str) -> Path | None:
        if not RUN_ID.fullmatch(run_id):
            return None
        path = self.root / f"{run_id}.jsonl"
        return path if path.is_file() else None

    def runs(self) -> list[dict[str, Any]]:
        """Each run kept, newest first, summarised."""
        if not self.root.is_dir():
            return []
        found = [summarise(path) for path in sorted(self.root.glob("*.jsonl"), reverse=True)]
        return [summary for summary in found if summary is not None]


def summarise(path: Path) -> dict[str, Any] | None:
    """A run's length, what it was, how it ended, how far the occupant walked, and how much of it
    the commander was pointing the way."""
    try:
        logged = [
            json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line
        ]
    except (OSError, ValueError):
        return None
    if not logged or logged[0].get("kind") != "run":
        return None
    first, last = logged[0], logged[-1]
    seconds = last["t"] / 1000
    walked = 0.0
    previous: tuple[float, float] | None = None
    guiding_since: float | None = None
    guided = 0.0
    for line in logged:
        if line["kind"] == "presence" and line.get("role") == "mobile_master":
            position = line.get("position")
            if position is None:
                continue
            here = (position["x"], position["z"])
            if previous is not None:
                walked += math.dist(previous, here)
            previous = here
        elif line["kind"] == "guide":
            if line.get("spot") is not None and guiding_since is None:
                guiding_since = line["t"]
            elif line.get("spot") is None and guiding_since is not None:
                guided += line["t"] - guiding_since
                guiding_since = None
    if guiding_since is not None:
        guided += last["t"] - guiding_since
    return {
        "id": path.stem,
        "at": first.get("at"),
        "room_version": first.get("room_version"),
        "object": first.get("object"),
        "hazard": first.get("hazard"),
        "ended": last.get("reason") if last.get("kind") == "run" else None,
        "seconds": round(seconds, 2),
        "occupant_path_metres": round(walked, 2),
        "guided_share": round(guided / last["t"], 3) if last["t"] > 0 else 0.0,
    }
