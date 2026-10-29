"""Splat training and depth renders on the GPU (needs CUDA, torch and gsplat). Moved from the
notebook (spike #92); measured on the GPU desktop, not in the tests."""

# torch and gsplat are only installed on the GPU desktop, and ship few type hints.
# pyright: basic
# pyright: reportMissingImports=false

from pathlib import Path
from typing import Any

import numpy as np

from backend.reconstruction.levelling import Camera
from backend.reconstruction.pipeline import Settings, Step
from backend.reconstruction.splat import OutOfGpuMemory, read_ply, write_ply
from backend.reconstruction.vps_map import DepthRenderer, MapFrame


def train_splat(
    cameras: list[Camera],
    points: np.ndarray,
    colours: np.ndarray,
    settings: Settings,
    out: Path,
    step: Step,
) -> dict[str, Any]:
    """Train a splat on the frames (needs CUDA, torch and gsplat), then write `out/room.ply` and
    held-out previews in `out/previews/`. Frames are shrunk to `settings.long_side` if larger.
    Running past `settings.memory_budget_gb` raises OutOfGpuMemory."""
    import torch
    import torch.nn.functional as F
    from gsplat import rasterization
    from gsplat.strategy import MCMCStrategy
    from PIL import Image

    device = "cuda"
    total = torch.cuda.get_device_properties(0).total_memory
    torch.cuda.set_per_process_memory_fraction(
        min(1.0, settings.memory_budget_gb * 1024**3 / total)
    )
    torch.cuda.empty_cache()
    torch.cuda.reset_peak_memory_stats()
    torch.manual_seed(0)

    def load(camera: Camera) -> tuple[torch.Tensor, torch.Tensor, int, int]:
        image = Image.open(camera["path"]).convert("RGB")
        factor = min(1.0, settings.long_side / max(image.size))
        width, height = round(image.width * factor), round(image.height * factor)
        if factor < 1:
            image = image.resize((width, height), Image.Resampling.LANCZOS)
        K = camera["K"].copy()
        K[:2] *= factor
        return (
            torch.from_numpy(np.array(image)),
            torch.tensor(K, dtype=torch.float32, device=device),
            width,
            height,
        )

    try:
        loaded = [load(camera) for camera in cameras]
        viewmats = [
            torch.tensor(np.linalg.inv(c["camera_to_world"]), dtype=torch.float32, device=device)
            for c in cameras
        ]
        held_out = list(range(0, len(cameras), settings.holdout_every))
        training = [i for i in range(len(cameras)) if i not in held_out]
        centres = np.array([camera["camera_to_world"][:3, 3] for camera in cameras])
        scene_scale = 1.1 * float(np.linalg.norm(centres - centres.mean(axis=0), axis=1).max())

        means = torch.tensor(points, dtype=torch.float32, device=device)
        start_colours = torch.tensor(colours, dtype=torch.float32, device=device)
        # MCMC grows the splat count by only 5% per refinement, so a sparse COLMAP cloud would
        # never reach max_splats. Start from jittered copies of the points.
        copies = max(1, -(-settings.min_start_splats // len(means)))
        if copies > 1:
            spacing = torch.cat(
                [
                    torch.cdist(chunk, means).topk(2, largest=False).values[:, 1]
                    for chunk in means.split(4096)
                ]
            )
            jitter = torch.randn((copies - 1, *means.shape), device=device) * spacing[None, :, None]
            means = torch.cat([means, (means[None] + jitter).reshape(-1, 3)])
            start_colours = start_colours.repeat(copies, 1)
        nearest = torch.cat(
            [
                torch.cdist(chunk, means).topk(4, largest=False).values[:, 1:]
                for chunk in means.split(4096)
            ]
        )
        start_size = torch.sqrt((nearest**2).mean(dim=-1)).clamp_min(1e-4)
        count = len(means)
        degree = settings.sh_degree
        sh = torch.zeros((count, (degree + 1) ** 2, 3), device=device)
        sh[:, 0] = (start_colours / 255 - 0.5) / 0.28209479177387814
        params = torch.nn.ParameterDict(
            {
                "means": torch.nn.Parameter(means),
                "scales": torch.nn.Parameter(
                    torch.log(start_size * 0.1).unsqueeze(-1).repeat(1, 3)
                ),
                "quats": torch.nn.Parameter(torch.rand((count, 4), device=device)),
                "opacities": torch.nn.Parameter(
                    torch.logit(torch.full((count,), 0.5, device=device))
                ),
                "sh0": torch.nn.Parameter(sh[:, :1].contiguous()),
                "shN": torch.nn.Parameter(sh[:, 1:].contiguous()),
            }
        )
        rates = {
            "means": 1.6e-4 * scene_scale,
            "scales": 5e-3,
            "quats": 1e-3,
            "opacities": 5e-2,
            "sh0": 2.5e-3,
            "shN": 2.5e-3 / 20,
        }
        optimizers = {
            name: torch.optim.Adam([{"params": params[name], "lr": rate, "name": name}], eps=1e-15)
            for name, rate in rates.items()
        }
        steps = settings.train_steps
        schedule = torch.optim.lr_scheduler.ExponentialLR(
            optimizers["means"], gamma=0.01 ** (1 / steps)
        )
        # Stop adding and moving splats at the same point as gsplat's 30,000-step default.
        strategy = MCMCStrategy(cap_max=settings.max_splats, refine_stop_iter=int(steps * 25 / 30))
        strategy.check_sanity(params, optimizers)
        state = strategy.initialize_state()

        def render(index: int, sh_degree: int) -> tuple[torch.Tensor, dict]:
            _, K, width, height = loaded[index]
            colours_sh = torch.cat([params["sh0"], params["shN"]], dim=1)
            images, _, info = rasterization(
                params["means"],
                params["quats"],
                torch.exp(params["scales"]),
                torch.sigmoid(params["opacities"]),
                colours_sh,
                viewmats[index][None],
                K[None],
                width,
                height,
                sh_degree=sh_degree,
                packed=False,
            )
            return images[0].clamp(0, 1), info

        def ssim(a: torch.Tensor, b: torch.Tensor) -> torch.Tensor:
            x, y = a.permute(2, 0, 1)[None], b.permute(2, 0, 1)[None]
            g = torch.exp(-((torch.arange(11, device=device) - 5) ** 2) / (2 * 1.5**2))
            window = ((g[:, None] * g[None]) / g.sum() ** 2).expand(3, 1, 11, 11)

            def blur(t: torch.Tensor) -> torch.Tensor:
                return F.conv2d(t, window, groups=3)

            mx, my = blur(x), blur(y)
            vx, vy, cov = blur(x * x) - mx**2, blur(y * y) - my**2, blur(x * y) - mx * my
            c1, c2 = 0.01**2, 0.03**2
            return (
                ((2 * mx * my + c1) * (2 * cov + c2)) / ((mx**2 + my**2 + c1) * (vx + vy + c2))
            ).mean()

        for number in range(steps):
            index = training[torch.randint(len(training), (1,)).item()]
            target = loaded[index][0].to(device, non_blocking=True).float() / 255
            image, info = render(index, min(number // 1000, degree))
            loss = 0.8 * F.l1_loss(image, target) + 0.2 * (1 - ssim(image, target))
            loss = (
                loss
                + 0.01 * torch.sigmoid(params["opacities"]).mean()
                + 0.01 * torch.exp(params["scales"]).mean()
            )
            loss.backward()
            for optimizer in optimizers.values():
                optimizer.step()
                optimizer.zero_grad(set_to_none=True)
            schedule.step()
            strategy.step_post_backward(
                params, optimizers, state, number, info, lr=schedule.get_last_lr()[0]
            )
            if number % 100 == 0 or number == steps - 1:
                splats = len(params["means"])
                step(number + 1, steps, f"{splats:,} splats, loss {loss.item():.4f}")

        (out / "previews").mkdir(parents=True, exist_ok=True)
        scores = []
        with torch.no_grad():
            for shown, index in enumerate(held_out):
                target = loaded[index][0].to(device).float() / 255
                image, _ = render(index, degree)
                scores.append(float(-10 * torch.log10(F.mse_loss(image, target))))
                if shown < 4:
                    pair = torch.cat([target, image], dim=1).mul(255).byte().cpu().numpy()
                    name = cameras[index]["name"]
                    Image.fromarray(pair).save(out / "previews" / f"{name}.jpg", quality=88)
            write_ply(
                out / "room.ply",
                params["means"].cpu().numpy(),
                params["scales"].cpu().numpy(),
                F.normalize(params["quats"], dim=-1).cpu().numpy(),
                params["opacities"].cpu().numpy(),
                params["sh0"].cpu().numpy(),
                params["shN"].cpu().numpy(),
            )
        return {
            "start_splats": count,
            "splats": len(params["means"]),
            "scene_scale": scene_scale,
            "peak_gpu_memory_gb": round(torch.cuda.max_memory_allocated() / 1024**3, 2),
            "held_out_frames": len(held_out),
            "psnr_db": round(float(np.mean(scores)), 2) if scores else None,
        }
    except torch.cuda.OutOfMemoryError as exc:
        raise OutOfGpuMemory(str(exc)) from exc
    finally:
        torch.cuda.empty_cache()


def depth_renderer(splat: Path) -> DepthRenderer:
    """Renders a map frame's depth (z in the camera) and opacity from a written splat, on CUDA."""
    import torch
    from gsplat import rasterization

    device = "cuda"
    stored = read_ply(splat)
    means = torch.tensor(stored["means"], device=device)
    quats = torch.tensor(stored["quats"], device=device)
    scales = torch.exp(torch.tensor(stored["scales"], device=device))
    opacities = torch.sigmoid(torch.tensor(stored["opacities"], device=device))
    colours = torch.zeros((len(means), 3), device=device)

    def render(frame: MapFrame) -> tuple[np.ndarray, np.ndarray]:
        viewmat = torch.tensor(np.linalg.inv(frame.camera_to_world), dtype=torch.float32)
        K = torch.tensor(frame.K, dtype=torch.float32)
        with torch.no_grad():
            depth, alpha, _ = rasterization(
                means,
                quats,
                scales,
                opacities,
                colours,
                viewmat[None].to(device),
                K[None].to(device),
                frame.width,
                frame.height,
                render_mode="ED",
                packed=False,
            )
        return depth[0, ..., 0].cpu().numpy(), alpha[0, ..., 0].cpu().numpy()

    return render
