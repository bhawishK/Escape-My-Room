"""Furniture made from a description (#186): a picture first, then a 3D piece at its true size.

The generation follows RiasadHuq10/VR-Image-3D-Object-Generator, used with its author's
permission: Z-Image-Turbo draws the description, and Hunyuan3D-2.1 turns the picture into a
textured GLB, both called as Hugging Face Spaces with the same settings. Its routing agent is left
out: the page already says whether it sends words or a picture.

A finished model is checked, resized uniformly to its true size, and centred so its bottom face's
centre is its origin, as every room entity's is. It is then kept with the server's data and added
to the catalogue, so it survives a restart and is placed like a built-in piece.
"""

import io
import logging
import math
import os
import re
import tempfile
import threading
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal, Protocol, cast

from PIL import Image
from pydantic import BaseModel, Field

from backend.furniture import Catalogue, CatalogueItem
from backend.gltf import AssetError, GltfDocument, split_glb, transform_point, write_glb
from backend.prepared_room import EntitySize

JobState = Literal["queued", "image_ready", "ready", "failed", "cancelled"]

# The node every generated model is wrapped in: its scale and place make the piece true to size.
PIECE_NODE = "piece"
# How long one generator step may take before the job fails, unless the settings say otherwise.
DEFAULT_TIMEOUT_SECONDS = 600.0
# A generated model larger than this is refused: phones would have to download it.
MAX_MODEL_BYTES = 50 * 1024 * 1024
# The Space making hazards' videos: Wan 2.2 image-to-video (#224). A setting can name another.
WAN_SPACE = (
    os.environ.get("ESCAPE_ROOM_HAZARD_VIDEO_SPACE") or "zerogpu-aoti/wan2-2-fp8da-aoti-faster"
)
# A Space call whose upload times out is tried this many times in all.
VIDEO_TRIES = 3
LOG = logging.getLogger(__name__)
# A size asked for or guessed is kept between these, in metres.
SMALLEST_METRES = 0.05
LARGEST_METRES = 10.0

FAILURES = {
    "image": "The generator couldn't make a picture of that. Try again, or put it another way.",
    "model": "The generator couldn't turn the picture into a 3D piece. Try again.",
    "unreadable": "The 3D piece the generator made couldn't be read. Try again.",
    "too_large": "The 3D piece the generator made is too large to use. Try a simpler piece.",
    "shape": "The 3D piece came out a strange shape, too flat or thin to size. Try again.",
    "timeout": "The generator took too long. It may be busy: try again in a few minutes.",
    "quota": (
        "The generator is out of GPU time for today. Set HF_TOKEN on the server for more, "
        "or try again later."
    ),
    # Hazards (#222): a video of the hazard, then its 3D animation.
    "video": "The generator couldn't make a video of that. Try again.",
    "animate": "The video couldn't be turned into a 3D animation. Try again.",
    "video_unset": "Making hazard videos isn't set up on this server yet.",
    "animate_unset": "Turning videos into 3D animations isn't set up on this server yet.",
    "room_picture": "The object couldn't be pictured from the room's splat. Try again.",
}


