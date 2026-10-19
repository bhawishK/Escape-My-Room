"""Serve the browser app and a direct, unauthenticated prototype connection."""

import asyncio
import json
import os
from pathlib import Path
from typing import Any

from fastapi import (
    FastAPI,
    Form,
    HTTPException,
    Request,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from backend.alignment import Alignment
from backend.captures import (
    Capture,
    CaptureLimits,
    CaptureStore,
    ImageKind,
    Upload,
)
from backend.errors import Refusal
from backend.preparation import JobRequest, PreparationService, worker_from_environment
from backend.prepared_room import ASSET_URL_PREFIX, PreparedRoomError, load_prepared_room
from backend.protocol import (
    CalibrateMessage,
    EntityTransformMessage,
    MarkerState,
    PoseMessage,
    Role,
    RoomLoadedMessage,
    WireModel,
)
from backend.sessions import PrototypeRoom


class OverviewChoice(WireModel):
    image_id: str


def create_app(prepared_dir: Path | None = None, data_dir: Path | None = None) -> FastAPI:
    app = FastAPI(title="Escape My Room prototype")
    repository = Path(__file__).resolve().parents[1]
    data = data_dir or Path(os.environ.get("ESCAPE_ROOM_DATA_DIR") or repository / "data")
    captures = CaptureStore(data / "captures", CaptureLimits.from_environment())
    preparations = PreparationService(
        data / "jobs", captures, worker_from_environment(repository)
    )
    default = repository / "assets" / "prepared-room"
    directory = prepared_dir or Path(os.environ.get("ESCAPE_ROOM_PREPARED_DIR") or default)
    try:
        prepared = load_prepared_room(directory)
        load_error = None
    except PreparedRoomError as exc:
        prepared = None
        load_error = str(exc)
    room = PrototypeRoom(load_error=load_error)
    if prepared is not None:
        room.entities = [entity.model_copy(deep=True) for entity in prepared.entities]
        room.markers = prepared.markers
        room.room_version = prepared.room_version

    @app.get("/api/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/room")
    async def prepared_room() -> dict[str, Any]:
        if room.load_error is not None or room.room_version is None:
            raise HTTPException(
                status_code=503, detail=room.load_error or "Prepared room is unavailable."
            )
        description = dict(room.snapshot()["room"])
        description.pop("loaded_by", None)
        return description

    @app.exception_handler(Refusal)
    async def refused(_: Request, exc: Refusal) -> JSONResponse:
        return JSONResponse(status_code=exc.status, content={"detail": str(exc)})

    def describe(capture: Capture) -> dict[str, Any]:
        """The capture as clients see it, with each photo's original and processed URLs."""
        data = capture.model_dump()
        for image in data["images"]:
            for kind in ("original", "processed"):
                path = app.url_path_for(
                    "capture_image", capture_id=capture.id, image_id=image["id"], kind=kind
                )
                image[f"{kind}_url"] = str(path)
        return data

    @app.get("/api/captures")
    def list_captures() -> dict[str, list[dict[str, Any]]]:
        return {"captures": [describe(capture) for capture in captures.newest_first()]}

    @app.post("/api/captures", status_code=201)
    def create_capture(
        images: list[UploadFile], overview: int = Form(), instructions: str = Form("")
    ) -> dict[str, Any]:
        uploads = [Upload(image.filename or "photo", image.file.read()) for image in images]
        return describe(captures.create(uploads, instructions, overview))

    @app.get("/api/captures/{capture_id}")
    def get_capture(capture_id: str) -> dict[str, Any]:
        return describe(captures.get(capture_id))

    @app.put("/api/captures/{capture_id}/overview")
    def choose_overview(capture_id: str, choice: OverviewChoice) -> dict[str, Any]:
        return describe(captures.set_overview(capture_id, choice.image_id))

    @app.get("/api/captures/{capture_id}/images/{image_id}/{kind}")
    def capture_image(capture_id: str, image_id: str, kind: ImageKind) -> FileResponse:
        path, media_type = captures.photo_file(capture_id, image_id, kind)
        return FileResponse(path, media_type=media_type)

    @app.get("/api/preparations")
    def list_preparations() -> dict[str, list[dict[str, Any]]]:
        return {"jobs": [job.model_dump() for job in preparations.newest_first()]}

    @app.post("/api/preparations", status_code=202)
    def submit_preparation(request: JobRequest) -> dict[str, Any]:
        return preparations.submit(request).model_dump()

    @app.get("/api/preparations/{job_id}")
    def get_preparation(job_id: str) -> dict[str, Any]:
        return preparations.get(job_id).model_dump()

    @app.get("/api/preparations/{job_id}/files/{relative:path}")
    def preparation_file(job_id: str, relative: str) -> FileResponse:
        return FileResponse(preparations.file(job_id, relative))

    @app.websocket("/api/ws")
    async def room_socket(socket: WebSocket, role: Role) -> None:
        sequence = 0

        async def reject(code: str, message: str) -> None:
            await socket.send_json({"type": "error", "code": code, "message": message})

        try:
            async with room.lock:
                await socket.accept()
                previous = room.sockets.get(role)
                room.sockets[role] = socket
                room.loaded_versions[role] = None
                room.alignment[role] = Alignment()
                if role == "mobile_master":
                    room.marker = MarkerState()
                if previous is not None:
                    try:
                        await asyncio.wait_for(
                            previous.close(code=1000, reason="Device connected in another tab"),
                            timeout=2,
                        )
                    except (RuntimeError, OSError, TimeoutError):
                        pass
                room.revision += 1
                await socket.send_json({"type": "welcome", "state": room.snapshot()})
                await room.broadcast(exclude=socket)
            while True:
                message = await socket.receive()
                if message["type"] == "websocket.disconnect":
                    raise WebSocketDisconnect(message.get("code", 1000))
                raw = message.get("text")
                if not isinstance(raw, str) or len(raw.encode("utf-8")) > 16384:
                    await reject("invalid_message", "Send a JSON text pose of at most 16 KiB.")
                    continue
                try:
                    payload = json.loads(raw)
                except ValueError:
                    await reject("invalid_message", "Send a valid XR pose using the contract.")
                    continue
                if not isinstance(payload, dict):
                    await reject("invalid_message", "Send a valid XR pose using the contract.")
                    continue
                try:
                    if payload.get("type") == "pose":
                        incoming: (
                            PoseMessage
                            | RoomLoadedMessage
                            | EntityTransformMessage
                            | CalibrateMessage
                        ) = PoseMessage.model_validate(payload)
                    elif payload.get("type") == "room_loaded":
                        incoming = RoomLoadedMessage.model_validate(payload)
                    elif payload.get("type") == "entity_transform":
                        incoming = EntityTransformMessage.model_validate(payload)
                    elif payload.get("type") == "calibrate":
                        incoming = CalibrateMessage.model_validate(payload)
                    else:
                        await reject("invalid_message", "Send a valid XR pose using the contract.")
                        continue
                except ValidationError:
                    await reject("invalid_message", "Send a valid XR pose using the contract.")
                    continue
                async with room.lock:
                    if room.sockets.get(role) is not socket:
                        return
                    if isinstance(incoming, PoseMessage):
                        if role != "mobile_master":
                            await reject("role_forbidden", "Only the phone sends the marker pose.")
                            continue
                        if incoming.sequence <= sequence:
                            await reject(
                                "stale_sequence", "Pose sequences must increase on this socket."
                            )
                            continue
                        sequence = incoming.sequence
                        room.accept_pose(incoming)
                        await room.broadcast()
                    elif isinstance(incoming, RoomLoadedMessage):
                        result = room.accept_room_version(role, incoming.room_version)
                        if result == "mismatch":
                            await reject(
                                "room_version_mismatch",
                                "Room version does not match. Reload and connect again.",
                            )
                            await socket.close(code=1008, reason="Room version mismatch")
                            return
                        if result == "unavailable":
                            await reject(
                                "room_unavailable",
                                room.load_error or "Prepared room is unavailable.",
                            )
                            continue
                        await room.broadcast()
                    elif isinstance(incoming, CalibrateMessage):
                        result = room.accept_alignment(role, incoming.yaw, incoming.origin)
                        if result == "unavailable":
                            await reject(
                                "room_unavailable",
                                room.load_error or "Prepared room is unavailable.",
                            )
                            continue
                        await room.broadcast()
                    else:
                        result = room.move_entity(incoming.id, incoming.position)
                        if result == "static":
                            await reject("entity_not_movable", "Static furniture cannot be moved.")
                            continue
                        if result == "unknown":
                            await reject("unknown_entity", "That room object does not exist.")
                            continue
                        if result == "unavailable":
                            await reject(
                                "room_unavailable",
                                room.load_error or "Prepared room is unavailable.",
                            )
                            continue
                        await room.broadcast()
        except WebSocketDisconnect:
            pass
        finally:
            async with room.lock:
                if room.sockets.get(role) is socket:
                    room.disconnect(role)
                    await room.broadcast()

    if directory.is_dir():
        app.mount(ASSET_URL_PREFIX, StaticFiles(directory=directory), name="prepared-room")
    dist = repository / "frontend" / "dist"
    if dist.is_dir():
        app.mount("/", StaticFiles(directory=dist, html=True), name="frontend")
    return app


app = create_app()
