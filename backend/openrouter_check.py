"""Send the frozen REST3D-shaped requests to the real OpenRouter once and record what came back.

    OPENROUTER_API_KEY=... python -m backend.openrouter_check path/to/room-photo.jpg

Five requests, each with its answer, tokens, cost and whether it followed the format:

1. object list: the photo and REST3D's object-list prompt;
2. segmentation tool: a first SAM 3 tool call for the first listed object;
3. mask verdict: the photo and a highlighted region, answered Accept or Reject;
4. support: seven images, REST3D's largest support request, answered with one support line;
5. negative format: the object list asked as a paragraph, so the repair path is exercised.

This spends real money from the key (a few cents at most) and is never run by the tests. The
report is written to `data/openrouter-checks/<time>.json` and printed; it contains no key.
"""

import json
import os
import sys
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from PIL import Image, ImageDraw

from backend.openrouter import (
    OBJECT_LIST,
    PROMPTS,
    SUPPORT_ROOTS,
    TOOL_EXAMPLE,
    VERDICT,
    AnswerFormat,
    Message,
    OpenRouterClient,
    OpenRouterConfig,
    Picture,
    ProviderFailure,
    Reply,
    ask,
    say,
    support_format,
    tool_call_format,
)


def highlighted(photo: Path, box: tuple[float, float, float, float], max_side: int) -> Picture:
    """The photo with a translucent coloured box over a fraction of it, standing in for a mask."""
    with Image.open(photo) as source:
        image = source.convert("RGB")
    image.thumbnail((max_side, max_side))
    overlay = Image.new("RGBA", image.size)
    width, height = image.size
    left, top, right, bottom = box
    ImageDraw.Draw(overlay).rectangle(
        (left * width, top * height, right * width, bottom * height), fill=(255, 45, 85, 110)
    )
    composed = Image.alpha_composite(image.convert("RGBA"), overlay).convert("RGB")
    path = Path(os.environ.get("TEMP", "/tmp")) / "openrouter-check-overlay.png"
    composed.save(path)
    return Picture.from_file(path, max_side)


def main(photo: Path) -> int:
    config = OpenRouterConfig.from_environment()
    client = OpenRouterClient(config, os.environ.get("OPENROUTER_API_KEY"))
    scene = Picture.from_file(photo, config.max_image_side)
    requests: list[dict[str, object]] = []
    spent: list[float] = []

    def run[T](name: str, messages: list[Message], answer: AnswerFormat[T]) -> T | None:
        calls: list[dict[str, object]] = []

        def record(reply: Reply, problem: str | None) -> None:
            calls.append({**asdict(reply), "accepted": problem is None, "problem": problem})
            if reply.cost_usd is not None:
                spent.append(reply.cost_usd)

        images = sum(isinstance(part, Picture) for message in messages for part in message.parts)
        entry: dict[str, object] = {"check": name, "images": images, "calls": calls}
        requests.append(entry)
        try:
            value = ask(client, messages, answer, record)
        except ProviderFailure as exc:
            entry["outcome"] = f"failed ({exc.kind}): {exc}"
            return None
        entry["outcome"] = f"accepted: {value}"
        return value

    prompt = (PROMPTS / "list_objects.txt").read_text(encoding="utf-8").strip()
    objects = run("object list", [say("user", scene, prompt)], OBJECT_LIST) or ["table"]
    target = objects[0]
    run(
        "segmentation tool",
        [
            say(
                "user",
                scene,
                f'Find "{target}" in this image with the segmentation tools. '
                f"You MUST end with a <tool> JSON call. Example: {TOOL_EXAMPLE}",
            )
        ],
        tool_call_format(first=True, mask_count=0),
    )
    run(
        "mask verdict",
        [
            say(
                "user",
                scene,
                highlighted(photo, (0.25, 0.3, 0.75, 0.9), config.max_image_side),
                f'Does the highlighted region in the second image cover "{target}"? '
                "Answer <verdict>Accept</verdict> or <verdict>Reject</verdict>.",
            )
        ],
        VERDICT,
    )
    # REST3D's largest support request: the scene, the object and five nearby objects.
    names = [name.replace(" ", "_") for name in objects[:6]]
    names += [f"object_{number}" for number in range(len(names) + 1, 7)]
    child, nearby = names[0], names[1:6]
    regions = [(0.1 * i, 0.2, 0.1 * i + 0.3, 0.8) for i in range(6)]
    parts: list[Picture | str] = [scene, "Full scene image above.\n\n"]
    parts += [
        highlighted(photo, regions[0], config.max_image_side),
        f'Current object: "{child}" (colored mask overlay above)\n\nNearby objects:\n',
    ]
    for name, region in zip(nearby, regions[1:], strict=False):
        parts += [highlighted(photo, region, config.max_image_side), f'Nearby object: "{name}"\n']
    parents = [*SUPPORT_ROOTS, *names]
    allowed = ", ".join(f'"{parent}"' for parent in parents if parent != child)
    parts.append(
        f'\nDetermine what supports or holds "{child}" in this scene.\n'
        f"The parent MUST be one of: {allowed}\n\n"
        'Relations: "on", "inside", "attach", "hang", "on-attach". Types: "fixed", "movable".\n\n'
        f"Output ONLY one line:\n{child} -> parent_name | relation | type\n"
    )
    run("support", [say("user", *parts)], support_format(child, parents))
    run(
        "negative format",
        [say("user", scene, prompt + "\n\nAnswer in one flowing paragraph instead of a list.")],
        OBJECT_LIST,
    )

    report = {
        "checked_at": datetime.now(UTC).isoformat(),
        "photo": photo.name,
        "model": config.model,
        "requests": requests,
        "total_cost_usd": round(sum(spent), 6),
    }
    folder = Path(os.environ.get("ESCAPE_ROOM_DATA_DIR") or "data") / "openrouter-checks"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.json"
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    print(f"\nSaved {path}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(2)
    sys.exit(main(Path(sys.argv[1])))
