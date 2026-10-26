"""Render views of a prepared splat room and ask Qwen about each one, recording what came back.

    python -m backend.room_views_check ROOM_DIR QUESTION VIEW [VIEW ...]

Each VIEW is `x,y,z@x,y,z`: where the camera stands and the point it looks at, in room metres.
Or `orbit:x,y,z:distance:height:count[:picks]` for views round a target (`orbit` in
`backend/room_views.py`), keeping only the comma-separated picks if given, counted from 1.

The key comes from OPENROUTER_API_KEY, in the environment or in `.env`. This spends real money
from the key (about a tenth of a cent a view) and is never run by the tests. The views and a report
with each answer, its tokens and cost, and the render times are written to
`data/room-views/<time>/`; the report contains no key.
"""

import json
import os
import sys
import time
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from backend.env_file import load_env_file
from backend.openrouter import OpenRouterClient, OpenRouterConfig, ProviderFailure, Reply
from backend.room_views import (
    SHORT_ANSWER,
    SHORT_ANSWER_REQUEST,
    View,
    ask_about_views,
    orbit,
    render_views,
)


def point(text: str) -> tuple[float, float, float]:
    x, y, z = (float(part) for part in text.split(","))
    return x, y, z


def parse_views(arguments: list[str]) -> list[View]:
    views: list[View] = []
    for argument in arguments:
        if argument.startswith("orbit:"):
            _, target, distance, height, count, *picks = argument.split(":")
            around = orbit(point(target), float(distance), int(count), float(height))
            chosen = [int(pick) for pick in picks[0].split(",")] if picks else []
            views += [around[pick - 1] for pick in chosen] if chosen else around
        else:
            position, look_at = argument.split("@")
            views.append(View(position=point(position), look_at=point(look_at)))
    return views


def main(room: Path, question: str, arguments: list[str]) -> int:
    load_env_file()
    config = OpenRouterConfig.from_environment()
    client = OpenRouterClient(config, os.environ.get("OPENROUTER_API_KEY"))
    views = parse_views(arguments)
    started = time.perf_counter()
    rendered = render_views(room, views)
    render_seconds = time.perf_counter() - started

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    folder = Path(os.environ.get("ESCAPE_ROOM_DATA_DIR") or "data") / "room-views" / stamp
    folder.mkdir(parents=True, exist_ok=True)
    entries: list[dict[str, object]] = []
    spent: list[float] = []
    for number, view in enumerate(rendered, start=1):
        (folder / f"view-{number}.png").write_bytes(view.png)
        calls: list[dict[str, object]] = []

        def record(reply: Reply, problem: str | None, calls: list[dict[str, object]] = calls):
            calls.append({**asdict(reply), "accepted": problem is None, "problem": problem})
            if reply.cost_usd is not None:
                spent.append(reply.cost_usd)

        entry: dict[str, object] = {
            "image": f"view-{number}.png",
            "view": asdict(view.view),
            "render_seconds": round(view.seconds, 3),
            "calls": calls,
        }
        entries.append(entry)
        try:
            asked = f"{question} {SHORT_ANSWER_REQUEST}"
            entry["answer"] = ask_about_views(client, [view], asked, SHORT_ANSWER, record)
        except ProviderFailure as exc:
            entry["answer"] = None
            entry["failure"] = f"{exc.kind}: {exc}"

    report = {
        "checked_at": datetime.now(UTC).isoformat(),
        "room": str(room),
        "question": question,
        "model": config.model,
        # Starting the browser and loading the splat, then drawing every view.
        "render_seconds_total": round(render_seconds, 3),
        "views": entries,
        "total_cost_usd": round(sum(spent), 6),
    }
    (folder / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    print(f"\nSaved {folder}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 4:
        print(__doc__)
        sys.exit(2)
    sys.exit(main(Path(sys.argv[1]), sys.argv[2], sys.argv[3:]))