class GenerationError(Exception):
    """A generator step failed; `reason` is a key of FAILURES. `message`, when given, says it
    more exactly, such as why an object in the room can't be pictured (#223)."""

    def __init__(self, reason: str, message: str | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.message = message or FAILURES[reason]


class Generator(Protocol):
    def image(self, description: str) -> bytes:
        """A PNG picture of the description."""
        ...

    def model(self, picture: bytes) -> bytes:
        """A textured GLB of what the PNG picture shows."""
        ...

    def video(self, picture: bytes, prompt: str, seed: int = 7) -> bytes:
        """An MP4 of the PNG picture coming to life as `prompt` says: a hazard (#222, #224).
        The same seed gives the same video."""
        ...

    def animate(self, video: bytes) -> list[bytes]:
        """The MP4's object as 3D Gaussian splats, one PLY per frame (#222, #226)."""
        ...


class HuggingFaceGenerator:
    """The Hugging Face Spaces VR-Image-3D-Object-Generator uses, with its settings, and Wan 2.2
    for hazards' videos (#224). `client` makes a gradio_client Client for a Space; tests fake it."""

    def __init__(
        self,
        token: str | None,
        client: Callable[[str], Any] | None = None,
        video_space: str = WAN_SPACE,
    ) -> None:
        self.token = token
        self.client = client or self._client
        self.video_space = video_space
        # Seconds before trying a timed-out upload again, times the attempt.
        self.retry_seconds = 5.0

    def _client(self, space: str) -> Any:
        from gradio_client import Client  # pyright: ignore

        return Client(space, token=self.token, verbose=False)  # pyright: ignore

    def image(self, description: str) -> bytes:
        from gradio_client import Client  # pyright: ignore

        result, _seed = Client("mrfakename/Z-Image-Turbo", token=self.token).predict(  # pyright: ignore
            prompt=description,
            height=768,
            width=768,
            num_inference_steps=8,
            seed=5,
            randomize_seed=True,
            api_name="/generate_image",
        )
        with Image.open(result) as picture:  # pyright: ignore[reportUnknownArgumentType]
            out = io.BytesIO()
            picture.convert("RGB").save(out, format="PNG")
        return out.getvalue()

    def model(self, picture: bytes) -> bytes:
        from gradio_client import Client, handle_file  # pyright: ignore

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "picture.png"
            path.write_bytes(picture)
            result = Client("tencent/Hunyuan3D-2.1", token=self.token).predict(  # pyright: ignore
                api_name="/generation_all",
                image=handle_file(str(path)),  # pyright: ignore[reportUnknownArgumentType]
                mv_image_front=None,
                mv_image_back=None,
                mv_image_left=None,
                mv_image_right=None,
                steps=30,
                guidance_scale=5,
                seed=1234,
                octree_resolution=256,
                check_box_rembg=True,
                num_chunks=8000,
                randomize_seed=True,
            )
            # The textured mesh, as the original reads it.
            return Path(result[1]["value"]).read_bytes()  # pyright: ignore

    def video(self, picture: bytes, prompt: str, seed: int = 7) -> bytes:
        """Wan 2.2 image-to-video, 3 s at 16 fps, with spike #220's settings. The Space's own
        negative prompt is kept: it is what made the spike's videos."""
        from gradio_client import handle_file  # pyright: ignore

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "picture.png"
            path.write_bytes(picture)
            video: Any = None
            for attempt in range(1, VIDEO_TRIES + 1):
                try:
                    video, _seed = self.client(self.video_space).predict(
                        input_image=handle_file(str(path)),  # pyright: ignore[reportUnknownArgumentType]
                        prompt=prompt,
                        steps=6,
                        duration_seconds=3.0,
                        guidance_scale=1,
                        guidance_scale_2=1,
                        seed=seed,
                        randomize_seed=False,
                        api_name="/generate_video",
                    )
                    break
                except Exception as exc:  # noqa: BLE001 - a Space fails in many ways; each is reported
                    LOG.warning(
                        "Wan video attempt %d failed: %s: %s", attempt, type(exc).__name__, exc
                    )
                    # The upload of the picture times out now and then on a slow line: try again.
                    if (
                        attempt < VIDEO_TRIES
                        and "timeout" in f"{type(exc).__name__} {exc}".lower().replace(" ", "")
                    ):
                        time.sleep(self.retry_seconds * attempt)
                        continue
                    raise video_failure(exc) from exc
            if video is None:
                raise GenerationError("video")
            made: Any = cast(dict[str, Any], video)["video"] if isinstance(video, dict) else video
            return Path(cast(str, made)).read_bytes()

    def animate(self, video: bytes) -> list[bytes]:
        # The L4GM step comes with #226.
        raise GenerationError("animate_unset")


class FixtureGenerator:
    """A generator for tests and offline development: a small picture, then a box 4 m wide, 2 m
    tall and 1 m deep whose lowest corner is at (1, 1, 1). `fail` makes one step go wrong."""

    def __init__(self, seconds: float = 0.1, fail: str | None = None) -> None:
        self.seconds = seconds
        self.fail = fail

    def image(self, description: str) -> bytes:
        time.sleep(self.seconds)
        if self.fail == "image":
            raise RuntimeError("The fixture generator failed to draw on purpose.")
        if self.fail == "quota":
            # As a Hugging Face Space answers once the account's ZeroGPU time is used up.
            raise RuntimeError("You have exceeded your ZeroGPU quota (90s requested vs. 68s left).")
        out = io.BytesIO()
        Image.new("RGB", (64, 64), (91, 127, 110)).save(out, format="PNG")
        return out.getvalue()

    def model(self, picture: bytes) -> bytes:
        time.sleep(self.seconds)
        if self.fail == "model":
            raise RuntimeError("The fixture generator failed to model on purpose.")
        if self.fail == "slow":
            time.sleep(60)
        if self.fail == "unreadable":
            return b"not a model"
        if self.fail == "too_large":
            return fixture_box() + b"\x00" * MAX_MODEL_BYTES
        if self.fail == "flat":
            # 1 m across and a tenth of a millimetre tall.
            return fixture_box((2.0, 1.0001, 2.0))
        return fixture_box()

    def video(self, picture: bytes, prompt: str, seed: int = 7) -> bytes:
        time.sleep(self.seconds)
        if self.fail == "video":
            raise RuntimeError("The fixture generator failed to film on purpose.")
        # An MP4's opening `ftyp` box, then a note of what it shows.
        return MP4_START + f"{prompt} | seed {seed}".encode()

    def animate(self, video: bytes) -> list[bytes]:
        time.sleep(self.seconds)
        if self.fail == "animate":
            raise RuntimeError("The fixture generator failed to animate on purpose.")
        return [fixture_splat(frame) for frame in range(FIXTURE_FRAMES)]


FIXTURE_FRAMES = 4
# The 20-byte start of an MP4 file: its `ftyp` box.
MP4_START = b"\x00\x00\x00\x14ftypisom\x00\x00\x02\x00isom"


def fixture_splat(frame: int) -> bytes:
    """A 3D Gaussian splat PLY of three splats, rising a little each frame."""
    import struct

    names = ["x", "y", "z", "f_dc_0", "f_dc_1", "f_dc_2", "opacity"]
    names += [f"scale_{i}" for i in range(3)] + [f"rot_{i}" for i in range(4)]
    header = "ply\nformat binary_little_endian 1.0\nelement vertex 3\n"
    header += "".join(f"property float {name}\n" for name in names) + "end_header\n"
    rows = b""
    for index in range(3):
        values = [index * 0.1, 0.1 * frame, 0.0, 1.5, 0.5, -1.0, 2.0, -3.0, -3.0, -3.0, 1, 0, 0, 0]
        rows += struct.pack("<14f", *values)
    return header.encode() + rows


def fixture_box(high: tuple[float, float, float] = (5.0, 3.0, 2.0)) -> bytes:
    """A GLB box from (1, 1, 1) to `high`: 4 × 2 × 1 m unless asked otherwise."""
    import struct

    low = (1.0, 1.0, 1.0)
    corners = [
        (x, y, z) for x in (low[0], high[0]) for y in (low[1], high[1]) for z in (low[2], high[2])
    ]
    # Two triangles for each of the six faces, by corner index.
    faces = [int(index) for index in "013032467475045051237276026064157173"]
    binary = struct.pack(
        f"<{len(corners) * 3}f", *[value for corner in corners for value in corner]
    )
    binary += struct.pack(f"<{len(faces)}H", *faces)
    document = {
        "asset": {"version": "2.0"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"name": "geometry_0", "mesh": 0}],
        "meshes": [
            {"name": "mesh_0", "primitives": [{"attributes": {"POSITION": 0}, "indices": 1}]}
        ],
        "accessors": [
            {
                "bufferView": 0,
                "componentType": 5126,
                "count": 8,
                "type": "VEC3",
                "min": list(low),
                "max": list(high),
            },
            {"bufferView": 1, "componentType": 5123, "count": len(faces), "type": "SCALAR"},
        ],
        "bufferViews": [
            {"buffer": 0, "byteOffset": 0, "byteLength": 96},
            {"buffer": 0, "byteOffset": 96, "byteLength": len(faces) * 2},
        ],
        "buffers": [{"byteLength": len(binary)}],
    }
    return write_glb(document, binary)


