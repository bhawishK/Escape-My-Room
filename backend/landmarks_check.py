"""The landmark spike (#110) on a real splat room: build its landmark map, then measure how well
Qwen's boxes locate phone-like views rendered at known places.

    python -m backend.landmarks_check build ROOM_DIR [--labels door,cupboard,...]
    python -m backend.landmarks_check evaluate ROOM_DIR

`build` asks Qwen for the labelled objects in eight views round each of a few spots along the
walk, and writes `landmarks.json` into the room. `evaluate` renders phone views (portrait, held
1.4 m up and tilted down) along the walk, locates each from the map, and reports the errors.
Each saves its views with the boxes drawn on, and a report, under `data/landmarks/<time>/`; the
report contains no key. Both spend real money from the key: about $0.0001 a view.
"""

import argparse
import json
import math
import os
import statistics
import sys
from dataclasses import asdict
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw

from backend.boxes import Box
from backend.env_file import load_env_file
from backend.landmarks import build_landmarks, load_landmarks, locate, pose_view, save_landmarks
from backend.openrouter import OpenRouterClient, OpenRouterConfig, Reply
from backend.room_scale import views_round
from backend.room_views import render_views

# A mirror is left out: the splats behind it are the reflected room, so its depth is wrong.
LABELS = ["door", "cupboard", "waste bin", "sink"]
# The hallway runs from the origin along (-1, -1): its waste bin and door stand on one wall and its
# cupboard on the other, about 1.4 m apart (from the first landmark map, 27 October 2026).
MAP_SPOTS = [(0.0, 0.0), (-1.0, -1.0), (-2.0, -2.0)]
# A phone held upright: a portrait view, 1.4 m up, tilted 15 degrees down.
PHONE_HEIGHT, PHONE_PITCH = 1.4, math.radians(-15)
PHONE_FOV, PHONE_SIZE = 65.0, (480, 640)
# Places along the hallway walk, in room metres, and the headings looked in from each.
SPOTS = [(0.3, 0.3), (-0.5, -0.5), (-1.2, -1.2), (-1.8, -1.8)]
# Down the hallway, 30 degrees either side of it, and back the way they came.
HEADINGS = [math.radians(degrees) for degrees in (-75, -45, -15, 135)]


def drawn(png: bytes, boxes: list[tuple[str, Box]]) -> bytes:
    with Image.open(BytesIO(png)) as source:
        image = source.convert("RGB")
    draw = ImageDraw.Draw(image)
    width, height = image.size
    for label, (left, top, right, bottom) in boxes:
        corners = (left * width, top * height, right * width, bottom * height)
        draw.rectangle(corners, outline=(255, 149, 0), width=3)
        draw.text((corners[0] + 4, corners[1] + 4), label, fill=(255, 149, 0))
    data = BytesIO()
    image.save(data, format="PNG")
    return data.getvalue()


class Spend:
    """Every reply's record and cost, for the report."""

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.cost = 0.0
        self.seconds = 0.0

    def record(self, reply: Reply, problem: str | None) -> None:
        self.calls.append({**asdict(reply), "accepted": problem is None, "problem": problem})
        self.cost += reply.cost_usd or 0.0
        self.seconds += reply.latency_seconds


def build(
    room: Path, labels: list[str], client: OpenRouterClient, folder: Path
) -> dict[str, object]:
    spend = Spend()
    built = build_landmarks(room, client, spend.record, labels, views_round(MAP_SPOTS))
    save_landmarks(room, built.landmarks)
    for number, png in enumerate(built.pngs, start=1):
        boxes = [(s.label, s.box) for s in built.sightings if s.view_number == number]
        (folder / f"map-view-{number}.png").write_bytes(drawn(png, boxes))
    return {
        "labels": labels,
        "landmarks": [asdict(mark) for mark in built.landmarks],
        "sightings": [asdict(sighting) for sighting in built.sightings],
        "views": len(built.views),
        "cost_usd": round(spend.cost, 6),
        "calls": spend.calls,
    }


