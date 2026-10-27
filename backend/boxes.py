"""Qwen's object boxes: a JSON list like `[{"label": "door", "bbox_2d": [x1, y1, x2, y2]}]`, with
coordinates from 0 to 1000 across the image, sometimes in a ```json code fence."""

import json
import re
from collections.abc import Sequence
from typing import cast

from backend.openrouter import AnswerFormat, Unreadable, without_thinking

# Fractions of a view: left, top, right, bottom.
type Box = tuple[float, float, float, float]


def read_boxes(text: str, labels: Sequence[str]) -> list[tuple[str, Box]]:
    """Each box with its label, one of `labels` (as asked, whatever its case), as fractions."""
    answer = re.sub(r"^```(?:json)?\s*|\s*```$", "", without_thinking(text).strip())
    try:
        items: object = json.loads(answer)
    except json.JSONDecodeError as exc:
        raise Unreadable("the answer is not a JSON list") from exc
    if not isinstance(items, list):
        raise Unreadable("the answer is not a JSON list")
    asked = {label.casefold(): label for label in labels}
    boxes: list[tuple[str, Box]] = []
    for item in cast(list[object], items):
        fields = cast(dict[str, object], item) if isinstance(item, dict) else {}
        label = asked.get(str(fields.get("label", "")).casefold())
        if label is None:
            raise Unreadable(f"every item's label must be one of: {', '.join(labels)}")
        edges = fields.get("bbox_2d")
        numbers = [
            float(edge)
            for edge in (cast(list[object], edges) if isinstance(edges, list) else [])
            if isinstance(edge, int | float) and 0 <= edge <= 1000
        ]
        if len(numbers) != 4 or len(cast(list[object], edges)) != 4:
            raise Unreadable("bbox_2d must be four numbers from 0 to 1000")
        left, top, right, bottom = (edge / 1000 for edge in numbers)
        if left >= right or top >= bottom:
            raise Unreadable("bbox_2d must be [x1, y1, x2, y2] with x1 < x2 and y1 < y2")
        boxes.append((label, (left, top, right, bottom)))
    return boxes


def find_objects(labels: Sequence[str]) -> str:
    """The question that asks for the boxes of these objects."""
    names = ", ".join(labels)
    return (
        f"Find every one of these objects in this image: {names}. "
        f'Output ONLY a JSON list like [{{"label": "{labels[0]}", "bbox_2d": [x1, y1, x2, y2]}}], '
        "with coordinates from 0 to 1000 relative to the image width and height, and each label "
        f"exactly one of: {names}. Output [] if none of them is in view."
    )


def box_format(labels: Sequence[str]) -> AnswerFormat[list[tuple[str, Box]]]:
    names = ", ".join(labels)
    return AnswerFormat(
        "object boxes",
        lambda text: read_boxes(text, labels),
        "Your answer did not follow the format. Output ONLY a JSON list like "
        f'[{{"label": "{labels[0]}", "bbox_2d": [x1, y1, x2, y2]}}] with coordinates from 0 to '
        f"1000 and each label exactly one of: {names}; or [] if none is in view.",
    )
