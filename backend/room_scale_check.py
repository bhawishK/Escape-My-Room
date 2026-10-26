"""Suggest a splat room's scale from its doors, show the evidence, and apply the master's choice.

    python -m backend.room_scale_check suggest ROOM_DIR
    python -m backend.room_scale_check accept ROOM_DIR
    python -m backend.room_scale_check measured ROOM_DIR HEIGHT --door N
    python -m backend.room_scale_check keep ROOM_DIR

`suggest` renders eight views round where the room was filmed and asks Qwen for the doors in each
(under $0.001 a run). Every view is saved with the doors drawn on, numbered, measured ones in orange
with their height and skipped ones in grey, with a report, under `data/room-scale/<time>/`; the
report contains no key. Nothing in the room changes.

The master then looks at the views and chooses, without asking Qwen again:
- `accept` the latest suggestion for the room;
- `measured`: door N of that suggestion is really HEIGHT metres tall, measured with a tape;
- `keep` the scale as it is, which is only noted in the manifest.
`accept` and `measured` rescale the room with `assets/splat-room/build_room.py`, which records
where the scale came from.
"""

import argparse
import importlib.util
import json
import os
import sys
from dataclasses import asdict
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

from backend.env_file import load_env_file
from backend.openrouter import OpenRouterClient, OpenRouterConfig, ProviderFailure, Reply
from backend.room_scale import Suggestion, suggest_scale

BUILD_ROOM = Path(__file__).resolve().parents[1] / "assets" / "splat-room" / "build_room.py"
MEASURED, SKIPPED = (255, 149, 0), (174, 174, 178)


def room_builder() -> Any:
    """The splat room builder, which owns the room's files."""
    spec = importlib.util.spec_from_file_location("splat_build_room", BUILD_ROOM)
    assert spec and spec.loader
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    return builder


def reports() -> Path:
    return Path(os.environ.get("ESCAPE_ROOM_DATA_DIR") or "data") / "room-scale"


def marked(suggestion: Suggestion, number: int) -> bytes:
    """View `number` with its doors drawn on: numbered, with their height or why they were not
    measured."""
    with Image.open(BytesIO(suggestion.pngs[number - 1])) as source:
        image = source.convert("RGB")
    draw = ImageDraw.Draw(image)
    width, height = image.size
    for door_number, door in enumerate(suggestion.doors, start=1):
        if door.view_number != number:
            continue
        left, top, right, bottom = door.box
        corners = (left * width, top * height, right * width, bottom * height)
        colour = SKIPPED if door.skipped else MEASURED
        label = f"#{door_number} " + (
            "skipped" if door.skipped or door.measured is None else f"{door.measured.height:.2f} m"
        )
        draw.rectangle(corners, outline=colour, width=3)
        draw.text((corners[0] + 4, corners[1] + 4), label, fill=colour)
    data = BytesIO()
    image.save(data, format="PNG")
    return data.getvalue()


def suggest(room: Path) -> int:
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
    folder = reports() / datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    folder.mkdir(parents=True, exist_ok=True)
    for number in range(1, len(suggestion.pngs) + 1):
        (folder / f"view-{number}.png").write_bytes(marked(suggestion, number))
    report = {
        "checked_at": datetime.now(UTC).isoformat(),
        "room": str(room.resolve()),
        "model": config.model,
        "typical_door_height": suggestion.typical_height,
        "doors": [
            {
                "door": number,
                "image": f"view-{door.view_number}.png",
                "box": door.box,
                "measured_height": door.measured and round(door.measured.height, 3),
                "depth": door.measured and round(door.measured.depth, 2),
                "splats": door.measured and door.measured.splats,
                "skipped": door.skipped,
            }
            for number, door in enumerate(suggestion.doors, start=1)
        ],
        "suggested_factor": suggestion.factor,
        "calls": calls,
        "total_cost_usd": round(sum(spent), 6),
    }
    (folder / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "calls"}, indent=2))
    print(f"\nViews and report saved in {folder}")
    if suggestion.factor is None:
        print("No door could be measured. Measure a door's height and run `measured` with it.")
        return 1
    print(
        f"\nSuggested: make the room x{suggestion.factor:.3f} larger. Check the views, then run "
        "`accept`, `measured HEIGHT --door N` or `keep`."
    )
    return 0


def latest_report(room: Path) -> tuple[Path, dict[str, Any]]:
    """The newest suggestion saved for this room, and where it is."""
    for path in sorted(reports().glob("*/report.json"), reverse=True):
        report = json.loads(path.read_text(encoding="utf-8"))
        if report.get("room") == str(room.resolve()):
            return path.parent, report
    raise SystemExit(f"No suggestion is saved for {room}: run `suggest` first.")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    steps = parser.add_subparsers(dest="step", required=True)
    for step in ("suggest", "accept", "keep"):
        steps.add_parser(step).add_argument("room", type=Path)
    measured = steps.add_parser("measured")
    measured.add_argument("room", type=Path)
    measured.add_argument("height", type=float, help="the door's real height, in metres")
    measured.add_argument("--door", type=int, required=True, help="its number in the views")
    arguments = parser.parse_args()
    room: Path = arguments.room
    if arguments.step == "suggest":
        return suggest(room)
    if arguments.step == "keep":
        room_builder().keep_scale(room)
        return 0
    folder, report = latest_report(room)
    if arguments.step == "accept":
        if report["suggested_factor"] is None:
            raise SystemExit("That suggestion measured no door: run `measured` instead.")
        counted = sum(door["skipped"] is None for door in report["doors"])
        factor = report["suggested_factor"]
        source = (
            f"door height {report['typical_door_height']} m (typical), "
            f"from {counted} doors Qwen found ({folder.name})"
        )
    else:
        doors = {door["door"]: door for door in report["doors"]}
        door = doors.get(arguments.door)
        if door is None or door["measured_height"] is None:
            raise SystemExit(f"Door #{arguments.door} was not measured in {folder.name}.")
        factor = arguments.height / door["measured_height"]
        source = (
            f"door height {arguments.height} m, measured by the master (door #{arguments.door} "
            f"in {folder.name})"
        )
    room_builder().rescale(room, factor, source)
    return 0


if __name__ == "__main__":
    sys.exit(main())
