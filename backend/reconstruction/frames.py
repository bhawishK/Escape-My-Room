"""Frames out of the room video: the sharpest of every three, evenly thinned. Needs ffmpeg."""

# cv2 is only installed on the GPU desktop.
# pyright: basic
# pyright: reportMissingImports=false

import shutil
import subprocess
from pathlib import Path

import numpy as np


def extract_frames(video: Path, out: Path, fps: float, long_side: int, max_frames: int) -> int:
    """Pull frames at three times `fps` and keep the sharpest of each three, to skip blur."""
    import cv2

    raw = out.parent / "raw_frames"
    for folder in (raw, out):
        shutil.rmtree(folder, ignore_errors=True)
        folder.mkdir(parents=True)
    size = f"scale='if(gt(iw,ih),min({long_side},iw),-2)':'if(gt(iw,ih),-2,min({long_side},ih))'"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            str(video),
            "-vf",
            f"fps={fps * 3},{size}",
            "-q:v",
            "2",
            str(raw / "%05d.jpg"),
        ],
        check=True,
    )
    frames = sorted(raw.glob("*.jpg"))

    def sharpness(path: Path) -> float:
        grey = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
        if grey is None:
            return 0.0
        return float(cv2.Laplacian(grey, cv2.CV_64F).var())

    picked = [max(frames[i : i + 3], key=sharpness) for i in range(0, len(frames), 3)]
    if len(picked) > max_frames:
        keep = np.linspace(0, len(picked) - 1, max_frames).round().astype(int)
        picked = [picked[i] for i in keep]
    for number, path in enumerate(picked):
        shutil.copy(path, out / f"frame_{number:04d}.jpg")
    shutil.rmtree(raw)
    return len(picked)
