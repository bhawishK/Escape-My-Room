"""Store room-photo captures: original files, their hashes, instructions and the chosen overview.

A capture is written to a hidden folder and renamed into place only after every photo is valid,
so a failed upload never leaves a partial capture. Originals are kept byte for byte. When a photo
carries an EXIF orientation, an upright PNG copy is written for processing and the transform is
recorded; otherwise the original is also the processed image.
"""

import hashlib
import io
import os
import re
import secrets
import shutil
import threading
from dataclasses import dataclass
from pathlib import Path, PurePath
from typing import Literal

from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import Field

from backend.errors import Refusal
from backend.protocol import WireModel
from backend.records import RecordFolder, StoredRecord, now, write_json

CAPTURE_ID = re.compile(r"^cap_[0-9a-f]{32}$")
IMAGE_ID = re.compile(r"^img_[0-9a-f]{32}$")
ORIENTATION_TAG = 0x0112

type MediaType = Literal["image/jpeg", "image/png"]
type ImageKind = Literal["original", "processed"]

# Pillow names a JPEG that carries extra embedded pictures (phone HDR gain maps, previews) "MPO".
MEDIA_TYPES: dict[str, MediaType] = {"JPEG": "image/jpeg", "MPO": "image/jpeg", "PNG": "image/png"}
SUFFIXES: dict[MediaType, str] = {"image/jpeg": ".jpg", "image/png": ".png"}
# Pixel modes PNG can store; anything else (such as CMYK) is converted to RGB for the upright copy.
PNG_MODES = {"1", "L", "LA", "P", "RGB", "RGBA", "I", "I;16"}


class CaptureError(Refusal):
    """A capture request cannot be accepted; the message is shown to the user."""


@dataclass(frozen=True)
class CaptureLimits:
    max_images: int = 40
    max_image_bytes: int = 25 * 1024 * 1024
    max_image_pixels: int = 50_000_000
    max_instructions: int = 4000

    @classmethod
    def from_environment(cls) -> "CaptureLimits":
        def setting(name: str, default: int) -> int:
            value = os.environ.get(f"ESCAPE_ROOM_CAPTURE_{name}")
            return int(value) if value else default

        defaults = cls()
        return cls(
            max_images=setting("MAX_IMAGES", defaults.max_images),
            max_image_bytes=setting("MAX_IMAGE_BYTES", defaults.max_image_bytes),
            max_image_pixels=setting("MAX_IMAGE_PIXELS", defaults.max_image_pixels),
            max_instructions=setting("MAX_INSTRUCTIONS", defaults.max_instructions),
        )


class ProcessedImage(WireModel):
    source: Literal["original", "exif_orientation_applied"]
    media_type: MediaType
    width: int
    height: int


class CaptureImage(WireModel):
    id: str = Field(pattern=IMAGE_ID.pattern)
    original_filename: str
    media_type: MediaType
    size_bytes: int
    sha256: str
    width: int
    height: int
    exif_orientation: int
    processed: ProcessedImage

    def file(self, kind: ImageKind) -> tuple[PurePath, MediaType]:
        """Where this photo's file of the given kind lives inside its capture folder."""
        if kind == "processed" and self.processed.source == "exif_orientation_applied":
            return PurePath("processed", f"{self.id}.png"), self.processed.media_type
        return PurePath("originals", f"{self.id}{SUFFIXES[self.media_type]}"), self.media_type


class Capture(StoredRecord):
    id: str = Field(pattern=CAPTURE_ID.pattern)
    instructions: str
    overview_image_id: str
    images: list[CaptureImage]


@dataclass(frozen=True)
class Upload:
    filename: str
    data: bytes


@dataclass(frozen=True)
class _CheckedPhoto:
    record: CaptureImage
    original: bytes
    upright_png: bytes | None