def generator_from_environment() -> Generator | None:
    """The generator the server's settings choose, or None when generation isn't set up."""
    chosen = os.environ.get("ESCAPE_ROOM_FURNITURE_GENERATOR")
    if chosen == "huggingface":
        try:
            import gradio_client  # pyright: ignore # noqa: F401
        except ImportError:
            # Not installed: install the `generation` extra. Until then, generation is off.
            return None
        return HuggingFaceGenerator(os.environ.get("HF_TOKEN") or None)
    if chosen == "fixture":
        seconds = float(os.environ.get("ESCAPE_ROOM_FIXTURE_GENERATOR_SECONDS") or 0.1)
        return FixtureGenerator(
            seconds, os.environ.get("ESCAPE_ROOM_FIXTURE_GENERATOR_FAIL") or None
        )
    return None


# Kinds of furniture and their usual size: how long (the longer side across the floor) or how
# tall, in metres. The kind named earliest in the description counts.
KINDS: list[tuple[tuple[str, ...], Literal["length", "height"], float]] = [
    (("sofa", "couch", "settee"), "length", 2.0),
    (("armchair",), "height", 0.9),
    (("bed",), "length", 2.0),
    (("bookshelf", "bookcase", "shelves", "shelf"), "height", 1.8),
    (("wardrobe", "cupboard"), "height", 1.9),
    (("cabinet", "dresser", "drawers", "sideboard"), "height", 1.0),
    (("table", "desk"), "height", 0.75),
    (("chair", "stool"), "height", 0.9),
    (("lamp",), "height", 1.6),
    (("rug", "carpet", "mat"), "length", 2.0),
    (("plant",), "height", 1.0),
    (("tv", "television"), "length", 1.2),
]
DIMENSION = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*(cm|centimet(?:er|re)s?|m|met(?:er|re)s?)\b"
    r"(?:\s+(long|wide|across|tall|high|deep))?",
    re.IGNORECASE,
)


