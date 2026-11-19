"""Join throw_video.mjs's frames into one animated GIF, and measure how much of the box shows.

Each frame is "as seen" beside "box outlined through everything", at the speed physics moved it.
The box's model is orange, so the orange pixels in the seen frame, against the orange pixels
inside its outline in the x-ray frame (drawn on top of the splat), say how much of it shows.

Usage: python throw_gif.py THROWS.json FRAMES_DIR OUT.gif
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw


def orange(image: Image.Image) -> np.ndarray:
    rgb = np.asarray(image.convert("RGB")).astype(int)
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    return (r > 150) & (g > 60) & (g < 190) & (b < 80) & (r - b > 120)


def main() -> None:
    recorded = json.loads(Path(sys.argv[1]).read_text())
    frames_dir, out = Path(sys.argv[2]), Path(sys.argv[3])
    pictures, durations = [], []
    for index, flight in enumerate(recorded["flights"], start=1):
        times = [frame["t"] for frame in flight["frames"]]
        shown = []
        for n, at in enumerate(times):
            seen = Image.open(frames_dir / f"{index}-{n:03d}-seen.png").convert("RGB")
            xray = Image.open(frames_dir / f"{index}-{n:03d}-xray.png").convert("RGB")
            # The x-ray draws the whole model over everything: all the orange the box could show.
            full = max(int(orange(xray).sum()), 1)
            visible = min(1.0, int(orange(seen).sum()) / full) if full > 1 else float("nan")
            shown.append(visible)
            picture = Image.new("RGB", (seen.width * 2 + 8, seen.height + 28), (30, 30, 30))
            picture.paste(seen, (0, 28))
            picture.paste(xray, (seen.width + 8, 28))
            picture = picture.resize((picture.width * 3 // 4, picture.height * 3 // 4))
            draw = ImageDraw.Draw(picture)
            draw.text((6, 8), f"Throw {index}: {flight['name']}   t = {at:.2f} s   box showing: {visible:.0%}",
                      fill=(255, 255, 255))
            draw.text((picture.width // 2 + 6, 8), "green: where physics has the box", fill=(0, 255, 102))
            pictures.append(picture)
            durations.append(max(20, round(1000 * ((times[n + 1] - at) if n + 1 < len(times) else 1.0))))
        hidden = [f"{times[n]:.2f}" for n, v in enumerate(shown) if v < 0.25]
        on_screen = [v for v in shown if v == v]
        print(f"throw {index} ({flight['name']}): box showing min {min(on_screen):.0%}, "
              f"median {float(np.median(on_screen)):.0%}; mostly hidden (<25%) at t = {', '.join(hidden) or 'never'}")
    pictures[0].save(out, save_all=True, append_images=pictures[1:], duration=durations, loop=0, optimize=True)
    print(f"wrote {out} ({len(pictures)} frames, {out.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
