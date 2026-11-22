"""Writes L4GM's infer_4d_ply.py (#226): its infer_4d.py, also saving each frame's splat.

L4GM's infer_4d.py only saves rendered videos; the hazard needs the 3D splat of every frame. This
adds one line in the loop over frames that saves them, as spike #220 did by hand.

Usage: python ply_writer.py L4GM_DIR
"""

import sys
from pathlib import Path

folder = Path(sys.argv[1])
source = (folder / "infer_4d.py").read_text(encoding="utf-8")
dump = "            for sv_name, gaussians_all_frame in zip_dump:\n"
loop = "                for t in range(gaussians_all_frame.shape[1]):\n"
save = (
    "                    model.gs.save_ply(gaussians_all_frame[:, t], os.path.join(opt.workspace, "
    'f"{name}_{sv_name}_{t:03d}.ply"))  # Escape My Room #226\n'
)
if source.count(dump) != 1:
    sys.exit("infer_4d.py has changed: its frame loop wasn't found, so the splats can't be saved.")
at = source.index(loop, source.index(dump)) + len(loop)
(folder / "infer_4d_ply.py").write_text(source[:at] + save + source[at:], encoding="utf-8")
print("wrote", folder / "infer_4d_ply.py")