Measure = Literal["length", "width", "depth", "height", "largest"]
# The side each word in "2 m long", "60 cm wide" and so on sets.
SIDES: dict[str, Measure] = {
    "long": "length",
    "wide": "width",
    "across": "width",
    "deep": "depth",
    "tall": "height",
    "high": "height",
}


def target_size(description: str) -> tuple[Measure, float]:
    """What the piece's size is set by: a size in the description, such as "2 m long" or
    "90 cm tall", else the usual size of the kind it names first, else 1 m at its largest."""
    found = DIMENSION.search(description)
    if found:
        value = float(found.group(1).replace(",", "."))
        metres = value / 100 if found.group(2).lower().startswith("c") else value
        measure = SIDES.get((found.group(3) or "").lower(), "length")
        return measure, max(SMALLEST_METRES, min(LARGEST_METRES, metres))
    for word in re.findall(r"[a-z]+", description.lower()):
        for names, kind_measure, metres in KINDS:
            if word in names:
                return kind_measure, metres
    return "largest", 1.0


def scene_roots(asset: GltfDocument) -> list[int]:
    """The nodes the model's scene shows; every parentless node if it names no scene."""
    scenes = asset.document.get("scenes")
    scene = asset.document.get("scene", 0)
    if isinstance(scenes, list) and isinstance(scene, int):
        listed = cast(list[object], scenes)
        chosen = listed[scene] if 0 <= scene < len(listed) else None
        nodes = cast(dict[str, object], chosen).get("nodes") if isinstance(chosen, dict) else None
        if isinstance(nodes, list):
            roots = [index for index in cast(list[object], nodes) if isinstance(index, int)]
            if roots:
                return roots
    return [index for index in range(len(asset.nodes)) if index not in asset.parents]


