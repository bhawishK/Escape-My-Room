# %% [markdown]
# # Room video → Gaussian splat (spike #92)
#
# Turns a slow video of one room into a Gaussian splat the Escape My Room viewer can load:
#
# 1. **Frames:** pull sharp frames out of the video.
# 2. **COLMAP:** work out where the camera was for every frame, and a sparse 3D point cloud.
# 3. **Level and scale:** put the floor flat at height 0 and make units roughly metres.
# 4. **Train:** fit a Gaussian splat to the frames on Colab's GPU.
# 5. **Export:** download `room-splat.zip` with `room.ply`, `report.json` and preview images.
#
# Use **Runtime → Change runtime type → T4 GPU**, then **Runtime → Run all**. The upload
# cell asks for the video. A 1–2 minute video takes roughly 45–75 minutes in total, most of it
# COLMAP and training. Keep the tab open.
#
# This is throwaway spike code (issue #92), generated from `spikes/colmap-splat/room_splat.py`.

# %%
# Settings. The defaults suit a 1–2 minute walk around a room.
SAMPLE_SCENE = None  # or a name from SAMPLE_SCENES below, to try the pipeline without a video
QUICK = True  # about half the time, a little less sharp: fewer, smaller frames, less training
MAPPER = "incremental"  # COLMAP's classic mapper, or "global" (GLOMAP) for many hundreds of frames
FRAMES_PER_SECOND = 2.0  # frames kept per second of video
MAX_FRAMES = 120 if QUICK else 240  # COLMAP time grows quickly with more
LONG_SIDE = 1280 if QUICK else 1600  # pixels; larger is sharper but slower to train
EXHAUSTIVE_UP_TO = 150  # up to this many frames, every frame is matched with every other
SEQUENTIAL_OVERLAP = 15  # above it, each frame is matched with this many neighbours
TRAIN_STEPS = 10_000 if QUICK else 20_000  # 30_000 is the usual full training
MAX_SPLATS = 400_000  # caps file size: about 30 MB at SH_DEGREE 1
SH_DEGREE = 1  # view-dependent colour detail; 3 is the usual, 4x larger files
ASSUMED_CAMERA_HEIGHT_M = 1.4  # height the phone was held at; the viewer can correct scale
HOLDOUT_EVERY = 10  # every Nth frame is kept out of training to measure quality
MIN_START_SPLATS = 50_000  # training starts from at least this many, copying COLMAP's points

# %%
# Install. pycolmap is CPU-only here; gsplat compiles its GPU code on first use (5–10 min).
# !nvidia-smi --query-gpu=name,memory.total --format=csv
# !pip -q install pycolmap==4.2.1 gsplat==1.5.3 opencv-python-headless remotezip==0.12.6

# %%
# Helpers: frames, COLMAP, levelling, and the splat file. No GPU needed here.
import json
import shutil
import subprocess
import time
from pathlib import Path

import numpy as np

# Published indoor scenes: photos in capture order, read straight out of the published zip
# without downloading all of it. For testing only; their authors state no licence.
SAMPLE_SCENES = {
    # Mip-NeRF 360 (Barron et al., CVPR 2022): a living room photographed in a full circle.
    "room": ("http://storage.googleapis.com/gresearch/refraw360/360_v2.zip", "room/images_4/"),
    "kitchen": (
        "http://storage.googleapis.com/gresearch/refraw360/360_v2.zip",
        "kitchen/images_4/",
    ),
    "counter": (
        "http://storage.googleapis.com/gresearch/refraw360/360_v2.zip",
        "counter/images_4/",
    ),
    # Deep Blending (Hedman et al., 2018), as packaged with the 3D Gaussian Splatting paper.
    "playroom": (
        "https://repo-sam.inria.fr/fungraph/3d-gaussian-splatting/datasets/input/tandt_db.zip",
        "db/playroom/images/",
    ),
}


