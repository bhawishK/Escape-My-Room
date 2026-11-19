"""Repairing renders with Difix3D+ in its own process and env (#215). A fake worker stands in for
Difix: it copies each render as its repair, or misbehaves as told."""

import sys
from pathlib import Path

import pytest
from PIL import Image

from backend.reconstruction.difix import DifixFailed, DifixUnavailable, repair_views

FAKE_WORKER = """
import shutil, sys
from pathlib import Path
folder = Path(sys.argv[1])
if "{mode}" == "fail":
    sys.exit("out of memory")
for render in sorted(folder.glob("*-render.png")):
    if "{mode}" == "skip" and render.name.startswith("01"):
        continue
    shutil.copy(render, folder / render.name.replace("-render", "-fixed"))
"""


def views(folder: Path, count: int) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    for index in range(count):
        for kind in ("render", "reference"):
            Image.new("RGB", (16, 12), (index * 40, 0, 0)).save(folder / f"{index:02d}-{kind}.png")


def worker(tmp_path: Path, mode: str = "copy") -> list[str]:
    script = tmp_path / f"worker-{mode}.py"
    script.write_text(FAKE_WORKER.format(mode=mode))
    return [sys.executable, str(script)]


def test_each_render_gets_its_repair(tmp_path):
    folder = tmp_path / "round-1"
    views(folder, 3)
    fixed = repair_views(folder, worker(tmp_path))
    assert [path.name for path in fixed] == ["00-fixed.png", "01-fixed.png", "02-fixed.png"]
    assert all(path.is_file() for path in fixed)


def test_a_repair_that_is_missing_is_an_error_not_a_gap(tmp_path):
    folder = tmp_path / "round-1"
    views(folder, 3)
    with pytest.raises(DifixFailed, match="01-render.png"):
        repair_views(folder, worker(tmp_path, "skip"))


def test_a_failing_worker_says_why(tmp_path):
    folder = tmp_path / "round-1"
    views(folder, 1)
    with pytest.raises(DifixFailed, match="out of memory"):
        repair_views(folder, worker(tmp_path, "fail"))


def test_without_difix_installed_it_says_how_to_set_it_up(tmp_path):
    folder = tmp_path / "round-1"
    views(folder, 1)
    with pytest.raises(DifixUnavailable, match="ESCAPE_ROOM_DIFIX_PYTHON"):
        repair_views(folder, [str(tmp_path / "no-such-python"), "worker.py"])