def evaluate(room: Path, client: OpenRouterClient, folder: Path) -> dict[str, object]:
    # A landmark seen only once may be a reflection or a mistake (a sink placed through the mirror).
    landmarks = [mark for mark in load_landmarks(room) if mark.seen >= 2]
    truths = [((x, PHONE_HEIGHT, z), heading) for x, z in SPOTS for heading in HEADINGS]
    views = [
        pose_view(position, heading, PHONE_PITCH, PHONE_FOV, *PHONE_SIZE)
        for position, heading in truths
    ]
    shots = render_views(room, views)
    results: list[dict[str, object]] = []
    spend = Spend()
    for number, (shot, (position, heading)) in enumerate(zip(shots, truths, strict=True), start=1):
        before_cost, before_seconds = spend.cost, spend.seconds
        located = locate(client, spend.record, shot, landmarks, PHONE_PITCH)
        (folder / f"test-view-{number}.png").write_bytes(drawn(shot.png, located.sightings))
        result: dict[str, object] = {
            "image": f"test-view-{number}.png",
            "true_position": position,
            "true_heading_deg": round(math.degrees(heading), 1),
            "sighted": [label for label, _ in located.sightings],
            "latency_seconds": round(spend.seconds - before_seconds, 2),
            "cost_usd": round(spend.cost - before_cost, 6),
            "fix": None,
        }
        if located.fix:
            fix = located.fix
            turn = math.degrees(
                math.atan2(math.sin(fix.heading - heading), math.cos(fix.heading - heading))
            )
            result["fix"] = {
                "position": [round(c, 3) for c in fix.position],
                "heading_deg": round(math.degrees(fix.heading), 1),
                "landmarks": fix.landmarks,
                "rms": round(fix.rms, 4),
                "floor_error_m": round(math.dist(fix.position[::2], position[::2]), 3),
                "height_error_m": round(fix.position[1] - position[1], 3),
                "heading_error_deg": round(turn, 1),
            }
        results.append(result)
    fixed = [r["fix"] for r in results if r["fix"]]
    errors = sorted(float(f["floor_error_m"]) for f in fixed)  # type: ignore[index]
    return {
        "views": len(results),
        "with_two_or_more_sighted": sum(len(r["sighted"]) >= 2 for r in results),  # type: ignore[arg-type]
        "fixed": len(fixed),
        "floor_error_m": {
            "median": statistics.median(errors) if errors else None,
            "p90": errors[min(len(errors) - 1, int(len(errors) * 0.9))] if errors else None,
            "max": errors[-1] if errors else None,
        },
        "cost_usd": round(spend.cost, 6),
        "latency_seconds_median": statistics.median(
            float(r["latency_seconds"])
            for r in results  # type: ignore[arg-type]
        ),
        "results": results,
        "calls": spend.calls,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("step", choices=["build", "evaluate"])
    parser.add_argument("room", type=Path)
    parser.add_argument("--labels", default=",".join(LABELS))
    arguments = parser.parse_args()
    load_env_file()
    config = OpenRouterConfig.from_environment()
    client = OpenRouterClient(config, os.environ.get("OPENROUTER_API_KEY"))
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    folder = (
        Path(os.environ.get("ESCAPE_ROOM_DATA_DIR") or "data")
        / "landmarks"
        / f"{stamp}-{arguments.step}"
    )
    folder.mkdir(parents=True, exist_ok=True)
    if arguments.step == "build":
        report = build(arguments.room, arguments.labels.split(","), client, folder)
    else:
        report = evaluate(arguments.room, client, folder)
    report = {
        "checked_at": datetime.now(UTC).isoformat(),
        "room": str(arguments.room),
        "model": config.model,
        **report,
    }
    (folder / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                key: value
                for key, value in report.items()
                if key not in ("calls", "results", "sightings")
            },
            indent=2,
        )
    )
    print(f"\nSaved {folder}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