class CaptureStore:
    def __init__(self, root: Path, limits: CaptureLimits) -> None:
        self.root = root
        self.limits = limits
        self._records = RecordFolder(root, Capture, CAPTURE_ID, "capture")
        self._lock = threading.Lock()

    def create(self, uploads: list[Upload], instructions: str, overview: int) -> Capture:
        if not uploads:
            raise CaptureError("Add at least one room photo.")
        if len(uploads) > self.limits.max_images:
            raise CaptureError(
                f"Choose at most {self.limits.max_images} photos; {len(uploads)} were selected.",
                413,
            )
        if len(instructions) > self.limits.max_instructions:
            raise CaptureError(
                f"Keep room instructions under {self.limits.max_instructions} characters.", 413
            )
        if not 0 <= overview < len(uploads):
            raise CaptureError("Choose one of the selected photos as the overview.")
        photos = [self._check(upload) for upload in uploads]
        capture = Capture(
            id=f"cap_{secrets.token_hex(16)}",
            created_at=now(),
            instructions=instructions,
            overview_image_id=photos[overview].record.id,
            images=[photo.record for photo in photos],
        )
        self.root.mkdir(parents=True, exist_ok=True)
        incoming = self.root / f".incoming-{capture.id}"
        try:
            (incoming / "originals").mkdir(parents=True)
            (incoming / "processed").mkdir()
            for photo in photos:
                (incoming / photo.record.file("original")[0]).write_bytes(photo.original)
                if photo.upright_png is not None:
                    (incoming / photo.record.file("processed")[0]).write_bytes(photo.upright_png)
            write_json(incoming / "capture.json", capture)
            incoming.rename(self.root / capture.id)
        finally:
            shutil.rmtree(incoming, ignore_errors=True)
        return capture

    def set_overview(self, capture_id: str, image_id: str) -> Capture:
        with self._lock:
            capture = self.get(capture_id)
            if image_id not in {image.id for image in capture.images}:
                raise CaptureError("That photo is not part of this capture.")
            capture.overview_image_id = image_id
            self._records.save(capture)
            return capture

    def newest_first(self) -> list[Capture]:
        return self._records.newest_first()

    def get(self, capture_id: str) -> Capture:
        capture = self._records.read(capture_id)
        if capture is None:
            raise CaptureError("That capture does not exist.", 404)
        return capture

    def photo_file(self, capture_id: str, image_id: str, kind: ImageKind) -> tuple[Path, MediaType]:
        capture = self.get(capture_id)
        image = next((item for item in capture.images if item.id == image_id), None)
        if image is None:
            raise CaptureError("That photo does not exist.", 404)
        relative, media_type = image.file(kind)
        return self.root / capture.id / relative, media_type

    def _check(self, upload: Upload) -> _CheckedPhoto:
        """Decode one upload fully, enforce the limits, and make its upright copy if needed."""
        name = PurePath(upload.filename.replace("\\", "/")).name[:255] or "photo"
        if len(upload.data) > self.limits.max_image_bytes:
            raise CaptureError(
                f"{name} is larger than {self.limits.max_image_bytes // 1024} KiB.", 413
            )
        try:
            with Image.open(io.BytesIO(upload.data)) as image:
                media_type = MEDIA_TYPES.get(image.format or "")
                if media_type is None:
                    raise CaptureError(f"{name} is not a JPEG or PNG photo.")
                width, height = image.size
                if width * height > self.limits.max_image_pixels:
                    raise CaptureError(
                        f"{name} has {width * height:,} pixels; "
                        f"the limit is {self.limits.max_image_pixels:,}.",
                        413,
                    )
                image.load()
                tag = image.getexif().get(ORIENTATION_TAG, 1)
                orientation = tag if isinstance(tag, int) and 1 <= tag <= 8 else 1
                upright = ImageOps.exif_transpose(image) if orientation != 1 else None
        except Image.DecompressionBombError as exc:
            # Pillow refuses extreme sizes before the configured pixel check can run.
            raise CaptureError(f"{name} has more pixels than can be decoded safely.", 413) from exc
        except (UnidentifiedImageError, OSError, SyntaxError, ValueError) as exc:
            raise CaptureError(f"{name} could not be read as a JPEG or PNG photo.") from exc
        if upright is None:
            processed = ProcessedImage(
                source="original", media_type=media_type, width=width, height=height
            )
            upright_png = None
        else:
            processed = ProcessedImage(
                source="exif_orientation_applied",
                media_type="image/png",
                width=upright.width,
                height=upright.height,
            )
            upright_png = _png(upright, name)
        record = CaptureImage(
            id=f"img_{secrets.token_hex(16)}",
            original_filename=name,
            media_type=media_type,
            size_bytes=len(upload.data),
            sha256=hashlib.sha256(upload.data).hexdigest(),
            width=width,
            height=height,
            exif_orientation=orientation,
            processed=processed,
        )
        return _CheckedPhoto(record=record, original=upload.data, upright_png=upright_png)


def _png(image: Image.Image, name: str) -> bytes:
    if image.mode not in PNG_MODES:
        image = image.convert("RGB")
    buffer = io.BytesIO()
    try:
        image.save(buffer, format="PNG")
    except (OSError, ValueError) as exc:
        raise CaptureError(
            f"{name} could not be turned upright for processing ({image.mode} colour). "
            "Save it as an ordinary JPEG or PNG and try again."
        ) from exc
    return buffer.getvalue()
