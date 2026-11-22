"""The 4D step (#226, part of #221): L4GM turns the hazard's video into 3D splat frames.

L4GM runs in its own env on the GPU desktop as two processes: `infer_3d.py` (ImageDream's views of
the first frame) and `infer_4d_ply.py` (the 4D frames, each saved as a splat). A fake L4GM folder
stands in here: its scripts act like the real ones, from their arguments.
"""

import sys
import threading
import time
from pathlib import Path

import pytest

from backend.animation import animate_video
from backend.furniture_generation import GenerationError
from backend.gpu import GPU

FAKE_3D = """
import sys
from pathlib import Path
args = sys.argv
workspace = Path(args[args.index("--workspace") + 1])
name = Path(args[args.index("--test_path") + 1]).stem
workspace.mkdir(parents=True, exist_ok=True)
assert args[args.index("--num_frames") + 1] == "1"
for view in range(4):
    (workspace / f"{name}_{view:03d}.png").write_bytes(b"view")
"""

FAKE_4D = """
import sys
from pathlib import Path
args = sys.argv
workspace = Path(args[args.index("--workspace") + 1])
name = Path(args[args.index("--test_path") + 1]).stem
assert all((workspace / f"{name}_{view:03d}.png").exists() for view in range(4)), "3D step first"
assert args[args.index("--num_frames") + 1] == "8"
if "{mode}" == "oom":
    sys.exit("torch.OutOfMemoryError: CUDA out of memory. Tried to allocate 768.00 MiB.")
if "{mode}" == "fail":
    sys.exit("RuntimeError: something broke")
for frame in (2, 0, 1):
    (workspace / f"{name}_wo_interp_{frame:03d}.ply").write_bytes(f"ply frame {frame}".encode())
    (workspace / f"{name}_w_interp_{frame:03d}.ply").write_bytes(b"in-between")
"""


def fake_l4gm(tmp_path: Path, mode: str = "ok") -> Path:
    folder = tmp_path / "l4gm"
    (folder / "pretrained").mkdir(parents=True)
    (folder / "infer_3d.py").write_text(FAKE_3D)
    (folder / "infer_4d_ply.py").write_text(FAKE_4D.replace("{mode}", mode))
    for weights in ("recon.safetensors", "interp.safetensors"):
        (folder / "pretrained" / weights).write_bytes(b"weights")
    return folder


def test_a_video_becomes_its_4d_frames_in_order(tmp_path):
    frames = animate_video(b"video", fake_l4gm(tmp_path), python=sys.executable)
    assert frames == [b"ply frame 0", b"ply frame 1", b"ply frame 2"]


def test_without_l4gm_installed_it_says_how_to_install_it(tmp_path):
    with pytest.raises(GenerationError) as failed:
        animate_video(b"video", tmp_path / "missing", python=sys.executable)
    assert failed.value.reason == "animate_unset"
    assert "scripts/l4gm/install.sh" in failed.value.message


def test_running_out_of_gpu_memory_is_said_plainly(tmp_path):
    with pytest.raises(GenerationError) as failed:
        animate_video(b"video", fake_l4gm(tmp_path, "oom"), python=sys.executable)
    assert failed.value.reason == "animate"
    assert "ran out of GPU memory" in failed.value.message


def test_any_other_failure_is_a_failed_animation(tmp_path):
    with pytest.raises(GenerationError) as failed:
        animate_video(b"video", fake_l4gm(tmp_path, "fail"), python=sys.executable)
    assert failed.value.reason == "animate"


def test_it_waits_while_something_else_has_the_gpu(tmp_path):
    folder = fake_l4gm(tmp_path)
    done: list[float] = []
    with GPU:
        # A room is being built: the hazard's 4D step waits.
        thread = threading.Thread(
            target=lambda: done.append(len(animate_video(b"video", folder, python=sys.executable)))
        )
        thread.start()
        time.sleep(0.5)
        assert done == []
    thread.join(timeout=30)
    assert done == [3]
