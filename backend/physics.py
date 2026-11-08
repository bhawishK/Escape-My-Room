"""The server's one physics simulation (#159): a Havok worker in Node beside Python.

Python starts the worker with the server and talks to it in JSON lines over its standard input and
output (the messages are described in ``physics/worker.mjs``). The session never waits on it: if it
can't start, or exits, the status says so with a reason and the session works as it did without
physics. Threads read the worker's output, so this works with any event loop, including
uvicorn's on Windows, which can't run asyncio subprocesses.
"""

import asyncio
import json
import os
import shutil
import subprocess
import threading
from collections import deque
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

from backend.prepared_room import FLOOR_THICKNESS, SceneEntity

REPOSITORY = Path(__file__).resolve().parents[1]
DEFAULT_WORKER = REPOSITORY / "physics" / "worker.mjs"
# Lines of the worker's standard error kept to explain why it stopped. Node's crash reports end
# with a stack and its version, so the explanation is the last line that names an error.
STDERR_LINES = 40
# Seconds the worker gets to exit on its own after its input closes.
STOP_TIMEOUT = 2.0

PhysicsState = Literal["starting", "running", "unavailable"]


def bodies_for(entities: list[SceneEntity]) -> list[dict[str, Any]]:
    """The room's simulated bodies: the floor is static, and movable objects are dynamic."""
    bodies: list[dict[str, Any]] = []
    for entity in entities:
        if entity.kind == "movable":
            motion = "dynamic"
        elif entity.size.height <= FLOOR_THICKNESS:
            motion = "static"
        else:
            # Furniture isn't a collider yet (#159, out of scope).
            continue
        bodies.append(
            {
                "id": entity.id,
                "motion": motion,
                "size": entity.size.model_dump(),
                "position": entity.position.model_dump(),
                "rotation": entity.rotation.model_dump(),
            }
        )
    return bodies


class PhysicsWorker:
    """The Havok worker process, and the status the session reports for it."""

    def __init__(self, on_change: Callable[[], None]) -> None:
        # Called on the event loop whenever the status changes.
        self.on_change = on_change
        self.state: PhysicsState = "starting"
        self.engine: str | None = None
        self.reason: str | None = None
        self.room_version: int | None = None
        self.bodies: dict[str, int] | None = None
        self.process: subprocess.Popen[str] | None = None
        self.loop: asyncio.AbstractEventLoop | None = None
        self.stopping = False
        self.write_lock = threading.Lock()
        self.errors: threading.Thread | None = None
        self.stderr: deque[str] = deque(maxlen=STDERR_LINES)
        # The room to load once the worker is ready, or reload if it is sent before then.
        self.pending: dict[str, Any] | None = None

    def status(self) -> dict[str, Any]:
        return {
            "status": self.state,
            "engine": self.engine,
            "reason": self.reason,
            "room_version": self.room_version,
            "bodies": self.bodies,
        }

    def start(self) -> None:
        """Start the worker. A failure to start makes physics unavailable, never the server."""
        self.loop = asyncio.get_running_loop()
        node = os.environ.get("ESCAPE_ROOM_NODE") or shutil.which("node")
        worker = Path(os.environ.get("ESCAPE_ROOM_PHYSICS_WORKER") or DEFAULT_WORKER)
        if node is None:
            self._unavailable("Node.js was not found, so the physics worker can't run.")
            return
        try:
            self.process = subprocess.Popen(
                [node, str(worker)],
                cwd=worker.parent,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                bufsize=1,
            )
        except OSError as exc:
            self._unavailable(f"The physics worker couldn't start: {exc}")
            return
        self.errors = threading.Thread(target=self._read_errors, daemon=True)
        self.errors.start()
        threading.Thread(target=self._read_output, daemon=True).start()

    def load(self, room_version: int, entities: list[SceneEntity]) -> None:
        """Replace the simulated room. Sent once the worker is ready if it isn't yet."""
        self.pending = {
            "type": "load",
            "room_version": room_version,
            "bodies": bodies_for(entities),
        }
        if self.state == "running":
            self._send(self.pending)

    def stop(self) -> None:
        """Close the worker's input, so it exits; kill it if it doesn't."""
        self.stopping = True
        process = self.process
        if process is None:
            return
        try:
            if process.stdin is not None:
                process.stdin.close()
            process.wait(timeout=STOP_TIMEOUT)
        except (OSError, subprocess.TimeoutExpired):
            process.kill()
            process.wait(timeout=STOP_TIMEOUT)

    def _send(self, message: dict[str, Any]) -> None:
        process = self.process
        if process is None or process.stdin is None:
            return
        try:
            with self.write_lock:
                process.stdin.write(json.dumps(message) + "\n")
                process.stdin.flush()
        except OSError:
            # The reader sees the worker exit and says why.
            pass

    def _read_output(self) -> None:
        process = self.process
        assert process is not None and process.stdout is not None
        for line in process.stdout:
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                continue
            self._on_loop(lambda message=message: self._handle(message))
        code = process.wait()
        # Its last words are on standard error; let them arrive before saying why it stopped.
        if self.errors is not None:
            self.errors.join(timeout=STOP_TIMEOUT)
        self._on_loop(lambda: self._exited(code))

    def _read_errors(self) -> None:
        process = self.process
        assert process is not None and process.stderr is not None
        for line in process.stderr:
            if line.strip():
                self.stderr.append(line.strip())

    def _on_loop(self, action: Callable[[], None]) -> None:
        loop = self.loop
        if loop is not None and not loop.is_closed():
            try:
                loop.call_soon_threadsafe(action)
            except RuntimeError:
                # The loop closed as the server stopped.
                pass

    def _handle(self, message: dict[str, Any]) -> None:
        kind = message.get("type")
        if kind == "ready":
            self.state = "running"
            self.engine = message.get("engine")
            self.reason = None
            if self.pending is not None:
                self._send(self.pending)
            self.on_change()
        elif kind == "loaded":
            self.room_version = message.get("room_version")
            self.bodies = message.get("bodies")
            self.on_change()

    def _exited(self, code: int) -> None:
        if self.stopping:
            return
        named = [line for line in self.stderr if "error" in line.lower()]
        last = named[-1] if named else self.stderr[-1] if self.stderr else None
        detail = f": {last}" if last else ""
        self._unavailable(f"The physics worker exited with code {code}{detail}")

    def _unavailable(self, reason: str) -> None:
        self.state = "unavailable"
        self.reason = reason
        self.room_version = None
        self.bodies = None
        self.on_change()