def true_to_size(model: bytes, description: str) -> tuple[bytes, EntitySize]:
    """The model wrapped in a `piece` node that scales it uniformly to its true size and puts
    its bottom face's centre at the origin, and that size. Raises GenerationError if it can't
    be used."""
    if len(model) > MAX_MODEL_BYTES:
        raise GenerationError("too_large")
    try:
        document, binary = split_glb("generated model", model)
        asset = GltfDocument("generated model", document)
        roots = scene_roots(asset)
        corners: list[tuple[float, float, float]] = []
        for root in roots:
            bounds = asset.local_bounds(root)
            if bounds is None:
                continue
            matrix = asset.local_matrix(root)
            corners.extend(
                transform_point(matrix, (x, y, z))
                for x in (bounds[0][0], bounds[1][0])
                for y in (bounds[0][1], bounds[1][1])
                for z in (bounds[0][2], bounds[1][2])
            )
    except (AssetError, ValueError, TypeError, KeyError, IndexError) as exc:
        raise GenerationError("unreadable") from exc
    if not corners:
        raise GenerationError("unreadable")
    low = [min(corner[axis] for corner in corners) for axis in range(3)]
    high = [max(corner[axis] for corner in corners) for axis in range(3)]
    width, height, depth = (high[axis] - low[axis] for axis in range(3))
    measure, metres = target_size(description)
    current = {
        "length": max(width, depth),
        "width": width,
        "depth": depth,
        "height": height,
    }.get(measure, max(width, height, depth))
    if not math.isfinite(current) or current <= 1e-6:
        raise GenerationError("unreadable")
    scale = metres / current
    # Too flat or thin to size: one side would come out huge.
    if max(width, height, depth) * scale > LARGEST_METRES:
        raise GenerationError("shape")
    centre_x, centre_z = (low[0] + high[0]) / 2, (low[2] + high[2]) / 2
    nodes: list[Any] = asset.document["nodes"]  # pyright: ignore
    nodes.append(
        {
            "name": PIECE_NODE,
            "scale": [scale, scale, scale],
            "translation": [-centre_x * scale, -low[1] * scale, -centre_z * scale],
            "children": roots,
        }
    )
    asset.document["scenes"] = [{"nodes": [len(nodes) - 1]}]
    asset.document["scene"] = 0
    size = EntitySize(
        width=round(width * scale, 4),
        height=round(height * scale, 4),
        depth=round(depth * scale, 4),
    )
    return write_glb(asset.document, binary), size


class FurnitureJob(BaseModel):
    id: str
    description: str
    state: JobState = "queued"
    error: str | None = None
    image_url: str | None = None
    # The catalogue piece, once ready.
    item: CatalogueItem | None = None
    # Made from the resident's photo (#187): the photo is the picture, so it starts from 3D.
    photo: bool = False


class GenerationRequest(BaseModel):
    description: str = Field(min_length=3, max_length=200)


# A photo is made no larger than this on its longer side before the 3D step: the pictures
# Z-Image draws for descriptions are 768 px, and image-to-3D needs no more.
PHOTO_SIDE = 1024


def fitted(picture: bytes) -> bytes:
    """A PNG picture no larger than PHOTO_SIDE on its longer side."""
    with Image.open(io.BytesIO(picture)) as image:
        if max(image.size) <= PHOTO_SIDE:
            return picture
        image.thumbnail((PHOTO_SIDE, PHOTO_SIDE))
        out = io.BytesIO()
        image.save(out, format="PNG")
        return out.getvalue()