def fetch_sample(scene: str, out: Path, long_side: int, max_frames: int) -> int:
    """A published scene's photos as frames, evenly thinned to `max_frames` and resized."""
    from PIL import Image
    from remotezip import RemoteZip

    url, folder = SAMPLE_SCENES[scene]
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True)
    with RemoteZip(url) as archive:
        names = sorted(
            name
            for name in archive.namelist()
            if name.startswith(folder) and name.lower().endswith((".jpg", ".jpeg", ".png"))
        )
        if len(names) > max_frames:
            names = [
                names[i] for i in np.linspace(0, len(names) - 1, max_frames).round().astype(int)
            ]
        for number, name in enumerate(names):
            with archive.open(name) as file:
                image = Image.open(file).convert("RGB")
            image.thumbnail((long_side, long_side))
            image.save(out / f"frame_{number:04d}.jpg", quality=95)
    return len(names)


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
        return float(cv2.Laplacian(grey, cv2.CV_64F).var())

    picked = [max(frames[i : i + 3], key=sharpness) for i in range(0, len(frames), 3)]
    if len(picked) > max_frames:
        keep = np.linspace(0, len(picked) - 1, max_frames).round().astype(int)
        picked = [picked[i] for i in keep]
    for number, path in enumerate(picked):
        shutil.copy(path, out / f"frame_{number:04d}.jpg")
    shutil.rmtree(raw)
    return len(picked)


def reconstruct(
    images: Path, work: Path, overlap: int, mapper: str, exhaustive_up_to: int = 150
) -> dict:
    """COLMAP: features, matching between nearby frames, mapping, then undistorted images.

    "incremental" adds cameras one at a time; "global" (GLOMAP) solves them all at once, which
    pays off with many hundreds of frames. On the 90-frame synthetic room both were equally
    accurate and incremental was faster (84 s against 134 s). If the chosen mapper places fewer
    than 80% of the frames, the other one is tried too and the better result kept.
    """
    import pycolmap

    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    database = work / "database.db"
    reader = pycolmap.ImageReaderOptions()
    # One focal length and one distortion term: phone video has square pixels and is already
    # mostly undistorted, and freer models (OPENCV) can settle on wrong intrinsics that bend
    # the whole room, as the synthetic check showed.
    reader.camera_model = "SIMPLE_RADIAL"
    pycolmap.extract_features(
        database, images, camera_mode=pycolmap.CameraMode.SINGLE, reader_options=reader
    )
    # Matching only neighbours in time misses a corner seen again later in the walk, and placed
    # only half of a published scene's photos; matching all pairs placed them all.
    total = len(list(images.glob("*.jpg")))
    started = time.time()
    if total <= exhaustive_up_to:
        pycolmap.match_exhaustive(database)
        matching = "exhaustive"
    else:
        pairing = pycolmap.SequentialPairingOptions()
        pairing.overlap = overlap
        pairing.quadratic_overlap = True
        pycolmap.match_sequential(database, pairing_options=pairing)
        matching = "sequential"
    matching_seconds = round(time.time() - started, 1)
    timings = {"matching": matching, "matching_seconds": matching_seconds}
    best, used = None, None
    for name in [mapper, "global" if mapper == "incremental" else "incremental"]:
        started = time.time()
        run = pycolmap.global_mapping if name == "global" else pycolmap.incremental_mapping
        (work / f"sparse-{name}").mkdir()
        models = run(database, images, work / f"sparse-{name}") or {}
        timings[f"{name}_mapper_seconds"] = round(time.time() - started, 1)
        if models:
            candidate = max(models.values(), key=lambda model: model.num_reg_images())
            if best is None or candidate.num_reg_images() > best.num_reg_images():
                best, used = candidate, name
        if best is not None and best.num_reg_images() >= 0.8 * total:
            break
    if best is None:
        raise RuntimeError("COLMAP could not place the frames. Try a slower, steadier video.")
    (work / "best").mkdir()
    best.write(work / "best")
    pycolmap.undistort_images(work / "undistorted", work / "best", images)
    camera = next(iter(best.cameras.values()))
    focal = float(camera.params[0])
    return {
        "frames": total,
        "frames_placed": best.num_reg_images(),
        "mapper": used,
        **timings,
        "sparse_points": best.num_points3D(),
        "mean_reprojection_error_px": round(best.compute_mean_reprojection_error(), 3),
        "focal_px": round(focal, 1),
        "horizontal_fov_degrees": round(
            float(np.degrees(2 * np.arctan(camera.width / 2 / focal))), 1
        ),
    }


