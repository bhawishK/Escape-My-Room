"""Serve the browser app and a direct, unauthenticated prototype connection."""

import asyncio
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

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
from backend.delivery import Outbox
from backend.env_file import load_env_file
from backend.errors import Refusal
from backend.preparation import (
    JobRequest,
    PreparationService,
    video_worker_from_environment,
    worker_from_environment,
)
from backend.prepared_room import ASSET_URL_PREFIX, PreparedRoomError, load_prepared_room
from backend.protocol import (
    AcquireMessage,
    CalibrateMessage,
    ClearAlignmentMessage,
    EntityTransformMessage,
    GripMessage,
    MarkerState,
    PoseMessage,
    PresenceMessage,
    PresenceState,
    ReleaseMessage,
    Role,
    RoomLoadedMessage,
    SelectMessage,
    WireModel,
)
from backend.sessions import PrototypeRoom
from backend.videos import (
    CompleteRequest,
    UploadRequest,
    VideoError,
    VideoLimits,
    VideoStore,
    probe_from_environment,
)

type Incoming = (
    PoseMessage
    | RoomLoadedMessage
    | EntityTransformMessage
    | CalibrateMessage
    | ClearAlignmentMessage
    | SelectMessage
    | AcquireMessage
    | ReleaseMessage
    | GripMessage
    | PresenceMessage
)
# The message model for each incoming `type`.
INCOMING: dict[str, type[Incoming]] = {
    "pose": PoseMessage,
    "room_loaded": RoomLoadedMessage,
    "entity_transform": EntityTransformMessage,
    "calibrate": CalibrateMessage,
    "clear_alignment": ClearAlignmentMessage,
    "select": SelectMessage,
    "acquire": AcquireMessage,
    "release": ReleaseMessage,
    "grip": GripMessage,
    "presence": PresenceMessage,
}

ROOM_VERSION_MISMATCH = (
    "room_version_mismatch",
    "Room version does not match. Reload and connect again.",
)

# Why a selection was refused, as the phone shows it.
SELECTION_REFUSALS = {
    "mismatch": ROOM_VERSION_MISMATCH,
    "unknown": ("unknown_entity", "That room object does not exist."),
    "not_selectable": ("entity_not_selectable", "That object is fixed and cannot be selected."),
    "held": ("selection_held", "Let go of the object before changing the selection."),
}


# Why a hold or release was refused, as the phone shows it.
MANIPULATION_REFUSALS = {
    "mismatch": ROOM_VERSION_MISMATCH,
    "not_selected": ("not_selected", "Select the object before holding it."),
    "not_tracked": ("not_tracked", "Turn on Walk with steps so the phone has a position."),
    "already_held": ("already_held", "The object is already being moved."),
    "controlled_by_other": ("controlled_by_other", "The other person is holding that object."),
    "stale": ("stale_manipulation", "That hold has already ended."),
    "unknown": ("unknown_entity", "That room object does not exist."),
    "not_selectable": ("entity_not_selectable", "That object is fixed and cannot be held."),
    "no_grip": ("no_grip", "The controller has no grip pose."),
}


# Five minutes of poses ten times a second fits in well under this.
MAX_MOVEMENT_LOG_BYTES = 2 * 1024 * 1024


class OverviewChoice(WireModel):
    image_id: str


