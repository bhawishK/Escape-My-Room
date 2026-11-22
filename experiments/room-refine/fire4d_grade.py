"""A stronger look for the generated 4D fire (#220): the flame splats more opaque and more orange.

L4GM learned pale, see-through flames from a video of pale flames on white. This only grades the
generated frames, as a colourist would: splats above the strip (the flames) get more opacity and
a warmer colour; the strip is left as it is. Shape and motion stay as generated.

Usage: python fire4d_grade.py IN_DIR OUT_DIR
"""
import sys
from pathlib import Path

import numpy as np

from splat import read_ply, write_ply

SH0 = 0.28209479177387814
BASE = -0.43          # the strip's underside in L4GM's units (+y up)
FLAMES_FROM = BASE + 0.12

source, out = Path(sys.argv[1]), Path(sys.argv[2])
out.mkdir(parents=True, exist_ok=True)
for path in sorted(source.glob("*.ply")):
    splat = read_ply(path)
    data = splat.data
    flame = splat.xyz[:, 1] > FLAMES_FROM
    data["opacity"][flame] += 1.6  # logit: a faint 0.2 becomes about 0.6
    rgb = np.stack([0.5 + SH0 * data[f"f_dc_{c}"] for c in range(3)], axis=1)
    hot = np.clip(rgb.mean(axis=1, keepdims=True), 0, 1)
    # Pale yellow-white becomes yellow at the core and orange-red at the edges.
    warm = np.concatenate([np.clip(0.55 + 0.6 * hot, 0, 1), np.clip(0.15 + 0.75 * hot ** 1.5, 0, 1), np.clip(0.05 + 0.35 * hot ** 3, 0, 1)], axis=1)
    for c in range(3):
        data[f"f_dc_{c}"][flame] = ((warm[flame, c] - 0.5) / SH0).astype(data[f"f_dc_{c}"].dtype)
    write_ply(out / path.name, splat)
print("graded", len(list(out.glob("*.ply"))), "frames")
