"""Serve the browser app and a direct, unauthenticated prototype connection."""

import asyncio
import json
import logging
import math
import os
import re
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import numpy as np
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
from backend.filming_check import CheckRequest, FilmingChecks
from backend.furniture import Catalogue
from backend.furniture_generation import (
    FurnitureGeneration,
    GenerationError,
    GenerationRequest,
    generator_from_environment,
    timeout_from_environment,
)
from backend.hazard_generation import (
    HazardGeneration,
    HazardJob,
    HazardRequest,
    HazardTarget,
    RoomPicture,
)
from backend.hazard_placement import Box
from backend.live_room import LiveRoomError, LiveRooms
from backend.physics import PhysicsWorker
from backend.preparation import (
    RECONSTRUCTION_FOLDER,
    JobRequest,
    PreparationService,
    video_worker_from_environment,
    worker_from_environment,
)
from backend.prepared_room import (
    ASSET_URL_PREFIX,
    LoadedRoom,
    PreparedRoomError,
    load_prepared_room,
)
from backend.protocol import (
    AcquireMessage,
    AddFurnitureMessage,
    AddHazardMessage,
    CalibrateMessage,
    CancelDrillMessage,
    ClearAlignmentMessage,
    DesignerHandMessage,
    EntityTransformMessage,
    GripMessage,
    GuideMessage,
    HazardControlMessage,
    MarkerState,
    PoseMessage,
    PrepareDrillMessage,
    PresenceMessage,
    PresenceState,
    ReleaseMessage,
    RemoveFurnitureMessage,
    ResizeFurnitureMessage,
    Role,
    RoomLoadedMessage,
    SelectMessage,
    VoiceMuteMessage,
    VoiceReadyMessage,
    VoiceSignalMessage,
    WireModel,
)
from backend.room_object_picture import PictureRefused, object_picture
from backend.room_views import RenderFailure
from backend.sessions import Drill, PrototypeRoom
from backend.videos import (
    CompleteRequest,
    UploadRequest,
    VideoError,
    VideoLimits,
    VideoStore,
    probe_from_environment,
)
from backend.voice import voice_config_from_environment
from backend.vps.service import Positioning

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
    | VoiceReadyMessage
    | VoiceMuteMessage
    | VoiceSignalMessage
    | AddFurnitureMessage
    | RemoveFurnitureMessage
    | AddHazardMessage
    | HazardControlMessage
    | PrepareDrillMessage
    | CancelDrillMessage
    | ResizeFurnitureMessage
    | DesignerHandMessage
    | GuideMessage
)
LOG = logging.getLogger(__name__)

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
    "voice_ready": VoiceReadyMessage,
    "voice_mute": VoiceMuteMessage,
    "voice_signal": VoiceSignalMessage,
    "add_furniture": AddFurnitureMessage,
    "remove_furniture": RemoveFurnitureMessage,
    "add_hazard": AddHazardMessage,
    "start_hazard": HazardControlMessage,
    "stop_hazard": HazardControlMessage,
    "remove_hazard": HazardControlMessage,
    "prepare_drill": PrepareDrillMessage,
    "cancel_drill": CancelDrillMessage,
    "resize_furniture": ResizeFurnitureMessage,
    "designer_hand": DesignerHandMessage,
    "guide": GuideMessage,
}

