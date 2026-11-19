"""Each frame's depth from Depth Anything V2 Small, fitted to metres for splat training (#209).

Runs on the GPU desktop (needs torch and transformers); the fitting is `depth_prior`'s, which is
tested without one. The model gives a relative inverse depth; each frame's is fitted to metres
by the COLMAP points that frame observed (`camera["seen"]`), and written as
`<out>/<frame name>.npz` (`depth`, float16 metres, 0 where unknown) at the size training uses.
A frame whose fit fails gets no file, and is trained on colour alone.

Depth-Anything-V2-Small is Apache-2.0; the larger sizes are CC-BY-NC-4.0.
"""

# torch and transformers are only installed on the GPU desktop.
# pyright: basic
# pyright: reportMissingImports=false

from pathlib import Path
from typing import Any

import numpy as np

from backend.reconstruction.depth_prior import (
    fit_inverse_depth,
    metric_depth,
    seen_points,
    training_size,
)
from backend.reconstruction.levelling import Camera
from backend.reconstruction.pipeline import Step

DEPTH_MODEL = "depth-anything/Depth-Anything-V2-Small-hf"


def write_depth_priors(
    cameras: list[Camera], points: np.ndarray, out: Path, long_side: int, step: Step
) -> dict[str, Any]:
    import torch
    import torch.nn.functional as F
    from PIL import Image
    from transformers import AutoImageProcessor, AutoModelForDepthEstimation

    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob("*.npz"):
        old.unlink()
    # The model is public; a stale login stored on the machine would make the Hub refuse it.
    processor = AutoImageProcessor.from_pretrained(DEPTH_MODEL, token=False)
    model = AutoModelForDepthEstimation.from_pretrained(DEPTH_MODEL, token=False).to("cuda").eval()
    fitted, errors = 0, []
    try:
        for number, camera in enumerate(cameras):
            image = Image.open(camera["path"]).convert("RGB")
            width, height, factor = training_size(image.width, image.height, long_side)
            with torch.no_grad():
                inputs = processor(images=image, return_tensors="pt").to("cuda")
                predicted = model(**inputs).predicted_depth
                relative = (
                    F.interpolate(
                        predicted[:, None],
                        size=(height, width),
                        mode="bicubic",
                        align_corners=False,
                    )[0, 0]
                    .float()
                    .cpu()
                    .numpy()
                )
            K = camera["K"].copy()
            K[:2] *= factor
            sized = {**camera, "K": K, "width": width, "height": height}
            seen = camera.get("seen")
            observed = points[seen] if seen is not None and len(seen) else points
            pixels, depths = seen_points(sized, observed)
            fit = fit_inverse_depth(relative, pixels, depths)
            if fit is not None:
                a, b = fit
                columns = np.clip(pixels[:, 0].astype(int), 0, width - 1)
                rows = np.clip(pixels[:, 1].astype(int), 0, height - 1)
                errors.append(
                    float(np.median(np.abs((a * relative[rows, columns] + b) * depths - 1)))
                )
                depth = metric_depth(relative, fit).astype(np.float16)
                np.savez_compressed(out / f"{camera['name']}.npz", depth=depth)
                fitted += 1
            step(number + 1, len(cameras), f"depth for {number + 1} of {len(cameras)} frames")
    finally:
        del model
        torch.cuda.empty_cache()
    return {
        "model": DEPTH_MODEL,
        "frames": len(cameras),
        "fitted": fitted,
        # How far the fitted depth is off at the points, in proportion, per frame's median.
        "median_point_error": round(float(np.median(errors)), 4) if errors else None,
    }
