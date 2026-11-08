"""The server's one physics simulation (#159): a Havok worker in Node beside Python.

Python starts the worker with the server and talks to it in JSON lines over its standard input and
output (the messages are described in ``physics/worker.mjs``). The session never waits on it: if it
can't start, or exits, the status says so with a reason and the session works as it did without
physics. Threads write to and read from the worker, so the event loop never waits on its pipes,
and this works with any event loop, including uvicorn's on Windows, which can't run asyncio
subprocesses.
"""

import asyncio
import json
import os
import queue
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


def bodies_for(entities: list[SceneEntity], epochs: dict[str, int]) -> list[dict[str, Any]]:
    """The room's simulated bodies, where they are now: the floor is static, and movable objects
    are dynamic, each with its epoch."""
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
                "material": None if entity.physics is None else entity.physics.model_dump(),
                "epoch": epochs.get(entity.id, 0),
            }
        )
    return bodies


def pose_of(entity: SceneEntity) -> dict[str, Any]:
    """Where an entity is, as the worker's commands give it."""
    return {"position": entity.position.model_dump(), "rotation": entity.rotation.model_dump()}


class PhysicsWorker:
    """The Havok worker process, and the status the session reports for it."""

    def __init__(
        self,
        on_change: Callable[[], None],
        on_moved: Callable[[list[dict[str, Any]]], None] = lambda poses: None,
    ) -> None:
        # Called on the event loop whenever the status changes.
        self.on_change = on_change
        # Called on the event loop with the poses of bodies that moved, about 30 times a second
        # while anything moves, and once more when it comes to rest. The moving list in the
        # status is current by then.
        self.on_moved = on_moved
        self.state: PhysicsState = "starting"
        self.engine: str | None = None
        self.reason: str | None = None
        self.room_version: int | None = None
        self.bodies: dict[str, int] | None = None
        self.process: subprocess.Popen[str] | None = None
        self.loop: asyncio.AbstractEventLoop | None = None
        self.stopping = False
        # Messages for the worker, written by a thread; None closes its input.
        self.outgoing: queue.Queue[dict[str, Any] | None] = queue.Queue()
        self.stderr: deque[str] = deque(maxlen=STDERR_LINES)
        self.stderr_reader: threading.Thread | None = None
        # The latest room asked for, and the session's own entities, so the room is sent with
        # them where they are when the worker becomes ready. Only this room's "loaded" counts.
        self.wanted_version: int | None = None
        self.entities: list[SceneEntity] = []
        # Each body's epoch: a number that grows with every room load and every command, never
        # reused. The worker echoes it in the body's poses, so poses from before the latest
        # command, or from a room since replaced, are recognised and ignored.
        self.epochs: dict[str, int] = {}
        self.last_epoch = 0
        # Bodies someone holds: physics leaves them alone, and reports of them don't count.
        self.held: set[str] = set()
        self.moving: list[str] = []

    def status(self) -> dict[str, Any]:
        return {
            "status": self.state,
            "engine": self.engine,
            "reason": self.reason,
            "room_version": self.room_version,
            "bodies": self.bodies,
            "moving": list(self.moving),
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
        self.stderr_reader = threading.Thread(target=self._read_errors, daemon=True)
        self.stderr_reader.start()
        threading.Thread(target=self._read_output, daemon=True).start()
        threading.Thread(target=self._write_input, daemon=True).start()

    def load(self, room_version: int, entities: list[SceneEntity]) -> None:
        """Replace the simulated room. Sent once the worker is ready if it isn't yet."""
        self.wanted_version = room_version
        self.entities = entities
        for entity in entities:
            self.epochs[entity.id] = self._next_epoch()
        self.held = set()
        self.moving = []
        if self.state == "running":
            self._send_room()

    def _send_room(self) -> None:
        if self.wanted_version is None:
            return
        self.outgoing.put(
            {
                "type": "load",
                "room_version": self.wanted_version,
                "bodies": bodies_for(self.entities, self.epochs),
            }
        )
        # Anything taken hold of before the worker was ready stays out of the simulation.
        for entity_id in self.held:
            self.outgoing.put({"type": "hold", "id": entity_id, "epoch": self.epochs[entity_id]})

    def _next_epoch(self) -> int:
        self.last_epoch += 1
        return self.last_epoch

    def hold(self, entity_id: str) -> None:
        """Someone holds it: the session moves it, and physics leaves it alone."""
        self._command("hold", entity_id)

    def release(self, entity: SceneEntity) -> None:
        """Let go where it is: it falls from rest and settles."""
        self._command("release", entity.id, pose_of(entity))

    def place(self, entity: SceneEntity) -> None:
        """Put it where it is, at rest, as the phone's let-go and a direct move do."""
        self._command("place", entity.id, pose_of(entity))

    def _command(self, kind: str, entity_id: str, pose: dict[str, Any] | None = None) -> None:
        epoch = self.epochs[entity_id] = self._next_epoch()
        if kind == "hold":
            self.held.add(entity_id)
        else:
            self.held.discard(entity_id)
        if kind != "release" and entity_id in self.moving:
            self.moving.remove(entity_id)
        if self.state == "running":
            self.outgoing.put({"type": kind, "id": entity_id, "epoch": epoch, **(pose or {})})

    def stop(self) -> None:
        """Close the worker's input, so it exits; kill it if it doesn't. Never raises."""
        self.stopping = True
        process = self.process
        if process is None:
            return
        self.outgoing.put(None)
        try:
            process.wait(timeout=STOP_TIMEOUT)
        except subprocess.TimeoutExpired:
            process.kill()
            try:
                process.wait(timeout=STOP_TIMEOUT)
            except subprocess.TimeoutExpired:
                # The operating system reaps it; the server stops regardless.
                pass

    def _write_input(self) -> None:
        process = self.process
        assert process is not None and process.stdin is not None
        while (message := self.outgoing.get()) is not None:
            try:
                process.stdin.write(json.dumps(message) + "\n")
                process.stdin.flush()
            except OSError:
                # The output reader sees the worker exit and says why.
                return
        try:
            process.stdin.close()
        except OSError:
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
        if self.stderr_reader is not None:
            self.stderr_reader.join(timeout=STOP_TIMEOUT)
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
            self._send_room()
            self.on_change()
        elif kind == "loaded":
            # An answer for a room that has since been replaced is out of date.
            if message.get("room_version") != self.wanted_version:
                return
            self.room_version = message.get("room_version")
            self.bodies = message.get("bodies")
            self.on_change()
        elif kind == "poses":
            bodies: list[dict[str, Any]] = message.get("bodies") or []
            current = [
                body
                for body in bodies
                if self.epochs.get(body["id"]) == body["epoch"] and body["id"] not in self.held
            ]
            reported: list[str] = message.get("moving") or []
            moving = [entity_id for entity_id in reported if entity_id not in self.held]
            # A hold or place already took its body out of the moving list here; the worker's
            # answer to it changes nothing, and the devices aren't sent a state for it.
            if not current and moving == self.moving:
                return
            self.moving = moving
            self.on_moved(current)

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
        self.moving = []
        self.on_change()
