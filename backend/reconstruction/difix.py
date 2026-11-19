"""Repair renders with Difix3D+ (#215), in its own process and Python env.

Difix (NVIDIA, research and evaluation use only) needs old diffusers and transformers, so it lives
in its own env (`~/difix` on the GPU desktop) and runs as a separate process. Training's GPU memory
is then free for it while it runs, and the project env never imports it.

A round's folder holds `<n>-render.png` and `<n>-reference.png`, its nearest filmed frame; the
worker (`difix_worker.py`) writes `<n>-fixed.png` beside them.

ESCAPE_ROOM_DIFIX_PYTHON is Difix's Python (default `~/difix/.venv/bin/python`) and
ESCAPE_ROOM_DIFIX_SRC its `src` folder (default `~/difix/src`).
"""

import os
import subprocess
from pathlib import Path

WORKER = Path(__file__).with_name("difix_worker.py")
# Loading the model takes about 10 s and each view about half a second on the desktop.
TIMEOUT_SECONDS = 900


class DifixUnavailable(Exception):
    """Difix's env isn't installed where the settings say."""


class DifixFailed(Exception):
    """The worker stopped, or left a render without its repair."""


def difix_command() -> list[str]:
    python = os.environ.get("ESCAPE_ROOM_DIFIX_PYTHON", str(Path.home() / "difix/.venv/bin/python"))
    return [python, str(WORKER)]


def repair_views(folder: Path, command: list[str] | None = None) -> list[Path]:
    """Every render's repair, in order. Raises DifixUnavailable or DifixFailed."""
    command = command or difix_command()
    if not Path(command[0]).is_file():
        raise DifixUnavailable(
            f"Difix's Python isn't at {command[0]}; install Difix3D+ in its own env and set "
            "ESCAPE_ROOM_DIFIX_PYTHON (and ESCAPE_ROOM_DIFIX_SRC) to it."
        )
    source = os.environ.get("ESCAPE_ROOM_DIFIX_SRC", str(Path.home() / "difix/src"))
    environment = os.environ | {"PYTHONPATH": source}
    try:
        subprocess.run(
            [*command, str(folder)],
            check=True,
            capture_output=True,
            text=True,
            env=environment,
            timeout=TIMEOUT_SECONDS,
        )
    except subprocess.CalledProcessError as exc:
        reason = (exc.stderr or exc.stdout or "").strip().splitlines()
        raise DifixFailed(f"Difix stopped: {reason[-1] if reason else exc.returncode}") from exc
    except subprocess.TimeoutExpired as exc:
        raise DifixFailed(f"Difix took longer than {TIMEOUT_SECONDS} s") from exc
    fixed: list[Path] = []
    for render in sorted(folder.glob("*-render.png")):
        repair = render.with_name(render.name.replace("-render", "-fixed"))
        if not repair.is_file():
            raise DifixFailed(f"Difix left {render.name} without its repair")
        fixed.append(repair)
    return fixed