def piece_name(description: str) -> str:
    """A short name for the catalogue: the description, capitalised and cut short."""
    text = " ".join(description.split())
    text = text[:1].upper() + text[1:]
    return text if len(text) <= 40 else text[:39].rstrip() + "…"


class FurnitureGeneration:
    """Generation jobs, one at a time in the order asked, and the pieces they made."""

    def __init__(
        self,
        root: Path,
        catalogue: Catalogue,
        generator: Generator | None,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        on_added: Callable[[CatalogueItem], None] = lambda item: None,
    ) -> None:
        # Called from the job thread when a piece joins the catalogue (#187).
        self.on_added = on_added
        self.root = root
        self.catalogue = catalogue
        self.generator = generator
        self.timeout = timeout
        self.jobs: dict[str, FurnitureJob] = {}
        self.lock = threading.Lock()
        self.pending: list[str] = []
        self.wake = threading.Condition(self.lock)
        self.load()
        threading.Thread(target=self._run, daemon=True, name="furniture-jobs").start()

    @property
    def available(self) -> bool:
        return self.generator is not None

    def load(self) -> None:
        """Put the pieces made before back in the catalogue."""
        pieces = self.root / "pieces"
        for record in sorted(pieces.glob("*/item.json")) if pieces.is_dir() else []:
            try:
                item = CatalogueItem.model_validate_json(record.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if (record.parent / "model.glb").is_file():
                self.catalogue.add(item)

    def start(self, description: str) -> FurnitureJob:
        job = FurnitureJob(id=uuid.uuid4().hex[:12], description=description.strip())
        with self.lock:
            self.jobs[job.id] = job
            self.pending.append(job.id)
            self.wake.notify()
        return job.model_copy()

    def start_photo(self, picture: bytes, description: str) -> FurnitureJob:
        """Make a piece from a photo (#187), already checked and upright as a PNG. The photo is
        the job's picture from the start; `description`, which may be empty, names and sizes it."""
        job = FurnitureJob(
            id=uuid.uuid4().hex[:12],
            description=description.strip(),
            state="image_ready",
            photo=True,
        )
        folder = self.root / "jobs" / job.id
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "picture.png").write_bytes(fitted(picture))
        job.image_url = f"/api/furniture/jobs/{job.id}/image"
        with self.lock:
            self.jobs[job.id] = job
            self.pending.append(job.id)
            self.wake.notify()
        return job.model_copy()

    def get(self, job_id: str) -> FurnitureJob | None:
        with self.lock:
            job = self.jobs.get(job_id)
            return None if job is None else job.model_copy()

    def cancel(self, job_id: str) -> FurnitureJob | None:
        """Stop a job that hasn't finished: it ends cancelled, and nothing joins the catalogue."""
        with self.lock:
            job = self.jobs.get(job_id)
            if job is None:
                return None
            if job.state in ("queued", "image_ready"):
                job.state = "cancelled"
                if job_id in self.pending:
                    self.pending.remove(job_id)
            return job.model_copy()

    def image(self, job_id: str) -> Path | None:
        path = self.root / "jobs" / job_id / "picture.png"
        return path if path.is_file() else None

    def model(self, item_id: str) -> Path | None:
        if not re.fullmatch(r"gen_[0-9a-f]{8}", item_id):
            return None
        path = self.root / "pieces" / item_id / "model.glb"
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
                self._fail(job_id, "The piece couldn't be made. Try again.")

    def _step(self, action: Callable[[], bytes], reason: str) -> bytes:
        return run_step(action, reason, self.timeout)

    def _still(self, job_id: str, state: JobState) -> bool:
        with self.lock:
            return self.jobs[job_id].state == state

    def _make(self, job_id: str) -> None:
        generator = self.generator
        job = self.get(job_id)
        if generator is None or job is None:
            return
        if job.state != ("image_ready" if job.photo else "queued"):
            return
        folder = self.root / "jobs" / job_id
        try:
            if job.photo:
                picture = (folder / "picture.png").read_bytes()
            else:
                picture = self._step(lambda: generator.image(job.description), "image")
                folder.mkdir(parents=True, exist_ok=True)
                (folder / "picture.png").write_bytes(picture)
                with self.lock:
                    current = self.jobs[job_id]
                    if current.state != "queued":
                        return
                    current.state = "image_ready"
                    current.image_url = f"/api/furniture/jobs/{job_id}/image"
            model = self._step(lambda: generator.model(picture), "model")
            if not self._still(job_id, "image_ready"):
                return
            sized, size = true_to_size(model, job.description)
            item_id = f"gen_{uuid.uuid4().hex[:8]}"
            piece = self.root / "pieces" / item_id
            piece.mkdir(parents=True, exist_ok=True)
            (piece / "model.glb").write_bytes(sized)
            item = CatalogueItem(
                id=item_id,
                name=piece_name(job.description) if job.description else "Piece from a photo",
                node=PIECE_NODE,
                size=size,
                model_url=f"/api/furniture/generated/{item_id}/model.glb",
                generated=True,
            )
            (piece / "item.json").write_text(item.model_dump_json(indent=2), encoding="utf-8")
            with self.lock:
                current = self.jobs[job_id]
                if current.state != "image_ready":
                    return
                self.catalogue.add(item)
                current.state = "ready"
                current.item = item
            self.on_added(item)
        except GenerationError as exc:
            with self.lock:
                current = self.jobs[job_id]
                if current.state in ("queued", "image_ready"):
                    current.state = "failed"
                    current.error = FAILURES[exc.reason]
        except OSError:
            self._fail(job_id, "The new piece couldn't be saved on the server.")

    def _fail(self, job_id: str, message: str) -> None:
        """End a job that is still going as failed; a cancelled or finished one stays so."""
        with self.lock:
            current = self.jobs[job_id]
            if current.state in ("queued", "image_ready"):
                current.state = "failed"
                current.error = message


