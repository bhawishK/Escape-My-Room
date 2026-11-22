"""The 4D step (#226, part of #221): L4GM turns a hazard's video into 3D Gaussian splat frames.

L4GM (NVIDIA, NeurIPS 2024; code and weights Apache 2.0) lives in its own env on the GPU desktop,
installed by `scripts/l4gm/install.sh` (ESCAPE_ROOM_L4GM_DIR, default `~/l4gm`). It runs as two
processes, as spike #220 did: `infer_3d.py` makes ImageDream's four views of the first frame, then
`infer_4d_ply.py` (L4GM's `infer_4d.py`, saving each frame's splat) makes the 4D frames, 8 frames
a pass so it fits 8 GB. The video comes from the quality gate (#225): the object alone on white,
square, at 16 fps.

It takes the GPU in turn with room reconstruction (`backend.gpu`).
"""

import logging
import os
import subprocess
import tempfile
from pathlib import Path

from backend.furniture_generation import GenerationError
from backend.gpu import GPU

LOG = logging.getLogger(__name__)
# Each of the two processes may take this long. The spike's took about 10 s and 35 s.
STEP_TIMEOUT_SECONDS = 600
# Frames per pass: 16 ran out of memory on the desktop's 8 GB.
FRAMES_PER_PASS = 8
NAME = "hazard_fg"


def l4gm_dir() -> Path:
    return Path(os.environ.get("ESCAPE_ROOM_L4GM_DIR") or Path.home() / "l4gm")


def l4gm_python(folder: Path) -> str:
    return os.environ.get("ESCAPE_ROOM_L4GM_PYTHON") or str(folder / ".venv" / "bin" / "python")


def _environment(folder: Path) -> dict[str, str]:
    """L4GM's environment: no Hugging Face login (a stale saved one breaks its downloads), CUDA's
    tools on the path, and memory that can grow in segments."""
    cuda = os.environ.get("CUDA_HOME", "/usr/local/cuda-12.8")
    environment = {
        key: value
        for key, value in os.environ.items()
        if key not in ("HF_TOKEN", "HUGGING_FACE_HUB_TOKEN")
    }
    environment |= {
        "HF_HUB_DISABLE_IMPLICIT_TOKEN": "1",
        "CUDA_HOME": cuda,
        "PATH": os.pathsep.join(
            [str(folder / ".venv" / "bin"), f"{cuda}/bin", environment.get("PATH", "")]
        ),
        "PYTORCH_CUDA_ALLOC_CONF": "expandable_segments:True",
    }
    return environment


def _run(command: list[str], folder: Path) -> None:
    try:
        subprocess.run(
            command,
            cwd=folder,
            env=_environment(folder),
            check=True,
            capture_output=True,
            text=True,
            timeout=STEP_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise GenerationError(
            "animate", "Making the 3D animation took too long. Try again."
        ) from exc
    except subprocess.CalledProcessError as exc:
        said = f"{exc.stderr or ''}\n{exc.stdout or ''}"
        lines = [line for line in said.strip().splitlines() if line.strip()]
        LOG.warning("L4GM step %s failed: %s", command[1], lines[-1] if lines else exc.returncode)
        if "OutOfMemoryError" in said or "out of memory" in said:
            raise GenerationError(
                "animate",
                "Making the 3D animation ran out of GPU memory. Try again when no room is being "
                "built.",
            ) from exc
        raise GenerationError("animate") from exc


def animate_video(
    video: bytes, folder: Path | None = None, python: str | None = None
) -> list[bytes]:
    """The video's object as one splat PLY per frame, in order."""
    folder = folder or l4gm_dir()
    recon, interp = (
        folder / "pretrained" / "recon.safetensors",
        folder / "pretrained" / "interp.safetensors",
    )
    needed = [folder / "infer_3d.py", folder / "infer_4d_ply.py", recon, interp]
    if not all(path.is_file() for path in needed):
        raise GenerationError(
            "animate_unset",
            "L4GM isn't installed on this server: run scripts/l4gm/install.sh on the GPU desktop.",
        )
    python = python or l4gm_python(folder)
    with GPU, tempfile.TemporaryDirectory(prefix="hazard-4d-") as scratch:
        workspace = Path(scratch) / "results"
        source = Path(scratch) / f"{NAME}.mp4"
        source.write_bytes(video)
        common = [
            "big",
            "--workspace",
            str(workspace),
            "--resume",
            str(recon),
            "--test_path",
            str(source),
        ]
        _run([python, "infer_3d.py", *common, "--num_frames", "1"], folder)
        _run(
            [
                python,
                "infer_4d_ply.py",
                *common,
                "--interpresume",
                str(interp),
                "--num_frames",
                str(FRAMES_PER_PASS),
            ],
            folder,
        )
        frames = sorted(workspace.glob(f"{NAME}_wo_interp_*.ply"))
        if len(frames) < 2:
            raise GenerationError("animate")
        return [frame.read_bytes() for frame in frames]
