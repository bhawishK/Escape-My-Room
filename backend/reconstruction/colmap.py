"""COLMAP: where the camera was for every frame, and a sparse point cloud. Needs pycolmap.

Feature extraction and matching use the GPU when pycolmap was built with CUDA; the wheels on PyPI
are CPU-only, which is slower but gives the same result (see docs/reconstruction.md).
"""

# cv2, pycolmap, torch and transformers are only installed on the GPU desktop.
# pyright: basic
# pyright: reportMissingImports=false

import shutil
import time
from pathlib import Path
from typing import Any

import numpy as np

from backend.reconstruction.levelling import Camera


def reconstruct(
    images: Path, work: Path, overlap: int, mapper: str, exhaustive_up_to: int = 150
) -> dict[str, Any]:
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
        database,
        images,
        camera_mode=pycolmap.CameraMode.SINGLE,
        reader_options=reader,
        device=pycolmap.Device.auto,
    )
    # Matching only neighbours in time misses a corner seen again later in the walk, and placed
    # only half of a published scene's photos; matching all pairs placed them all.
    total = len(list(images.glob("*.jpg")))
    started = time.time()
    if total <= exhaustive_up_to:
        pycolmap.match_exhaustive(database, device=pycolmap.Device.auto)
        matching = "exhaustive"
    else:
        pairing = pycolmap.SequentialPairingOptions()
        pairing.overlap = overlap
        pairing.quadratic_overlap = True
        pycolmap.match_sequential(database, pairing_options=pairing, device=pycolmap.Device.auto)
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


def load_scene(folder: Path) -> tuple[list[Camera], np.ndarray, np.ndarray]:
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


def write_levelled_model(folder: Path, transform: np.ndarray, out: Path) -> None:
    """The undistorted model moved by the levelling similarity, into the splat's frame."""
    import pycolmap

    model = pycolmap.Reconstruction(folder / "sparse")
    scale = float(np.cbrt(np.linalg.det(transform[:3, :3])))
    rotation = pycolmap.Rotation3d(transform[:3, :3] / scale)
    model.transform(pycolmap.Sim3d(scale, rotation, transform[:3, 3]))
    out.mkdir(parents=True, exist_ok=True)
    model.write(out)
