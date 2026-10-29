"""Is this machine ready to reconstruct rooms? (#139)

    python -m backend.gpu_check

Prints one line per check and exits 1 if any fails:
- the NVIDIA driver (`nvidia-smi`) and the GPU torch sees, with its free memory;
- ffprobe, which finishing a room video upload needs (#136);
- pycolmap and transformers, which the pipeline imports (#135);
- gsplat, by training a tiny splat for about 30 s. The first run compiles gsplat's CUDA code, which
  takes 5–10 minutes and needs the CUDA toolkit (`nvcc`).
"""

# torch, gsplat, pycolmap and transformers are only installed on the GPU desktop.
# pyright: basic
# pyright: reportMissingImports=false

import shutil
import subprocess
import sys
import time
from collections.abc import Callable

TRAINING_SECONDS = 30


def driver() -> str:
    result = subprocess.run(
        ["nvidia-smi", "--query-gpu=name,memory.total,driver_version", "--format=csv,noheader"],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def cuda() -> str:
    import torch

    if not torch.cuda.is_available():
        raise RuntimeError("torch sees no CUDA GPU; install torch for CUDA 12.8")
    free, total = torch.cuda.mem_get_info()
    name = torch.cuda.get_device_name(0)
    return (
        f"{name}, {free / 1024**3:.1f} of {total / 1024**3:.1f} GB free, "
        f"torch {torch.__version__} for CUDA {torch.version.cuda}"
    )


def ffprobe() -> str:
    if shutil.which("ffprobe") is None:
        raise RuntimeError("ffprobe not found; install ffmpeg")
    result = subprocess.run(["ffprobe", "-version"], capture_output=True, text=True, check=True)
    return result.stdout.splitlines()[0]


def libraries() -> str:
    import pycolmap
    import transformers

    return f"pycolmap {pycolmap.__version__}, transformers {transformers.__version__}"


def gsplat_training() -> str:
    """Fit 20,000 random splats to a random 256 x 256 picture for about 30 s."""
    import torch
    from gsplat import rasterization

    device = "cuda"
    torch.manual_seed(0)
    count, side = 20_000, 256
    means = (torch.rand(count, 3, device=device) - 0.5) * 2
    means[:, 2] += 3
    params = [
        means.requires_grad_(),
        torch.rand(count, 4, device=device).requires_grad_(),
        torch.full((count, 3), -4.0, device=device).requires_grad_(),
        torch.zeros(count, device=device).requires_grad_(),
        torch.rand(count, 3, device=device).requires_grad_(),
    ]
    optimizer = torch.optim.Adam(params, lr=1e-2)
    viewmat = torch.eye(4, device=device)[None]
    K = torch.tensor([[300.0, 0, side / 2], [0, 300.0, side / 2], [0, 0, 1]], device=device)[None]
    target = torch.rand(side, side, 3, device=device)
    started = time.monotonic()
    steps, loss = 0, None
    while time.monotonic() - started < TRAINING_SECONDS:
        means_, quats, scales, opacities, colours = params
        image, _, _ = rasterization(
            means_,
            torch.nn.functional.normalize(quats, dim=-1),
            torch.exp(scales),
            torch.sigmoid(opacities),
            colours,
            viewmat,
            K,
            side,
            side,
        )
        loss = torch.nn.functional.l1_loss(image[0], target)
        optimizer.zero_grad()
        loss.backward()
        optimizer.step()
        steps += 1
    peak = torch.cuda.max_memory_allocated() / 1024**3
    final = loss.item() if loss is not None else float("nan")
    return f"{steps} steps in {TRAINING_SECONDS} s, loss {final:.3f}, peak {peak:.2f} GB"


CHECKS: list[tuple[str, Callable[[], str]]] = [
    ("NVIDIA driver", driver),
    ("CUDA in torch", cuda),
    ("ffprobe", ffprobe),
    ("pipeline libraries", libraries),
    ("gsplat training", gsplat_training),
]


def main() -> int:
    failed = 0
    for name, check in CHECKS:
        print(f"...  {name}", flush=True)
        try:
            print(f"ok   {name}: {check()}", flush=True)
        except Exception as exc:  # noqa: BLE001 - report every check, whatever breaks
            failed += 1
            print(f"FAIL {name}: {type(exc).__name__}: {exc}", flush=True)
    print("Ready to reconstruct rooms." if not failed else f"{failed} check(s) failed.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