# Why a voice call set-up message was not passed on (#13), as the page shows it.
VOICE_REFUSALS = {
    "not_ready": ("voice_not_ready", "Start voice before setting up a call."),
    "peer_gone": ("voice_peer_unavailable", "The other person is not connected."),
    "peer_not_ready": ("voice_peer_not_ready", "The other person has not started voice."),
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

# Why a piece of furniture was not placed (#181).
FURNITURE_REFUSALS = {
    "mismatch": ROOM_VERSION_MISMATCH,
    "unknown_item": ("unknown_furniture", "That piece is not in the furniture catalogue."),
    "outside": ("outside_room", "Place furniture with all of it on the room's floor."),
    "no_room": ("no_room", "There is no free floor near there for that piece."),
    "too_many": ("too_much_furniture", "The room is full. Take a piece away before adding more."),
    "unknown": ("unknown_entity", "That room object does not exist."),
    "not_furniture": ("not_furniture", "Only placed furniture can be taken away or resized."),
    "controlled_by_other": ("controlled_by_other", "The other person is holding that piece."),
}


# Why a hazard message was refused (#229).
HAZARD_REFUSALS = {
    "mismatch": ROOM_VERSION_MISMATCH,
    "unknown": ("unknown_hazard", "There is no such hazard."),
    "too_many": ("too_many_hazards", "Take a hazard away before adding another."),
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


# The designer's hand is passed to the phone at most this often, in seconds (#185). The headset
# sends one every 50 ms; this only stops a flood, never a hand delayed and bunched by the network.
HAND_SECONDS = 0.025

CARRYING = "Someone is carrying the box. Let go of it before changing the room."

# Five minutes of poses ten times a second fits in well under this.
MAX_MOVEMENT_LOG_BYTES = 2 * 1024 * 1024
# A phone frame to locate is a JPEG of about 640 px, tens of kilobytes (#133).
MAX_FRAME_BYTES = 1024 * 1024


class OverviewChoice(WireModel):
    image_id: str


def create_app(
    prepared_dir: Path | None = None,
    data_dir: Path | None = None,
    positioning: Positioning | None = None,
) -> FastAPI:
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
    configured = prepared_dir or Path(os.environ.get("ESCAPE_ROOM_PREPARED_DIR") or default)
    # The configured room, unless a reconstruction was made live since (#138).
    live_rooms = LiveRooms(data, configured)
    try:
        prepared = live_rooms.load()
        load_error = None
    except PreparedRoomError as exc:
        prepared = None
        load_error = str(exc)
    delay_ms = float(os.environ.get("ESCAPE_ROOM_SIMULATED_DELAY_MS") or 0)
    if not 0 <= delay_ms <= 5000:
        raise ValueError("ESCAPE_ROOM_SIMULATED_DELAY_MS must be from 0 to 5000.")
    catalogue = Catalogue()
    # Furniture made from a description (#186), kept with the data so it survives a restart.
    # The server's event loop, once it runs, for news from worker threads.
    running: dict[str, asyncio.AbstractEventLoop] = {}

    def piece_added(_item: object) -> None:
        """A piece joined the catalogue (#187): tell both devices, from the job's thread."""
        loop = running.get("loop")
        if loop is not None and not loop.is_closed():
            loop.call_soon_threadsafe(lambda: room.track(announce_catalogue()))

    async def announce_catalogue() -> None:
        async with room.lock:
            room.catalogue_version += 1
            room.revision += 1
            await room.broadcast()

    # One generator for furniture and hazards (#222).
    generator = generator_from_environment()
    generation = FurnitureGeneration(
        data / "furniture",
        catalogue,
        generator,
        timeout_from_environment(),
        on_added=piece_added,
    )
    room = PrototypeRoom(load_error=load_error, delivery_delay=delay_ms / 1000)

    def object_name(entity_id: str) -> str:
        """A room object's name for the hazard's video: its label, as people would say it."""
        entity = next((e for e in room.entities if e.id == entity_id), None)
        return (entity.label if entity else entity_id.replace("_", " ")).lower()

    def room_picture(entity_id: str) -> RoomPicture:
        """An object in the live room, cut from its own splat (#223), or why it can't be; with
        its box and the side it was pictured from, to place its hazard (#228)."""
        try:
            pictured = object_picture(live_rooms.directory, room.entities, entity_id)
            entity = next(e for e in room.entities if e.id == entity_id)
            eye, middle = pictured.view.position, pictured.view.look_at
            across = (eye[0] - middle[0], eye[2] - middle[2])
            length = math.hypot(*across) or 1.0
            box = Box(
                x=entity.position.x,
                y=entity.position.y,
                z=entity.position.z,
                yaw=2 * math.atan2(entity.rotation.y, entity.rotation.w),
                width=entity.size.width,
                depth=entity.size.depth,
            )
            return RoomPicture(pictured.png, box, (across[0] / length, across[1] / length))
        except PictureRefused as exc:
            raise GenerationError("room_picture", str(exc)) from exc
        except RenderFailure as exc:
            LOG.warning("Picturing %s from the room's splat failed: %s", entity_id, exc)
            raise GenerationError("room_picture") from exc

    # Hazards (#222, part of #221), each starting from a picture: an object in the room's own
    # (#223), or a new object's drawn from words.
    def hazard_finished(job: HazardJob) -> None:
        """A fire job ended (#234): if it was the drill's, its fire goes into the room."""
        loop = running.get("loop")
        if loop is not None and not loop.is_closed():
            loop.call_soon_threadsafe(lambda: room.track(drill_job_done(job)))

    async def drill_job_done(job: HazardJob) -> None:
        async with room.lock:
            drill = room.drill
            if drill is None or drill.job != job.id:
                return
            if job.state == "ready" and job.asset is not None:
                room.drill_ready(job.asset)
            else:
                drill.state = "failed"
                drill.error = job.error or "The fire couldn't be made."
            room.revision += 1
            await room.broadcast()

    hazards = HazardGeneration(
        data / "hazards",
        generator,
        room_picture,
        object_name,
        timeout_from_environment(),
        room_name=lambda: live_rooms.directory.name,
        on_finished=hazard_finished,
    )
    # The server's one physics simulation (#159), started and stopped with the server.
    physics = PhysicsWorker(room.physics_changed, room.physics_moved)
    room.physics = physics
    # Locates phone frames against the live room's positioning map (#133).
    positioning = positioning or Positioning()

    def show(loaded: LoadedRoom) -> None:
        """Make this the shared room. Devices see its version change and reload it."""
        room.entities = [entity.model_copy(deep=True) for entity in loaded.entities]
        room.room_version = loaded.room_version
        room.splat_url = loaded.splat_url
        room.splat_phone_url = loaded.splat_phone_url
        room.landmarks = list(loaded.landmarks)
        room.map = loaded.map
        room.splat_placement = loaded.splat_placement
        room.load_error = None
        # Hazards and the drill belong to the room they were placed in.
        room.hazards = []
        room.drill = None
        physics.load(loaded.room_version, room.entities)
        positioning.use(live_rooms.directory, loaded.splat_placement, loaded.room_version)

    if prepared is not None:
        show(prepared)
    # One change of the live room at a time.
    changing_room = asyncio.Lock()

    async def swap_in(loaded: LoadedRoom, record: Callable[[], object]) -> None:
        """Make a checked room live for everyone; refused while someone carries the box."""
        async with room.lock:
            if room.manipulation is not None:
                raise LiveRoomError(CARRYING, 409)
            record()
            show(loaded)
            room.selection = None
            # Calibrations, positions and loaded versions belong to the old room.
            room.alignment = {"mobile_master": Alignment(), "vr_solver": Alignment()}
            room.marker = MarkerState()
            room.presence = {"mobile_master": PresenceState(), "vr_solver": PresenceState()}
            room.loaded_versions = {"mobile_master": None, "vr_solver": None}
            room.revision += 1
            await room.broadcast()

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        running["loop"] = asyncio.get_running_loop()
        physics.start()
        try:
            yield
        finally:
            await asyncio.to_thread(physics.stop)

    app = FastAPI(title="Escape My Room prototype", lifespan=lifespan)

    @app.get("/api/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    # Read once, so a mistake in the settings stops the server at start-up with its reason.
    voice_config = voice_config_from_environment()

    # The filming coach's check (#100): Qwen looks at a small frame, within each recording's budget.
    filming_checks = FilmingChecks.from_environment()

    @app.post("/api/coach/check")
    def coach_check(request: CheckRequest) -> dict[str, str | None]:
        """A prompt for the frame being filmed, or none; failures are quiet (#100)."""
        return filming_checks.check(request)

    @app.get("/api/voice/config")
    def voice_settings() -> dict[str, Any]:
        """The STUN and TURN servers the pages give WebRTC for the voice call (#172)."""
        return voice_config

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
        if not isinstance(log, dict) or not isinstance(
            cast(dict[str, Any], log).get("entries"), list
        ):
            raise HTTPException(400, "A movement log needs a list of entries.")
        entries = cast(list[Any], cast(dict[str, Any], log)["entries"])
        movement_logs.mkdir(parents=True, exist_ok=True)
        name = datetime.now(UTC).strftime("%Y%m%d-%H%M%S-%f") + ".json"
        # Written whole, then renamed, so a reader never sees half a log.
        pending = movement_logs / (name + ".tmp")
        pending.write_text(json.dumps(log, indent=2), encoding="utf-8")
        pending.replace(movement_logs / name)
        return {"file": name, "entries": len(entries)}

    @app.post("/api/localize")
    def localize(
        image: UploadFile,
        fx: float = Form(gt=0),
        fy: float = Form(gt=0),
        cx: float = Form(),
        cy: float = Form(),
        width: int = Form(gt=0, le=4096),
        height: int = Form(gt=0, le=4096),
    ) -> dict[str, Any]:
        """Where the phone's camera stood for one frame, in room metres (#133). `fx`, `fy`, `cx`
        and `cy` are its lens in that JPEG's pixels."""
        jpeg = image.file.read(MAX_FRAME_BYTES + 1)
        if len(jpeg) > MAX_FRAME_BYTES:
            raise HTTPException(status_code=413, detail="The frame is larger than 1 MB.")
        K = np.array([[fx, 0.0, cx], [0.0, fy, cy], [0.0, 0.0, 1.0]])
        return positioning.locate(jpeg, K, (width, height)).wire()

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

    @app.post("/api/preparations/{job_id}/activate")
    async def make_live(job_id: str) -> dict[str, Any]:
        """Build a reviewed reconstruction into a room and make it live, without a restart."""
        job = preparations.get(job_id)
        if job.state != "awaiting_review" or job.reconstruction is None:
            raise LiveRoomError("Only a finished reconstruction can be made live.", 409)
        if room.manipulation is not None:
            raise LiveRoomError(CARRYING, 409)
        async with changing_room:
            version = live_rooms.next_version(room.room_version)
            source = preparations.root / job.id / RECONSTRUCTION_FOLDER
            loaded, folder = await asyncio.to_thread(live_rooms.build, job.id, source, version)
            await swap_in(loaded, lambda: live_rooms.record(folder, version, job.id))
            return live_rooms.describe(loaded).model_dump()

    @app.post("/api/rooms/restore")
    async def restore_room() -> dict[str, Any]:
        """Make the room before the live one live again, under a new room version."""
        async with changing_room:
            previous = live_rooms.previous
            if previous is None:
                raise LiveRoomError("There is no earlier room to go back to.", 409)
            version = live_rooms.next_version(room.room_version)
            directory = Path(previous.directory)
            try:
                loaded = load_prepared_room(directory)
            except PreparedRoomError as exc:
                message = f"The earlier room can no longer be loaded: {exc}"
                raise LiveRoomError(message, 422) from exc
            loaded.room_version = version
            await swap_in(loaded, lambda: live_rooms.record(directory, version, previous.job_id))
            return live_rooms.describe(loaded).model_dump()

    @app.get("/api/furniture")
    async def furniture_catalogue() -> dict[str, Any]:
        """The pieces the designer can place, with their true sizes and models (#181)."""
        items = catalogue.listed()
        # Without the built-in file, pieces made from descriptions (#186) are still listed.
        if catalogue.error is not None and not items:
            raise HTTPException(503, catalogue.error)
        return {"items": [item.model_dump() for item in items]}

    @app.post("/api/furniture/jobs", status_code=202)
    async def start_generation(request: GenerationRequest) -> dict[str, Any]:
        """Make a piece from a description (#186): a picture first, then the 3D piece."""
        if not generation.available:
            raise HTTPException(
                503, "Making furniture from a description isn't set up on this server."
            )
        return generation.start(request.description).model_dump()

    @app.post("/api/furniture/jobs/photo", status_code=202)
    def start_photo_generation(image: UploadFile, description: str = Form("")) -> dict[str, Any]:
        """Make a piece from the resident's photo (#187), checked with the photo rules."""
        if not generation.available:
            raise HTTPException(503, "Making furniture from a photo isn't set up on this server.")
        if len(description) > 200:
            raise HTTPException(422, "Describe the piece in at most 200 characters.")
        # No more than the photo limit and one byte is read: anything larger is refused.
        data = image.file.read(captures.limits.max_image_bytes + 1)
        picture = captures.photo_png(Upload(image.filename or "photo", data))
        try:
            return generation.start_photo(picture, description).model_dump()
        except OSError as exc:
            raise HTTPException(500, "The photo couldn't be saved on the server.") from exc

    @app.get("/api/furniture/jobs/{job_id}")
    async def generation_job(job_id: str) -> dict[str, Any]:
        job = generation.get(job_id)
        if job is None:
            raise HTTPException(404, "That furniture job does not exist.")
        return job.model_dump()

    @app.post("/api/furniture/jobs/{job_id}/cancel")
    async def cancel_generation(job_id: str) -> dict[str, Any]:
        job = generation.cancel(job_id)
        if job is None:
            raise HTTPException(404, "That furniture job does not exist.")
        return job.model_dump()

    @app.get("/api/furniture/jobs/{job_id}/image")
    async def generation_image(job_id: str) -> FileResponse:
        path = generation.image(job_id) if re.fullmatch(r"[0-9a-f]{12}", job_id) else None
        if path is None:
            raise HTTPException(404, "That job has no picture yet.")
        return FileResponse(path, media_type="image/png")

    @app.get("/api/furniture/generated/{item_id}/model.glb")
    async def generated_model(item_id: str) -> FileResponse:
        path = generation.model(item_id)
        if path is None:
            raise HTTPException(404, "That piece does not exist.")
        return FileResponse(path, media_type="model/gltf-binary")

    @app.post("/api/hazards/jobs", status_code=202)
    async def start_hazard(request: HazardRequest) -> dict[str, Any]:
        """Make a hazard (#222): a picture, a video of the hazard, then its 3D animation."""
        if not hazards.available:
            raise HTTPException(503, "Making hazards isn't set up on this server.")
        entity = request.target.entity
        if entity is not None and not any(e.id == entity for e in room.entities):
            raise HTTPException(422, f"There's no {entity} in the room.")
        return hazards.start(request).model_dump()

    @app.get("/api/hazards/jobs/{job_id}")
    async def hazard_job(job_id: str) -> dict[str, Any]:
        job = hazards.get(job_id)
        if job is None:
            raise HTTPException(404, "That hazard job does not exist.")
        return job.model_dump()

    @app.post("/api/hazards/jobs/{job_id}/cancel")
    async def cancel_hazard(job_id: str) -> dict[str, Any]:
        job = hazards.cancel(job_id)
        if job is None:
            raise HTTPException(404, "That hazard job does not exist.")
        return job.model_dump()

    @app.get("/api/hazards/jobs/{job_id}/image")
    async def hazard_image(job_id: str) -> FileResponse:
        path = hazards.file(job_id, "picture.png")
        if path is None:
            raise HTTPException(404, "That job has no picture yet.")
        return FileResponse(path, media_type="image/png")

    @app.get("/api/hazards/jobs/{job_id}/video")
    async def hazard_video(job_id: str) -> FileResponse:
        path = hazards.file(job_id, "video.mp4")
        if path is None:
            raise HTTPException(404, "That job has no video yet.")
        return FileResponse(path, media_type="video/mp4")

    @app.get("/api/hazards/{asset_id}/frames/{name}")
    async def hazard_frame(asset_id: str, name: str) -> FileResponse:
        found = re.fullmatch(r"(\d{1,4})\.spz", name)
        path = hazards.frame(asset_id, int(found.group(1))) if found else None
        if path is None:
            raise HTTPException(404, "That hazard frame does not exist.")
        return FileResponse(path, media_type="application/octet-stream")

    @app.get("/api/furniture/{name}")
    async def furniture_model(name: str) -> FileResponse:
        path = catalogue.file(name)
        if path is None:
            raise HTTPException(404, "That furniture file does not exist.")
        return FileResponse(path)

    @app.get("/api/rooms/live")
    async def live_room() -> dict[str, Any]:
        try:
            loaded = live_rooms.load()
        except PreparedRoomError:
            loaded = None
        return live_rooms.describe(loaded).model_dump()

    @app.get(ASSET_URL_PREFIX + "/{relative:path}")
    async def room_file(relative: str) -> FileResponse:
        """A file of the live room. No-cache: after a room change the same name is a new file."""
        root = live_rooms.directory.resolve()
        path = (root / relative).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise HTTPException(404, "That room file does not exist.")
        return FileResponse(path, headers={"Cache-Control": "no-cache"})

    @app.get("/api/preparations/{job_id}/files/{relative:path}")
    def preparation_file(job_id: str, relative: str) -> FileResponse:
        return FileResponse(preparations.file(job_id, relative))

    @app.websocket("/api/ws")
    async def room_socket(socket: WebSocket, role: Role) -> None:
        sequence = 0
        presence_sequence = 0
        grip_sequence = 0
        hand_sequence = 0
        # When this headset's hand was last passed to the phone (#185), on the loop's clock.
        hand_passed_at = -math.inf
        guide_sequence = 0
        guide_passed_at = -math.inf
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
                # A new page has no microphone open yet, whatever the tab it replaced had.
                room.stop_voice(role)
                if role == "mobile_master":
                    room.marker = MarkerState()
                    room.selection = None
                # A new connection does not inherit the hold. The object stays at its last place.
                if room.manipulation is not None and room.manipulation.owner == role:
                    room.drop()
                if previous is not None:
                    # A headset replaced by a new tab takes its hand (#185) and spot (#248).
                    phone = room.outboxes.get("mobile_master")
                    if role == "vr_solver" and phone is not None:
                        phone.reply({"type": "designer_hand", "position": None, "length": None})
                        phone.reply({"type": "guide", "spot": None})
                    try:
                        await asyncio.wait_for(
                            previous.close(code=1000, reason="Device connected in another tab"),
                            timeout=2,
                        )
                    except (RuntimeError, OSError, TimeoutError):
                        pass
                room.revision += 1
                outbox.reply({"type": "welcome", "state": room.for_role(room.snapshot(), role)})
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
                    elif isinstance(incoming, DesignerHandMessage):
                        if role != "vr_solver":
                            await reject("role_forbidden", "Only the headset sends its hand.")
                            continue
                        if incoming.sequence <= hand_sequence:
                            await reject(
                                "stale_sequence", "Hand sequences must increase on this socket."
                            )
                            continue
                        hand_sequence = incoming.sequence
                        now = asyncio.get_running_loop().time()
                        # At most one place every HAND_SECONDS; the hand going always passes.
                        if incoming.position is not None and now - hand_passed_at < HAND_SECONDS:
                            continue
                        phone = room.outboxes.get("mobile_master")
                        if phone is not None:
                            position = incoming.position
                            phone.reply(
                                {
                                    "type": "designer_hand",
                                    "position": None if position is None else position.model_dump(),
                                    "length": None if position is None else incoming.length,
                                }
                            )
                            if position is not None:
                                hand_passed_at = now
                    elif isinstance(incoming, GuideMessage):
                        if role != "vr_solver":
                            await reject("role_forbidden", "Only the headset guides.")
                            continue
                        if incoming.sequence <= guide_sequence:
                            await reject(
                                "stale_sequence", "Guide sequences must increase on this socket."
                            )
                            continue
                        guide_sequence = incoming.sequence
                        now = asyncio.get_running_loop().time()
                        # As the hand: at most one spot every HAND_SECONDS; clearing always passes.
                        if incoming.spot is not None and now - guide_passed_at < HAND_SECONDS:
                            continue
                        phone = room.outboxes.get("mobile_master")
                        if phone is not None:
                            spot = incoming.spot
                            phone.reply(
                                {
                                    "type": "guide",
                                    "spot": None if spot is None else spot.model_dump(),
                                }
                            )
                            if spot is not None:
                                guide_passed_at = now
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
                    elif isinstance(incoming, VoiceReadyMessage):
                        if room.set_voice_ready(role, incoming.ready):
                            await room.broadcast()
                    elif isinstance(incoming, VoiceMuteMessage):
                        if room.set_voice_muted(role, incoming.muted) != "ok":
                            await reject(*VOICE_REFUSALS["not_ready"])
                            continue
                        await room.broadcast()
                    elif isinstance(incoming, VoiceSignalMessage):
                        refusal = room.voice_refusal(role)
                        if refusal is not None:
                            await reject(*VOICE_REFUSALS[refusal])
                            continue
                        # Passed to the other person alone, in order, and never kept: it is not
                        # shared state, so it does not ride on a state broadcast.
                        other: Role = "vr_solver" if role == "mobile_master" else "mobile_master"
                        room.outboxes[other].reply(
                            {
                                "type": "voice_signal",
                                "from": role,
                                "session": room.voice_sessions[role],
                                "kind": incoming.kind,
                                "sdp": incoming.sdp,
                                "candidate": None
                                if incoming.candidate is None
                                else incoming.candidate.model_dump(),
                            }
                        )
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
                            result = room.release(role, incoming.manipulation_id, incoming.velocity)
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
                    elif isinstance(incoming, AddFurnitureMessage):
                        if role != "vr_solver":
                            await reject("role_forbidden", "Only the headset places furniture.")
                            continue
                        result = room.add_furniture(
                            incoming.room_version,
                            catalogue.get(incoming.item),
                            incoming.position,
                            incoming.yaw,
                        )
                        if result == "unavailable":
                            await reject(
                                "room_unavailable",
                                room.load_error or "Prepared room is unavailable.",
                            )
                            continue
                        if result != "ok":
                            await reject(*FURNITURE_REFUSALS[result])
                            continue
                        await room.broadcast()
                    elif isinstance(incoming, ResizeFurnitureMessage):
                        result = room.resize_furniture(
                            role, incoming.room_version, incoming.id, incoming.scale, incoming.final
                        )
                        if result == "unavailable":
                            await reject(
                                "room_unavailable",
                                room.load_error or "Prepared room is unavailable.",
                            )
                            continue
                        if result != "ok":
                            await reject(*FURNITURE_REFUSALS[result])
                            continue
                        await room.broadcast()
                    elif isinstance(incoming, RemoveFurnitureMessage):
                        result = room.remove_furniture(role, incoming.room_version, incoming.id)
                        if result == "unavailable":
                            await reject(
                                "room_unavailable",
                                room.load_error or "Prepared room is unavailable.",
                            )
                            continue
                        if result != "ok":
                            await reject(*FURNITURE_REFUSALS[result])
                            continue
                        await room.broadcast()
                    elif isinstance(incoming, (PrepareDrillMessage, CancelDrillMessage)):
                        if role != "vr_solver":
                            await reject("role_forbidden", "Only the headset runs drills.")
                            continue
                        if room.load_error is not None or room.room_version is None:
                            await reject(
                                "room_unavailable",
                                room.load_error or "Prepared room is unavailable.",
                            )
                            continue
                        if incoming.room_version != room.room_version:
                            await reject(*ROOM_VERSION_MISMATCH)
                            continue
                        stopping = room.drop_drill()
                        if stopping is not None:
                            hazards.cancel(stopping)
                        if isinstance(incoming, PrepareDrillMessage):
                            if not any(e.id == incoming.entity for e in room.entities):
                                await reject("unknown_entity", "That room object does not exist.")
                                await room.broadcast()
                                continue
                            room.drill = Drill(
                                entity=incoming.entity,
                                hazard=incoming.hazard.strip(),
                                state="preparing",
                            )
                            found = hazards.cached(
                                live_rooms.directory.name, incoming.entity, incoming.hazard
                            )
                            if found is not None:
                                room.drill_ready(found)
                            elif not hazards.available:
                                room.drill.state = "failed"
                                room.drill.error = "This server can't make fires."
                            else:
                                made = hazards.start(
                                    HazardRequest(
                                        target=HazardTarget(entity=incoming.entity),
                                        hazard=incoming.hazard,
                                    )
                                )
                                room.drill.job = made.id
                            room.revision += 1
                        await room.broadcast()
                    elif isinstance(incoming, (AddHazardMessage, HazardControlMessage)):
                        if role != "vr_solver":
                            await reject("role_forbidden", "Only the headset runs hazards.")
                            continue
                        if isinstance(incoming, AddHazardMessage):
                            result = room.add_hazard(
                                incoming.room_version, hazards.asset(incoming.asset)
                            )
                        else:
                            result = room.control_hazard(
                                incoming.room_version, incoming.id, incoming.type
                            )
                        if result == "unavailable":
                            await reject(
                                "room_unavailable",
                                room.load_error or "Prepared room is unavailable.",
                            )
                            continue
                        if result != "ok":
                            await reject(*HAZARD_REFUSALS[result])
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
                    # The headset gone, so are its hand (#185) and spot (#248) in the phone's room.
                    phone = room.outboxes.get("mobile_master")
                    if role == "vr_solver" and phone is not None:
                        phone.reply({"type": "designer_hand", "position": None, "length": None})
                        phone.reply({"type": "guide", "spot": None})
                    await room.broadcast()
            await outbox.close()

    dist = repository / "frontend" / "dist"
    if dist.is_dir():
        app.mount("/", StaticFiles(directory=dist, html=True), name="frontend")
    return app


load_env_file()
app = create_app()
