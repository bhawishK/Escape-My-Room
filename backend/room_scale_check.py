"""Suggest a splat room's scale from its doors, show the evidence, and apply the master's choice.

    python -m backend.room_scale_check ROOM_DIR             suggest only
    python -m backend.room_scale_check ROOM_DIR --accept    apply the suggestion
    python -m backend.room_scale_check ROOM_DIR --length L  the doors are L m tall: measured
    python -m backend.room_scale_check ROOM_DIR --keep      keep the assumed scale

Each run except --keep renders eight views round the room and asks Qwen for the doors in each
(about $0.001 a run). Every view is saved with the doors' boxes and measured heights drawn on, with
a report, under `data/room-scale/<time>/`; the report contains no key. Applying rescales the room
with `assets/splat-room/build_room.py --rescale` and records where the scale came from.
"""

import importlib.util
import json
import os
import statistics
import sys
from dataclasses import asdict
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw

from backend.env_file import load_env_file
from backend.openrouter import OpenRouterClient, OpenRouterConfig, ProviderFailure, Reply
from backend.room_scale import DOOR_HEIGHT, Suggestion, suggest_scale

BUILD_ROOM = Path(__file__).resolve().parents[1] / "assets" / "splat-room" / "build_room.py"


def rescale(room: Path, factor: float, source: str) -> None:
    """Rescale with the splat room builder, which owns the room's files."""
    spec = importlib.util.spec_from_file_location("splat_build_room", BUILD_ROOM)
    assert spec and spec.loader
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    builder.rescale(room, factor, source)


def marked(png: bytes, suggestion: Suggestion, number: int) -> bytes:
    """The view with each measured door's box and height drawn on."""
    with Image.open(BytesIO(png)) as source:
        image = source.convert("RGB")
    draw = ImageDraw.Draw(image)
    width, height = image.size
    for item in suggestion.evidence:
        if item.view_number != number:
            continue
        left, top, right, bottom = item.box
        corners = (left * width, top * height, right * width, bottom * height)
        draw.rectangle(corners, outline=(255, 149, 0), width=3)
        draw.text(
            (corners[0] + 4, corners[1] + 4), f"{item.measured.height:.2f} m", fill=(255, 149, 0)
        )
    data = BytesIO()
    image.save(data, format="PNG")
    return data.getvalue()


def main(room: Path, choice: str | None, length: float | None) -> int:
    if choice == "--keep":
        manifest = json.loads((room / "manifest.json").read_text(encoding="utf-8"))
        assumed = manifest.get("splat", {}).get("scale_source") or "as trained"
        rescale(room, 1.0, f"{assumed}; kept by the master")
        return 0
    load_env_file()
    config = OpenRouterConfig.from_environment()
    client = OpenRouterClient(config, os.environ.get("OPENROUTER_API_KEY"))
    calls: list[dict[str, object]] = []
    spent: list[float] = []

    def record(reply: Reply, problem: str | None) -> None:
        calls.append({**asdict(reply), "accepted": problem is None, "problem": problem})
        if reply.cost_usd is not None:
            spent.append(reply.cost_usd)

    try:
        suggestion = suggest_scale(room, client, record)
    except ProviderFailure as exc:
        print(f"Could not ask Qwen ({exc.kind}): {exc}")
        return 1

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    folder = Path(os.environ.get("ESCAPE_ROOM_DATA_DIR") or "data") / "room-scale" / stamp
    folder.mkdir(parents=True, exist_ok=True)
    for number, png in enumerate(suggestion.pngs, start=1):
        (folder / f"view-{number}.png").write_bytes(marked(png, suggestion, number))
    heights = [item.measured.height for item in suggestion.evidence]
    report = {
        "checked_at": datetime.now(UTC).isoformat(),
        "room": str(room),
        "model": config.model,
        "typical_door_height": suggestion.typical_height,
        "doors": [
            {
                "image": f"view-{item.view_number}.png",
                "box": item.box,
                "measured_height": round(item.measured.height, 3),
                "depth": round(item.measured.depth, 2),
                "splats": item.measured.splats,
            }
            for item in suggestion.evidence
        ],
        "skipped": suggestion.skipped,
        "suggested_factor": suggestion.factor,
        "calls": calls,
        "total_cost_usd": round(sum(spent), 6),
    }
    (folder / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "calls"}, indent=2))
    print(f"\nViews and report saved in {folder}")

    if suggestion.factor is None:
        print("No door could be measured; the scale stays as it is.")
        return 1
    if length is not None:
        factor = length / statistics.median(heights)
        source = f"door height {length} m, measured by the master"
    elif choice == "--accept":
        factor = suggestion.factor
        source = f"door height {DOOR_HEIGHT} m (typical), from {len(heights)} doors Qwen found"
    else:
        print(
            f"\nSuggested: make the room x{suggestion.factor:.3f} larger. Check the views, "
            "then run again with --accept, --length <the doors' measured height>, or --keep."
        )
        return 0
    rescale(room, factor, source)
    return 0


if __name__ == "__main__":
    arguments = sys.argv[1:]
    if not arguments or arguments[1:2] not in ([], ["--accept"], ["--keep"], ["--length"]):
        print(__doc__)
        sys.exit(2)
    given = float(arguments[2]) if arguments[1:2] == ["--length"] else None
    sys.exit(main(Path(arguments[0]), arguments[1] if len(arguments) > 1 else None, given))
