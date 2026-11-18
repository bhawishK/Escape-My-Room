"""Where a splat room is see-through, as the devices draw it (#206).

Renders each view with Spark twice, on black and on white. Where the splat is solid the two
agree; where it is see-through the background shows, so the difference is (1 - opacity). This
measures holes as people see them, faint splats included, unlike counting splats.

Views: along the filmed path, standing at spots across the floor looking at each wall, and from
above and the upper corners, as the dollhouse is seen.

Usage: python holes.py ROOM_DIR OUT_DIR WALLS_JSON
"""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from PIL import Image  # noqa: E402

from backend.room_views import View, filmed, render_views  # noqa: E402

SIZE = (320, 240)
SOLID = 0.8  # a pixel at least this opaque counts as covered


def views_for(room: Path, walls: dict) -> list[tuple[str, View]]:
    (x0, x1), (z0, z1) = walls["x"], walls["z"]
    cx, cz = (x0 + x1) / 2, (z0 + z1) / 2
    chosen: list[tuple[str, View]] = []
    path = filmed(room)
    for index in range(0, len(path), 10):
        chosen.append((f"filmed {index}", View(position=path[index].position, look_at=path[index].look_at)))
    targets = {"left": (x0, 1.2, cz), "right": (x1, 1.2, cz), "far": (cx, 1.2, z0), "near": (cx, 1.2, z1)}
    for sx in (x0 + 0.25 * (x1 - x0), x0 + 0.75 * (x1 - x0)):
        spot = (sx, 1.6, cz)
        for name, target in targets.items():
            chosen.append((f"standing x{sx:.1f} to {name}", View(position=spot, look_at=target)))
    middle = (cx, 0.0, cz)
    chosen.append(("above", View(position=(cx, 4.5, cz + 0.001), look_at=middle)))
    for name, (x, z) in {"corner far-left": (x0, z0), "corner far-right": (x1, z0),
                         "corner near-left": (x0, z1), "corner near-right": (x1, z1)}.items():
        chosen.append((name, View(position=(x + (x - cx) * 0.6, 3.2, z + (z - cz) * 0.6), look_at=middle)))
    return chosen


def opacity_maps(room: Path, views: list[View]) -> list[np.ndarray]:
    sized = [View(position=v.position, look_at=v.look_at, fov_degrees=v.fov_degrees, width=SIZE[0], height=SIZE[1]) for v in views]
    def render(background: str) -> list[np.ndarray]:
        with_background = [View(**{**v.__dict__, "background": background}) for v in sized]
        return [np.asarray(Image.open(io.BytesIO(r.png)).convert("RGB"), float) / 255 for r in render_views(room, with_background)]
    black, white = render("#000000"), render("#ffffff")
    return [1 - np.clip((w - b).mean(axis=2), 0, 1) for b, w in zip(black, white)], black


def main() -> None:
    room, out, walls = Path(sys.argv[1]), Path(sys.argv[2]), json.loads(Path(sys.argv[3]).read_text())
    out.mkdir(parents=True, exist_ok=True)
    named = views_for(room, walls)
    maps, colours = opacity_maps(room, [view for _, view in named])
    summary = []
    tiles = []
    for (name, _), alpha, colour in zip(named, maps, colours):
        covered = float((alpha >= SOLID).mean())
        summary.append({"view": name, "covered": round(covered, 3), "mean_opacity": round(float(alpha.mean()), 3)})
        # The render, with see-through places tinted magenta.
        tint = colour * alpha[..., None] + np.array([1, 0, 1]) * (1 - alpha[..., None])
        tiles.append((np.clip(tint, 0, 1) * 255).astype(np.uint8))
    columns = 6
    rows = [np.concatenate(tiles[i:i + columns] + [np.full_like(tiles[0], 255)] * (columns - len(tiles[i:i + columns])), axis=1)
            for i in range(0, len(tiles), columns)]
    Image.fromarray(np.concatenate(rows, axis=0)).save(out / "holes.png")
    groups: dict[str, list[float]] = {}
    for item in summary:
        group = item["view"].split(" ")[0]
        groups.setdefault(group, []).append(item["covered"])
    (out / "holes.json").write_text(json.dumps({"views": summary, "covered_by_group": {g: round(float(np.mean(v)), 3) for g, v in groups.items()}}, indent=2))
    for group, values in groups.items():
        print(f"{group:10s} {len(values):2d} views, covered {np.mean(values):.0%} (worst {min(values):.0%})")


if __name__ == "__main__":
    main()
