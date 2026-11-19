"""Puts a splat room's floor on its real floor and rescales it from the camera height (#206).

The pipeline took the lowest large flat surface as the floor; in the live room that was a bed's
top, with the wooden floor 0.83 m below it. This fits a plane to the splats on the real floor,
then works out a new manifest placement: turned so that plane is level, moved so it is at y = 0,
and scaled so the cameras stand CAMERA_HEIGHT_M above it. The PLY is untouched; the visual
positioning map is in the PLY's own frame, so the new placement carries it along too.

Usage: python fix_floor.py ROOM_DIR OUT_DIR FLOOR_Y_GUESS [CAMERA_HEIGHT_M]
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import numpy as np

from splat import Placement, read_ply

BAND_M = 0.06


def fit_plane(points: np.ndarray, rounds: int = 400, tolerance: float = 0.015, seed: int = 0) -> tuple[np.ndarray, float, np.ndarray]:
    """RANSAC then least squares: the unit normal (y up), d with n·p = d, and the inliers."""
    rng = np.random.default_rng(seed)
    best = np.zeros(len(points), bool)
    for _ in range(rounds):
        a, b, c = points[rng.choice(len(points), 3, replace=False)]
        normal = np.cross(b - a, c - a)
        if np.linalg.norm(normal) < 1e-9:
            continue
        normal /= np.linalg.norm(normal)
        if abs(normal[1]) < 0.9:  # only near-horizontal planes
            continue
        inliers = np.abs(points @ normal - normal @ a) < tolerance
        if inliers.sum() > best.sum():
            best = inliers
    centre = points[best].mean(axis=0)
    _, _, vt = np.linalg.svd(points[best] - centre)
    normal = vt[2] if vt[2][1] > 0 else -vt[2]
    return normal, float(normal @ centre), best


def levelling(normal: np.ndarray) -> np.ndarray:
    """The smallest turn carrying `normal` onto +y (Rodrigues)."""
    up = np.array([0.0, 1.0, 0.0])
    axis = np.cross(normal, up)
    sine, cosine = np.linalg.norm(axis), float(normal @ up)
    if sine < 1e-12:
        return np.eye(3)
    k = axis / sine
    skew = np.array([[0, -k[2], k[1]], [k[2], 0, -k[0]], [-k[1], k[0], 0]])
    return np.eye(3) + sine * skew + (1 - cosine) * skew @ skew


def quaternion(matrix: np.ndarray) -> dict[str, float]:
    trace = np.trace(matrix)
    if trace > 0:
        s = 2 * np.sqrt(trace + 1)
        w, x, y, z = s / 4, (matrix[2, 1] - matrix[1, 2]) / s, (matrix[0, 2] - matrix[2, 0]) / s, (matrix[1, 0] - matrix[0, 1]) / s
    else:
        i = int(np.argmax(np.diag(matrix)))
        j, k = (i + 1) % 3, (i + 2) % 3
        s = 2 * np.sqrt(1 + matrix[i, i] - matrix[j, j] - matrix[k, k])
        q = np.zeros(3)
        q[i] = s / 4
        q[j] = (matrix[j, i] + matrix[i, j]) / s
        q[k] = (matrix[k, i] + matrix[i, k]) / s
        w = (matrix[k, j] - matrix[j, k]) / s
        x, y, z = q
    return {"x": float(x), "y": float(y), "z": float(z), "w": float(w)}


def main() -> None:
    room, out = Path(sys.argv[1]), Path(sys.argv[2])
    guess = float(sys.argv[3])
    camera_height = float(sys.argv[4]) if len(sys.argv) > 4 else 1.4
    manifest = json.loads((room / "manifest.json").read_text())
    report = json.loads((room / "report.json").read_text())
    splat = read_ply(room / "room.ply")
    placement = Placement.of(room / "manifest.json")
    points = placement.to_room(splat.xyz)

    near = (splat.opacity > 0.15) & (np.abs(points[:, 1] - guess) < BAND_M)
    normal, offset, inliers = fit_plane(points[near])
    tilt = np.degrees(np.arccos(normal[1]))
    print(f"floor plane from {inliers.sum()} of {near.sum()} splats near y = {guess}: tilt {tilt:.2f}°, "
          f"y at the origin {offset / normal[1]:.3f} m")

    # New room point = k * L * (old - f0): f0 is the floor under the old origin, L levels it.
    turn = levelling(normal)
    f0 = np.array([0.0, offset / normal[1], 0.0])
    # The report lists cameras in the splat's own frame: the placement carries them into the room.
    cameras = placement.to_room(np.array([camera["position"] for camera in report["cameras"]]))
    heights = (cameras - f0) @ normal
    k = camera_height / float(np.median(heights))
    print(f"cameras {np.median(heights):.3f} m above that floor (median of {len(cameras)}); "
          f"scale × {k:.4f} so they stand {camera_height} m above it")

    new_position = k * turn @ (placement.position - f0)
    new_rotation = turn @ placement.rotation
    new_scale = k * placement.scale

    def to_new(old: np.ndarray) -> np.ndarray:
        return k * (np.atleast_2d(old) - f0) @ turn.T

    moved = to_new(points)
    floor_band = (splat.opacity > 0.15) & (np.abs(moved[:, 1]) < 0.03)
    low = np.percentile(moved[floor_band][:, [0, 2]], 2, axis=0)
    high = np.percentile(moved[floor_band][:, [0, 2]], 98, axis=0)
    print(f"wooden floor in the new room: x {low[0]:.2f}..{high[0]:.2f}, z {low[1]:.2f}..{high[1]:.2f} m")

    splat_entry = dict(manifest["splat"])
    splat_entry.update({
        "position": dict(zip("xyz", map(float, new_position))),
        "rotation": quaternion(new_rotation),
        "scale": float(new_scale),
        "scale_source": f"assumed: the phone was held {camera_height} m above the wooden floor (#206)",
    })
    manifest["splat"] = splat_entry
    for entity in manifest["entities"]:
        if entity["id"] == "floor":
            entity["size"]["width"] = float(high[0] - low[0])
            entity["size"]["depth"] = float(high[1] - low[1])
            entity["position"] = {"x": float((low[0] + high[0]) / 2), "y": -0.02, "z": float((low[1] + high[1]) / 2)}
        elif entity["id"] == "box":
            # The box keeps its place over the floor, now on the real floor.
            x, _, z = to_new(np.array([entity["position"][key] for key in "xyz"]))[0]
            entity["position"] = {"x": float(x), "y": 0.0, "z": float(z)}

    out.mkdir(parents=True, exist_ok=True)
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2))
    from refine import write_entity_glb
    floor = next(entity for entity in manifest["entities"] if entity["id"] == "floor")
    write_entity_glb(out, "floor", (floor["size"]["width"], floor["size"]["height"], floor["size"]["depth"]), "#8d9399")
    for name in ("room.ply", "room-phone.ply", "box.glb"):
        if not (out / name).exists():
            shutil.copy2(room / name, out / name)
    # The report's cameras are in the splat's own frame, which the new placement carries along.
    shutil.copy2(room / "report.json", out / "report.json")
    print("new placement:", json.dumps({key: splat_entry[key] for key in ("position", "rotation", "scale")}))


if __name__ == "__main__":
    main()
