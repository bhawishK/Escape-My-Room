"""A room from a retrained splat, placed as a calibrated room already is (#209).

Retraining reuses the reconstruction's frames, COLMAP model and levelling, so the new splat is in
the same frame as the old one, and the old room's placement (floor on the real floor, scale from
the camera height, #206) is right for it unchanged. This copies that room's manifest and
entities, and takes the new splat, its phone copy, its positioning map and report.

Usage: python make_room.py RECONSTRUCTION_DIR PLACED_ROOM_DIR OUT_DIR [ROOM_VERSION]
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def build_room_module():
    spec = importlib.util.spec_from_file_location("build_room", ROOT / "assets" / "splat-room" / "build_room.py")
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def main() -> None:
    reconstruction, placed, out = (Path(arg) for arg in sys.argv[1:4])
    version = int(sys.argv[4]) if len(sys.argv) > 4 else None
    out.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((placed / "manifest.json").read_text())
    if version is not None:
        manifest["room_version"] = version
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2))
    for entity in manifest["entities"]:
        shutil.copy2(placed / entity["asset"], out / entity["asset"])
    shutil.copy2(reconstruction / "room.ply", out / "room.ply")
    shutil.copy2(reconstruction / "report.json", out / "report.json")
    if (reconstruction / "vps").is_dir():
        shutil.rmtree(out / "vps", ignore_errors=True)
        shutil.copytree(reconstruction / "vps", out / "vps")
    build = build_room_module()
    build.write_phone_splat(out / "room.ply", out / build.PHONE_FILE, build.PHONE_SPLATS)

    from backend.prepared_room import load_prepared_room

    room = load_prepared_room(out)
    print(f"room {room.room_version} accepted: {[entity.id for entity in room.entities]}")


if __name__ == "__main__":
    main()