def load_scene(folder: Path) -> tuple[list[dict], np.ndarray, np.ndarray]:
    """Cameras (intrinsics, camera-to-world, image path) and coloured points of a model."""
    import pycolmap

    model = pycolmap.Reconstruction(folder / "sparse")
    cameras = []
    for image in sorted(model.images.values(), key=lambda image: image.name):
        if not image.has_pose:
            continue
        camera = model.cameras[image.camera_id]
        fx, fy, cx, cy = camera.params[:4]
        world_to_camera = np.eye(4)
        world_to_camera[:3] = image.cam_from_world().matrix()
        cameras.append(
            {
                "name": image.name,
                "path": folder / "images" / image.name,
                "width": camera.width,
                "height": camera.height,
                "K": np.array([[fx, 0, cx], [0, fy, cy], [0, 0, 1]]),
                "camera_to_world": np.linalg.inv(world_to_camera),
            }
        )
    points = np.array([point.xyz for point in model.points3D.values()])
    colours = np.array([point.color for point in model.points3D.values()], dtype=np.uint8)
    return cameras, points, colours


def _rotation_between(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """The rotation turning unit vector a onto unit vector b."""
    v = np.cross(a, b)
    c = float(np.dot(a, b))
    if np.linalg.norm(v) < 1e-9:
        if c > 0:
            return np.eye(3)
        axis = np.cross(a, [1.0, 0, 0] if abs(a[0]) < 0.9 else [0, 1.0, 0])
        axis /= np.linalg.norm(axis)
        return 2 * np.outer(axis, axis) - np.eye(3)
    vx = np.array([[0, -v[2], v[1]], [v[2], 0, -v[0]], [-v[1], v[0], 0]])
    return np.eye(3) + vx + vx @ vx / (1 + c)


def level_room(
    points: np.ndarray, cameras: list[dict], camera_height_m: float
) -> tuple[np.ndarray, dict]:
    """A similarity putting the floor at y = 0 with +y up, units roughly metres, facing -z.

    Up starts as the cameras' average up (frames are upright) and is refined to the normal of
    the lowest large horizontal plane of points, which is taken as the floor. Scale assumes the
    phone was held `camera_height_m` above that floor.
    """
    centres = np.array([camera["camera_to_world"][:3, 3] for camera in cameras])
    # COLMAP cameras look along +z with +y pointing down in the image.
    ups = np.array([-camera["camera_to_world"][:3, 1] for camera in cameras])
    forwards = np.array([camera["camera_to_world"][:3, 2] for camera in cameras])
    up = ups.mean(axis=0)
    up /= np.linalg.norm(up)
    first_up = up.copy()
    method = "lowest horizontal plane"
    floor = None
    for _ in range(3):
        heights = points @ up
        camera_height = float(np.median(centres @ up))
        below = heights[heights < camera_height]
        if len(below) < 50:
            break
        low = float(np.percentile(below, 0.5))
        counts, edges = np.histogram(below, bins=120, range=(low, camera_height))
        width = edges[1] - edges[0]
        start = int(np.argmax(counts >= 0.3 * counts.max()))
        peak = start + int(np.argmax(counts[start : start + 6]))
        floor = float((edges[peak] + edges[peak + 1]) / 2)
        near = points[np.abs(heights - floor) < 1.5 * width]
        if len(near) < 30:
            break
        centred = near - near.mean(axis=0)
        normal = np.linalg.svd(centred, full_matrices=False)[2][-1]
        normal = normal if normal @ up > 0 else -normal
        if np.degrees(np.arccos(np.clip(normal @ up, -1, 1))) > 20:
            break
        up = normal
    heights = points @ up
    camera_height = float(np.median(centres @ up))
    if floor is None:
        method = "lowest points (no floor plane found)"
        floor = float(np.percentile(heights, 1))
    else:
        floor = float(np.median(heights[np.abs(heights - floor) < 0.02 * (camera_height - floor)]))
    held_at = camera_height - floor
    if held_at <= 0:
        raise RuntimeError("The floor was found above the cameras; the video may be upside down.")
    scale = camera_height_m / held_at
    rotation = _rotation_between(up, np.array([0.0, 1.0, 0.0]))
    forward = rotation @ forwards.mean(axis=0)
    forward[1] = 0
    if np.linalg.norm(forward) > 1e-6:
        forward /= np.linalg.norm(forward)
        yaw = np.arctan2(forward[0], -forward[2])
        turn = np.array([[np.cos(yaw), 0, -np.sin(yaw)], [0, 1, 0], [np.sin(yaw), 0, np.cos(yaw)]])
        rotation = turn @ rotation
    centre = centres.mean(axis=0)
    origin = centre - ((centre @ up) - floor) * up
    transform = np.eye(4)
    transform[:3, :3] = scale * rotation
    transform[:3, 3] = -scale * rotation @ origin
    report = {
        "floor": method,
        "up_correction_degrees": round(
            float(np.degrees(np.arccos(np.clip(up @ first_up, -1, 1)))), 2
        ),
        "camera_height_units": round(held_at, 4),
        "assumed_camera_height_m": camera_height_m,
        "scale": scale,
    }
    return transform, report


def apply_transform(
    transform: np.ndarray, cameras: list[dict], points: np.ndarray
) -> tuple[list[dict], np.ndarray]:
    """Move cameras and points by a similarity; camera rotations stay pure rotations."""
    scale = np.cbrt(np.linalg.det(transform[:3, :3]))
    rotation = transform[:3, :3] / scale
    moved = []
    for camera in cameras:
        camera_to_world = camera["camera_to_world"]
        new = np.eye(4)
        new[:3, :3] = rotation @ camera_to_world[:3, :3]
        new[:3, 3] = transform[:3, :3] @ camera_to_world[:3, 3] + transform[:3, 3]
        moved.append({**camera, "camera_to_world": new})
    return moved, points @ transform[:3, :3].T + transform[:3, 3]


def write_ply(path: Path, means, scales, quats, opacities, sh0, sh_rest) -> None:
    """The standard 3DGS PLY: log scales, wxyz quaternions, logit opacity, SH channel-major."""
    count = len(means)
    rest = sh_rest.transpose(0, 2, 1).reshape(count, -1)  # [N, 3 * (K - 1)], all R then G then B
    columns = [
        means,
        np.zeros_like(means),
        sh0.reshape(count, 3),
        rest,
        opacities.reshape(count, 1),
        scales,
        quats,
    ]
    names = ["x", "y", "z", "nx", "ny", "nz", "f_dc_0", "f_dc_1", "f_dc_2"]
    names += [f"f_rest_{i}" for i in range(rest.shape[1])]
    names += ["opacity", "scale_0", "scale_1", "scale_2", "rot_0", "rot_1", "rot_2", "rot_3"]
    data = np.concatenate([np.asarray(column, dtype=np.float32) for column in columns], axis=1)
    header = ["ply", "format binary_little_endian 1.0", f"element vertex {count}"]
    header += [f"property float {name}" for name in names] + ["end_header", ""]
    with open(path, "wb") as file:
        file.write("\n".join(header).encode())
        file.write(data.astype("<f4").tobytes())


# %%
# Upload the video (or set VIDEO to a path, for example in mounted Google Drive). Skipped when
# SAMPLE_SCENE is set.
WORK = Path("/content/room")
VIDEO = None
if VIDEO is None and SAMPLE_SCENE is None:
    from google.colab import files

    uploaded = files.upload()
    VIDEO = Path(next(iter(uploaded)))
report: dict = {
    "video": f"sample: {SAMPLE_SCENE}" if SAMPLE_SCENE else Path(VIDEO).name,
    "settings": {
        "quick": QUICK,
        "mapper": MAPPER,
        "frames_per_second": FRAMES_PER_SECOND,
        "max_frames": MAX_FRAMES,
        "long_side": LONG_SIDE,
        "train_steps": TRAIN_STEPS,
        "max_splats": MAX_SPLATS,
        "sh_degree": SH_DEGREE,
    },
}

# %%
# 1. Frames.
started = time.time()
if SAMPLE_SCENE:
    count = fetch_sample(SAMPLE_SCENE, WORK / "frames", LONG_SIDE, MAX_FRAMES)
else:
    count = extract_frames(Path(VIDEO), WORK / "frames", FRAMES_PER_SECOND, LONG_SIDE, MAX_FRAMES)
report["frames_seconds"] = round(time.time() - started, 1)
print(f"{count} frames in {report['frames_seconds']} s")

# %%
# 2. COLMAP. Expect 10–40 minutes on Colab's CPU.
started = time.time()
report["colmap"] = reconstruct(
    WORK / "frames", WORK / "colmap", SEQUENTIAL_OVERLAP, MAPPER, EXHAUSTIVE_UP_TO
)
report["colmap"]["seconds"] = round(time.time() - started, 1)
print(json.dumps(report["colmap"], indent=2))
if report["colmap"]["frames_placed"] < 0.8 * report["colmap"]["frames"]:
    print("Warning: fewer than 80% of frames were placed; the splat will have gaps.")

# %%
# 3. Level and scale.
cameras, points, colours = load_scene(WORK / "colmap" / "undistorted")
transform, report["levelling"] = level_room(points, cameras, ASSUMED_CAMERA_HEIGHT_M)
cameras, points = apply_transform(transform, cameras, points)
print(json.dumps(report["levelling"], indent=2))

# %%
# 4. Train the splat on the GPU.
import torch
import torch.nn.functional as F
from gsplat import rasterization
from gsplat.strategy import MCMCStrategy
from PIL import Image

device = "cuda"
torch.manual_seed(0)
pictures = [
    torch.from_numpy(np.array(Image.open(camera["path"]).convert("RGB"))) for camera in cameras
]
Ks = [torch.tensor(camera["K"], dtype=torch.float32, device=device) for camera in cameras]
viewmats = [
    torch.tensor(np.linalg.inv(camera["camera_to_world"]), dtype=torch.float32, device=device)
    for camera in cameras
]
held_out = list(range(0, len(cameras), HOLDOUT_EVERY))
training = [i for i in range(len(cameras)) if i not in held_out]
centres = np.array([camera["camera_to_world"][:3, 3] for camera in cameras])
scene_scale = 1.1 * float(np.linalg.norm(centres - centres.mean(axis=0), axis=1).max())

means = torch.tensor(points, dtype=torch.float32, device=device)
start_colours = torch.tensor(colours, dtype=torch.float32, device=device)
# MCMC grows the splat count by only 5% per refinement, so a sparse COLMAP cloud (a small or
# compressed video) would never reach MAX_SPLATS. Start from jittered copies of the points.
copies = max(1, -(-MIN_START_SPLATS // len(means)))
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
    [torch.cdist(chunk, means).topk(4, largest=False).values[:, 1:] for chunk in means.split(4096)]
)
start_size = torch.sqrt((nearest**2).mean(dim=-1)).clamp_min(1e-4)
count = len(means)
sh = torch.zeros((count, (SH_DEGREE + 1) ** 2, 3), device=device)
sh[:, 0] = (start_colours / 255 - 0.5) / 0.28209479177387814
params = torch.nn.ParameterDict(
    {
        "means": torch.nn.Parameter(means),
        "scales": torch.nn.Parameter(torch.log(start_size * 0.1).unsqueeze(-1).repeat(1, 3)),
        "quats": torch.nn.Parameter(torch.rand((count, 4), device=device)),
        "opacities": torch.nn.Parameter(torch.logit(torch.full((count,), 0.5, device=device))),
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
schedule = torch.optim.lr_scheduler.ExponentialLR(
    optimizers["means"], gamma=0.01 ** (1 / TRAIN_STEPS)
)
# Stop adding and moving splats at the same point of training as gsplat's 30,000-step default.
strategy = MCMCStrategy(cap_max=MAX_SPLATS, refine_stop_iter=int(TRAIN_STEPS * 25 / 30))
strategy.check_sanity(params, optimizers)
state = strategy.initialize_state()


def render(index: int, degree: int) -> tuple[torch.Tensor, dict]:
    camera = cameras[index]
    colours_sh = torch.cat([params["sh0"], params["shN"]], dim=1)
    images, _, info = rasterization(
        params["means"],
        params["quats"],
        torch.exp(params["scales"]),
        torch.sigmoid(params["opacities"]),
        colours_sh,
        viewmats[index][None],
        Ks[index][None],
        camera["width"],
        camera["height"],
        sh_degree=degree,
        packed=False,
    )
    return images[0].clamp(0, 1), info


def ssim(a: torch.Tensor, b: torch.Tensor) -> torch.Tensor:
    x, y = a.permute(2, 0, 1)[None], b.permute(2, 0, 1)[None]
    g = torch.exp(-((torch.arange(11, device=device) - 5) ** 2) / (2 * 1.5**2))
    window = (g[:, None] * g[None]) / g.sum() ** 2
    window = window.expand(3, 1, 11, 11)

    def blur(t: torch.Tensor) -> torch.Tensor:
        return F.conv2d(t, window, groups=3)

    mx, my = blur(x), blur(y)
    vx, vy, cov = blur(x * x) - mx**2, blur(y * y) - my**2, blur(x * y) - mx * my
    c1, c2 = 0.01**2, 0.03**2
    return (((2 * mx * my + c1) * (2 * cov + c2)) / ((mx**2 + my**2 + c1) * (vx + vy + c2))).mean()


started = time.time()
for step in range(TRAIN_STEPS):
    index = training[torch.randint(len(training), (1,)).item()]
    target = pictures[index].to(device, non_blocking=True).float() / 255
    out, info = render(index, min(step // 1000, SH_DEGREE))
    loss = 0.8 * F.l1_loss(out, target) + 0.2 * (1 - ssim(out, target))
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
    strategy.step_post_backward(params, optimizers, state, step, info, lr=schedule.get_last_lr()[0])
    if step % 1000 == 0 or step == TRAIN_STEPS - 1:
        print(
            f"step {step}: loss {loss.item():.4f}, {len(params['means']):,} splats, "
            f"{time.time() - started:.0f} s"
        )
report["training"] = {
    "start_splats": count,
    "seconds": round(time.time() - started, 1),
    "splats": len(params["means"]),
    "scene_scale": scene_scale,
}

# %%
# 5. Measure on frames kept out of training, export and download.
out_dir = WORK / "export"
shutil.rmtree(out_dir, ignore_errors=True)
(out_dir / "previews").mkdir(parents=True)
scores = []
with torch.no_grad():
    for number, index in enumerate(held_out):
        target = pictures[index].to(device).float() / 255
        out, _ = render(index, SH_DEGREE)
        scores.append(float(-10 * torch.log10(F.mse_loss(out, target))))
        if number < 4:
            pair = torch.cat([target, out], dim=1).mul(255).byte().cpu().numpy()
            Image.fromarray(pair).save(
                out_dir / "previews" / f"{cameras[index]['name']}.jpg", quality=88
            )
    write_ply(
        out_dir / "room.ply",
        params["means"].cpu().numpy(),
        params["scales"].cpu().numpy(),
        F.normalize(params["quats"], dim=-1).cpu().numpy(),
        params["opacities"].cpu().numpy(),
        params["sh0"].cpu().numpy(),
        params["shN"].cpu().numpy(),
    )
report["quality"] = {"held_out_frames": len(held_out), "psnr_db": round(float(np.mean(scores)), 2)}
report["ply_mb"] = round((out_dir / "room.ply").stat().st_size / 1e6, 1)
# Where each frame was filmed from and the way it faced, so the viewer can start there.
report["cameras"] = [
    {
        "name": camera["name"],
        "position": camera["camera_to_world"][:3, 3].round(4).tolist(),
        "forward": camera["camera_to_world"][:3, 2].round(4).tolist(),
    }
    for camera in cameras
]
(out_dir / "report.json").write_text(json.dumps(report, indent=2))
print(json.dumps({key: value for key, value in report.items() if key != "cameras"}, indent=2))
shutil.make_archive("/content/room-splat", "zip", out_dir)
from google.colab import files

files.download("/content/room-splat.zip")
