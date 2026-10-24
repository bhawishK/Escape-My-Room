"""Check the notebook's CPU steps on a synthetic room video whose geometry is known.

Renders a textured 4 m x 5 m x 2.6 m room with a table and a cabinet, filmed from 1.4 m while
walking round its edge, then runs the notebook's frame, COLMAP and levelling helpers on it and
compares the cameras with the truth. Also writes the sparse points as a small splat file for the
viewer.

    python check_pipeline.py OUTPUT_DIR [incremental|global]
    (needs ffmpeg, pycolmap, numpy, opencv)
"""

import re
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
WIDTH, HEIGHT, FPS, SECONDS = 960, 540, 30, 30
CAMERA_HEIGHT = 1.4
LOOP = (1.3, 1.8)  # the walk's half-widths across x and z, in metres
TRUE_FOCAL = WIDTH / 2 / np.tan(np.radians(70) / 2)


def helpers() -> dict:
    """The notebook's helper cell, run as code."""
    source = (HERE / "room_splat.py").read_text(encoding="utf-8")
    cells = re.split(r"^# %%.*$", source, flags=re.MULTILINE)
    [cell] = [cell for cell in cells if cell.lstrip().startswith("# Helpers")]
    namespace: dict = {}
    exec(compile(cell, "helpers", "exec"), namespace)
    return namespace