def create_app(prepared_dir: Path | None = None, data_dir: Path | None = None) -> FastAPI:
    repository = Path(__file__).resolve().parents[1]
    data = data_dir or Path(os.environ.get("ESCAPE_ROOM_DATA_DIR") or repository / "data")
    captures = CaptureStore(data / "captures", CaptureLimits.from_environment())
    videos = VideoStore(data / "captures", VideoLimits.from_environment(), probe_from_environment())
    preparations = PreparationService(
        data / "jobs",
        captures,
        worker_from_environment(repository, captures),
        videos,
        video_worker_from_environment(repository, videos),
    )
    default = repository / "assets" / "prepared-room"
    directory = prepared_dir or Path(os.environ.get("ESCAPE_ROOM_PREPARED_DIR") or default)
    try:
        prepared = load_prepared_room(directory)
        load_error = None
    except PreparedRoomError as exc:
        prepared = None
        load_error = str(exc)
    delay_ms = float(os.environ.get("ESCAPE_ROOM_SIMULATED_DELAY_MS") or 0)
    if not 0 <= delay_ms <= 5000:
        raise ValueError("ESCAPE_ROOM_SIMULATED_DELAY_MS must be from 0 to 5000.")
    room = PrototypeRoom(load_error=load_error, delivery_delay=delay_ms / 1000)
    if prepared is not None:
        room.entities = [entity.model_copy(deep=True) for entity in prepared.entities]
        room.room_version = prepared.room_version
        room.splat_url = prepared.splat_url
        room.splat_phone_url = prepared.splat_phone_url
        room.landmarks = list(prepared.landmarks)
        room.map = prepared.map
        room.splat_placement = prepared.splat_placement

    app = FastAPI(title="Escape My Room prototype")

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

    movement_logs = data / "movement-logs"

    @app.post("/api/movement-logs", status_code=201)
    async def save_movement_log(request: Request) -> dict[str, Any]:
        """Keep a phone's movement log from a device check, for the developer to read."""
        declared = request.headers.get("content-length", "")
        if declared.isdigit() and int(declared) > MAX_MOVEMENT_LOG_BYTES:
            raise HTTPException(413, "The movement log is too large to save.")
        body = await request.body()
        if len(body) > MAX_MOVEMENT_LOG_BYTES:
            raise HTTPException(413, "The movement log is too large to save.")
        try:
            log = json.loads(body)
        except ValueError as exc:
            raise HTTPException(400, "A movement log must be JSON.") from exc
        if not isinstance(log, dict) or not isinstance(cast(dict[str, Any], log).get("entries"), list):
            raise HTTPException(400, "A movement log needs a list of entries.")
        entries = cast(list[Any], cast(dict[str, Any], log)["entries"])
        movement_logs.mkdir(parents=True, exist_ok=True)
        name = datetime.now(UTC).strftime("%Y%m%d-%H%M%S-%f") + ".json"
        # Written whole, then renamed, so a reader never sees half a log.
        pending = movement_logs / (name + ".tmp")
        pending.write_text(json.dumps(log, indent=2), encoding="utf-8")
        pending.replace(movement_logs / name)
        return {"file": name, "entries": len(entries)}

    @app.get("/api/captures")
    def list_captures() -> dict[str, list[dict[str, Any]]]:
        """Photo and video captures together, newest first; each says its `kind`."""
        listed = [describe(capture) for capture in captures.newest_first()]
        listed += [video.model_dump() for video in videos.newest_first()]
        return {"captures": sorted(listed, key=lambda c: c["created_at"], reverse=True)}

    @app.post("/api/captures", status_code=201)
    def create_capture(
        images: list[UploadFile], overview: int = Form(), instructions: str = Form("")
    ) -> dict[str, Any]:
        uploads = [Upload(image.filename or "photo", image.file.read()) for image in images]
        return describe(captures.create(uploads, instructions, overview))

    @app.get("/api/captures/{capture_id}")
    def get_capture(capture_id: str) -> dict[str, Any]:
        video = videos.get(capture_id)
        return video.model_dump() if video else describe(captures.get(capture_id))

    @app.put("/api/captures/{capture_id}/overview")
    def choose_overview(capture_id: str, choice: OverviewChoice) -> dict[str, Any]:
        return describe(captures.set_overview(capture_id, choice.image_id))

    @app.get("/api/captures/{capture_id}/images/{image_id}/{kind}")
    def capture_image(capture_id: str, image_id: str, kind: ImageKind) -> FileResponse:
        path, media_type = captures.photo_file(capture_id, image_id, kind)
        return FileResponse(path, media_type=media_type)

    @app.post("/api/videos", status_code=201)
    def start_video(request: UploadRequest) -> dict[str, Any]:
        return videos.start(request).model_dump()

    @app.put("/api/videos/{upload_id}/chunks/{number}", status_code=204)
    async def video_chunk(upload_id: str, number: int, request: Request) -> None:
        largest = videos.limits.chunk_bytes
        too_large = VideoError(f"A chunk is at most {largest} bytes.", 413)
        declared = request.headers.get("content-length", "")
        if declared.isdigit() and int(declared) > largest:
            raise too_large
        # Read as it streams, so a chunk with no declared length is still cut off at the limit.
        data = bytearray()
        async for piece in request.stream():
            data += piece
            if len(data) > largest:
                raise too_large
        await asyncio.to_thread(videos.put_chunk, upload_id, number, bytes(data))

    @app.post("/api/videos/{upload_id}/complete", status_code=201)
    def complete_video(upload_id: str, request: CompleteRequest) -> dict[str, Any]:
        return videos.complete(upload_id, request).model_dump()

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
        presence_sequence = 0
        grip_sequence = 0
        outbox = Outbox(socket, room.delivery_delay)

        async def reject(code: str, message: str) -> None:
            outbox.reply({"type": "error", "code": code, "message": message})

        try:
            async with room.lock:
                await socket.accept()
                previous = room.sockets.get(role)
                room.sockets[role] = socket
                room.outboxes[role] = outbox
                room.loaded_versions[role] = None
                room.alignment[role] = Alignment()
                room.presence[role] = PresenceState()
                room.presence_seen.pop(role, None)
                room.cancel_presence_timer(role)
                if role == "mobile_master":
                    room.marker = MarkerState()
                    room.selection = None
                # A new connection does not inherit the hold. The object stays at its last place.
                if room.manipulation is not None and room.manipulation.owner == role:
                    room.drop()
                if previous is not None:
                    try:
                        await asyncio.wait_for(
                            previous.close(code=1000, reason="Device connected in another tab"),
                            timeout=2,
                        )
                    except (RuntimeError, OSError, TimeoutError):
                        pass
                room.revision += 1
                outbox.reply({"type": "welcome", "state": room.snapshot()})
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
                message_type = cast(dict[str, Any], payload).get("type")
                model = INCOMING.get(message_type) if isinstance(message_type, str) else None
                if model is None:
                    await reject("invalid_message", "Send a valid XR pose using the contract.")
                    continue
                try:
                    incoming = model.model_validate(payload)
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
                    elif isinstance(incoming, PresenceMessage):
                        if incoming.sequence <= presence_sequence:
                            await reject(
                                "stale_sequence",
                                "Presence sequences must increase on this socket.",
                            )
                            continue
                        presence_sequence = incoming.sequence
                        room.accept_presence(role, incoming)
                        await room.broadcast()
                    elif isinstance(incoming, RoomLoadedMessage):
                        result = room.accept_room_version(role, incoming.room_version)
                        if result == "mismatch":
                            await reject(*ROOM_VERSION_MISMATCH)
                            await outbox.close(flush=True)
                            await socket.close(code=1008, reason="Room version mismatch")
                            return
                        if result == "unavailable":
                            await reject(
                                "room_unavailable",
                                room.load_error or "Prepared room is unavailable.",
                            )
                            continue
                        await room.broadcast()
                    elif isinstance(incoming, ClearAlignmentMessage):
                        room.clear_alignment(role)
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
                    elif isinstance(incoming, AcquireMessage | ReleaseMessage | GripMessage):
                        if isinstance(incoming, GripMessage):
                            if role != "vr_solver":
                                await reject(
                                    "role_forbidden",
                                    "Only the headset moves an object with the controller.",
                                )
                                continue
                            if incoming.sequence <= grip_sequence:
                                await reject(
                                    "stale_sequence",
                                    "Grip sequences must increase on this socket.",
                                )
                                continue
                            grip_sequence = incoming.sequence
                            orientation = incoming.orientation
                            result = room.accept_grip(
                                role,
                                incoming.manipulation_id,
                                incoming.sequence,
                                incoming.position,
                                (orientation.x, orientation.y, orientation.z, orientation.w),
                            )
                        elif isinstance(incoming, AcquireMessage):
                            grip = None
                            if incoming.position is not None and incoming.orientation is not None:
                                orientation = incoming.orientation
                                grip = (
                                    incoming.position,
                                    (orientation.x, orientation.y, orientation.z, orientation.w),
                                )
                            elif incoming.position is not None or incoming.orientation is not None:
                                await reject(
                                    "invalid_message",
                                    "A grip pose needs both a position and an orientation.",
                                )
                                continue
                            result = room.acquire(role, incoming.room_version, incoming.id, grip)
                        else:
                            result = room.release(role, incoming.manipulation_id)
                        if result == "unavailable":
                            await reject(
                                "room_unavailable",
                                room.load_error or "Prepared room is unavailable.",
                            )
                            continue
                        if result != "ok":
                            await reject(*MANIPULATION_REFUSALS[result])
                            continue
                        await room.broadcast()
                    elif isinstance(incoming, SelectMessage):
                        if role != "mobile_master":
                            await reject("role_forbidden", "Only the phone selects objects.")
                            continue
                        result = room.select(incoming.room_version, incoming.id)
                        rejected = None
                        if result == "unavailable":
                            rejected = {
                                "code": "room_unavailable",
                                "message": room.load_error or "Prepared room is unavailable.",
                            }
                        elif result != "ok":
                            code, text = SELECTION_REFUSALS[result]
                            rejected = {"code": code, "message": text}
                        # Selection is private intent: only the phone hears the result.
                        outbox.reply(
                            {"type": "selection", "id": room.selection, "rejected": rejected}
                        )
                    else:
                        result = room.move_entity(incoming.id, incoming.position)
                        if result == "static":
                            await reject("entity_not_movable", "Static furniture cannot be moved.")
                            continue
                        if result == "unknown":
                            await reject("unknown_entity", "That room object does not exist.")
                            continue
                        if result == "controlled":
                            await reject("entity_controlled", "That object is being held.")
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
                if room.outboxes.get(role) is outbox:
                    del room.outboxes[role]
                if room.sockets.get(role) is socket:
                    room.disconnect(role)
                    await room.broadcast()
            await outbox.close()

    if directory.is_dir():
        app.mount(ASSET_URL_PREFIX, StaticFiles(directory=directory), name="prepared-room")
    dist = repository / "frontend" / "dist"
    if dist.is_dir():
        app.mount("/", StaticFiles(directory=dist, html=True), name="frontend")
    return app


load_env_file()
app = create_app()