def video_failure(exc: BaseException) -> GenerationError:
    """A Space's failure as the user is told it: how long to wait when the day's GPU time is used
    up ("Try again in 18:19:24"), else that the video failed."""
    text = str(exc)
    if "quota" not in text.lower():
        return GenerationError("video")
    wait = re.search(r"try again in (\d+):(\d+):(\d+)", text, re.IGNORECASE)
    if wait is None:
        return GenerationError("quota", "The video generator is out of GPU time for today.")
    hours, minutes = int(wait.group(1)), int(wait.group(2))
    return GenerationError(
        "quota",
        f"The video generator is out of GPU time for today: try again in {hours} h {minutes} min.",
    )


def run_step[T](action: Callable[[], T], reason: str, timeout: float) -> T:
    """Run one generator step on a thread of its own, giving up on it after `timeout` seconds. A
    step given up on finishes on its own, and never holds up the next one. A failure becomes a
    GenerationError: `reason`, or `quota` when a Space's GPU time is used up."""
    result: list[T] = []
    failure: list[BaseException] = []

    def run() -> None:
        try:
            result.append(action())
        except BaseException as exc:  # noqa: BLE001 - reported to the job below
            failure.append(exc)

    thread = threading.Thread(target=run, daemon=True, name="generation-step")
    thread.start()
    thread.join(timeout)
    if thread.is_alive():
        raise GenerationError("timeout")
    if failure:
        exc = failure[0]
        if isinstance(exc, GenerationError):
            raise exc
        # Spaces on shared GPUs refuse once the day's GPU time is used up.
        raise GenerationError("quota" if "quota" in str(exc).lower() else reason) from exc
    return result[0]


def timeout_from_environment() -> float:
    return float(os.environ.get("ESCAPE_ROOM_FURNITURE_TIMEOUT_SECONDS") or DEFAULT_TIMEOUT_SECONDS)