def texture(rng: np.random.Generator, width_m: float, height_m: float) -> np.ndarray:
    """A non-repeating pattern of coloured blobs and lines over grain, 300 pixels per metre."""
    import cv2

    w, h = max(int(width_m * 300), 8), max(int(height_m * 300), 8)
    image = np.full((h, w, 3), rng.integers(60, 200, 3), dtype=np.uint8)
    for _ in range(int(w * h / 900)):
        colour = tuple(int(c) for c in rng.integers(0, 256, 3))
        x, y = int(rng.integers(0, w)), int(rng.integers(0, h))
        if rng.random() < 0.6:
            cv2.circle(image, (x, y), int(rng.integers(3, 18)), colour, -1)
        else:
            cv2.line(
                image,
                (x, y),
                (x + int(rng.integers(-40, 40)), y + int(rng.integers(-40, 40))),
                colour,
                3,
            )
    # Grain at two scales, like plaster, wood and fabric in a real room.
    grain = sum(
        cv2.resize(
            rng.normal(0, 1, (h // s + 1, w // s + 1)), (w, h), interpolation=cv2.INTER_CUBIC
        )
        * a
        for s, a in ((2, 18), (9, 30))
    )
    return np.clip(image + grain[..., None], 0, 255).astype(np.uint8)


def rectangles(rng: np.random.Generator) -> list[dict]:
    """Axis-aligned textured rectangles: the room's six faces and the furniture's sides and tops."""
    boxes = [((-2.0, 0.0, -2.5), (2.0, 2.6, 2.5), True)]  # the room, seen from inside
    boxes += [
        ((0.3, 0.0, -1.6), (1.1, 0.75, -0.9), False),
        ((-1.9, 0.0, 0.5), (-1.4, 1.2, 1.5), False),
    ]
    faces = []
    for low, high, inside in boxes:
        for axis in range(3):
            for value in (low[axis], high[axis]):
                if not inside and axis == 1 and value == low[1]:
                    continue  # furniture has no visible bottom
                u, v = [a for a in range(3) if a != axis]
                faces.append(
                    {
                        "axis": axis,
                        "value": value,
                        "u": u,
                        "v": v,
                        "low": (low[u], low[v]),
                        "high": (high[u], high[v]),
                        "image": texture(rng, high[u] - low[u], high[v] - low[v]),
                    }
                )
    return faces


def path(count: int) -> list[tuple[np.ndarray, np.ndarray]]:
    """Camera-to-world rotations (COLMAP axes: x right, y down, z forward) and positions."""
    poses = []
    for i in range(count):
        # Walk round the edge of the room, 0.7 m from the walls, facing across it and sweeping
        # 30 degrees either side, as the filming guide asks.
        angle = 2 * np.pi * i / count
        position = np.array(
            [
                LOOP[0] * np.cos(angle),
                CAMERA_HEIGHT + 0.03 * np.sin(5 * angle),
                LOOP[1] * np.sin(angle),
            ]
        )
        yaw = np.arctan2(-position[2], -position[0]) + np.radians(30) * np.sin(3 * angle)
        pitch = np.radians(-12)
        forward = np.array(
            [np.cos(yaw) * np.cos(pitch), np.sin(pitch), np.sin(yaw) * np.cos(pitch)]
        )
        right = np.cross(forward, [0.0, 1.0, 0.0])
        right /= np.linalg.norm(right)
        down = np.cross(forward, right)
        poses.append((np.stack([right, down, forward], axis=1), position))
    return poses


def render(
    faces: list[dict], rotation: np.ndarray, position: np.ndarray, focal: float
) -> np.ndarray:
    xs, ys = np.meshgrid(np.arange(WIDTH) + 0.5 - WIDTH / 2, np.arange(HEIGHT) + 0.5 - HEIGHT / 2)
    rays = np.stack([xs / focal, ys / focal, np.ones_like(xs)], axis=-1).reshape(-1, 3) @ rotation.T
    nearest = np.full(len(rays), np.inf)
    colour = np.zeros((len(rays), 3), dtype=np.uint8)
    for face in faces:
        d = rays[:, face["axis"]]
        with np.errstate(divide="ignore", invalid="ignore"):
            t = (face["value"] - position[face["axis"]]) / d
        hit = position + t[:, None] * rays
        pu, pv = hit[:, face["u"]], hit[:, face["v"]]
        (lu, lv), (hu, hv) = face["low"], face["high"]
        ok = (t > 1e-6) & (t < nearest) & (pu >= lu) & (pu <= hu) & (pv >= lv) & (pv <= hv)
        image = face["image"]
        iu = np.clip(
            ((pu[ok] - lu) / (hu - lu) * (image.shape[1] - 1)).astype(int), 0, image.shape[1] - 1
        )
        iv = np.clip(
            ((pv[ok] - lv) / (hv - lv) * (image.shape[0] - 1)).astype(int), 0, image.shape[0] - 1
        )
        colour[ok] = image[iv, iu]
        nearest[ok] = t[ok]
    return colour.reshape(HEIGHT, WIDTH, 3)


def make_video(out: Path) -> list[tuple[np.ndarray, np.ndarray]]:
    rng = np.random.default_rng(7)
    faces = rectangles(rng)
    poses = path(FPS * SECONDS)
    focal = TRUE_FOCAL
    encoder = subprocess.Popen(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "-s",
            f"{WIDTH}x{HEIGHT}",
            "-r",
            str(FPS),
            "-i",
            "-",
            "-c:v",
            "libx264",
            "-crf",
            "18",
            "-pix_fmt",
            "yuv420p",
            str(out),
        ],
        stdin=subprocess.PIPE,
    )
    for rotation, position in poses:
        encoder.stdin.write(render(faces, rotation, position, focal).tobytes())
    encoder.stdin.close()
    encoder.wait()
    return poses


def main(out: Path, mapper: str) -> int:
    out.mkdir(parents=True, exist_ok=True)
    h = helpers()
    if not (out / "synthetic.mp4").exists():
        started = time.time()
        make_video(out / "synthetic.mp4")
        print(f"video: rendered in {time.time() - started:.0f} s")

    count = h["extract_frames"](out / "synthetic.mp4", out / "frames", 3.0, 960, 240)
    started = time.time()
    colmap = h["reconstruct"](out / "frames", out / "colmap", 15, mapper)
    print(f"frames: {count}; COLMAP in {time.time() - started:.0f} s: {colmap}")
    cameras, points, colours = h["load_scene"](out / "colmap" / "undistorted")
    transform, levelling = h["level_room"](points, cameras, CAMERA_HEIGHT)
    cameras, points = h["apply_transform"](transform, cameras, points)
    print(f"levelling: {levelling}")

    # Frames were kept at 3 per second from 30 fps, the sharpest of each 3 at 9 fps.
    found = np.array([camera["camera_to_world"][:3, 3] for camera in cameras])
    heights = found[:, 1]
    ups = np.array([-camera["camera_to_world"][:3, 1] for camera in cameras])
    true_pitch = 12.0
    tilt = np.degrees(np.arccos(np.clip(ups[:, 1], -1, 1)))
    floor = points[points[:, 1] < 0.3, 1]
    walk = found[:, [0, 2]] - found[:, [0, 2]].mean(axis=0)
    radius = float(np.linalg.norm(walk, axis=1).mean())
    true_walk = np.array([position[[0, 2]] for _, position in path(360)])
    true_radius = float(np.linalg.norm(true_walk, axis=1).mean())
    spread = np.linalg.svd(walk, full_matrices=False)[1]
    shape, true_shape = float(spread[0] / spread[1]), LOOP[1] / LOOP[0]
    checks = {
        "frames placed": (
            colmap["frames_placed"] / colmap["frames"],
            colmap["frames_placed"] >= 0.9 * colmap["frames"],
        ),
        "camera height spread (m)": (float(heights.std()), heights.std() < 0.05),
        "camera tilt vs 12 deg": (float(np.median(tilt)), abs(np.median(tilt) - true_pitch) < 1.5),
        "floor points median y (m)": (
            float(np.median(floor)) if len(floor) else None,
            len(floor) > 0 and abs(np.median(floor)) < 0.03,
        ),
        f"walk mean radius vs {true_radius:.2f} m": (radius, abs(radius / true_radius - 1) < 0.05),
        f"walk shape vs {true_shape:.3f}": (shape, abs(shape / true_shape - 1) < 0.05),
        f"focal vs {TRUE_FOCAL:.1f} px": (
            colmap["focal_px"],
            abs(colmap["focal_px"] / TRUE_FOCAL - 1) < 0.03,
        ),
    }
    failed = False
    for name, (value, ok) in checks.items():
        print(f"{'ok  ' if ok else 'FAIL'} {name}: {value}")
        failed |= not ok

    # Sparse points as small round splats, so the viewer can be tried before any training.
    n = len(points)
    h["write_ply"](
        out / "room.ply",
        points,
        np.full((n, 3), np.log(0.012)),
        np.tile([1.0, 0, 0, 0], (n, 1)),
        np.full(n, 4.0),
        ((colours / 255 - 0.5) / 0.28209479177387814)[:, None, :],
        np.zeros((n, 3, 3)),
    )
    print(f"wrote {out / 'room.ply'} with {n} points")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1]), sys.argv[2] if len(sys.argv) > 2 else "incremental"))
