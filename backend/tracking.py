"""Camera calibrations the phone measures before marker tracking, one per video resolution.

The phone's browser does not report its camera's focal length or principal point, so the phone
measures them from views of a printed ChArUco board and saves them here. Pixel values are in the
coordinates of the video frames the browser delivers at `width` x `height`. A rotated phone
delivers a different resolution and needs its own calibration.
"""

import threading
from pathlib import Path

from pydantic import Field, ValidationError

from backend.errors import Refusal
from backend.protocol import WireModel
from backend.records import now, write_json

# A board calibration with a larger reprojection error points at blur or a bent board.
MAX_RMS_PX = 2.0


class CalibrationInput(WireModel):
    width: int = Field(ge=64, le=8192)
    height: int = Field(ge=64, le=8192)
    fx: float = Field(gt=0, le=100_000)
    fy: float = Field(gt=0, le=100_000)
    cx: float
    cy: float
    # OpenCV order: k1, k2, p1, p2, k3.
    distortion: list[float] = Field(min_length=5, max_length=5)
    rms_px: float = Field(ge=0)
    views: int = Field(ge=5, le=200)
    user_agent: str = Field(max_length=512)


class CameraCalibration(CalibrationInput):
    recorded_at: str


class CalibrationFile(WireModel):
    calibrations: list[CameraCalibration]


class CalibrationStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()

    def all(self) -> list[CameraCalibration]:
        try:
            text = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return []
        return CalibrationFile.model_validate_json(text).calibrations

    def save(self, body: bytes) -> CameraCalibration:
        try:
            calibration = CalibrationInput.model_validate_json(body)
        except ValidationError as exc:
            raise Refusal("Send a camera calibration using the documented fields.") from exc
        width, height = calibration.width, calibration.height
        if not (0 <= calibration.cx <= width and 0 <= calibration.cy <= height):
            raise Refusal("The principal point must lie inside the image. Calibrate again.")
        if calibration.rms_px > MAX_RMS_PX:
            raise Refusal(
                f"Calibration error is {calibration.rms_px:.2f} px; it must be at most "
                f"{MAX_RMS_PX:.1f} px. Hold the board flat and still, and calibrate again."
            )
        record = CameraCalibration(**calibration.model_dump(), recorded_at=now())
        with self._lock:
            kept = [
                item
                for item in self.all()
                if (item.width, item.height) != (record.width, record.height)
            ]
            self.path.parent.mkdir(parents=True, exist_ok=True)
            write_json(self.path, CalibrationFile(calibrations=[*kept, record]))
        return record
