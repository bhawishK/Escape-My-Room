"""The filming coach's check on the server (#100): Qwen looks at a small frame from the recording.

Every few seconds while the room is filmed, the phone sends a small JPEG of what the camera sees.
Qwen, through the OpenRouter adapter, says whether it is a close-up of a plain surface (which makes
a poor splat room: the tests in #92), whether the floor is in view, and what is in shot. That
gives the prompts the phone can't work out alone: "Step back" and "Show the floor".

Each recording has a spending limit (ESCAPE_ROOM_COACH_BUDGET_USD, default 2 cents, about 50
checks). Any failure is quiet: the answer has no prompt and the phone keeps filming. The key never
leaves the server.
"""

import base64
import binascii
import io
import json
import os
import re
import threading
from collections import OrderedDict
from dataclasses import dataclass
from typing import Literal

from PIL import Image, UnidentifiedImageError
from pydantic import Field, ValidationError

from backend.errors import Refusal
from backend.openrouter import (
    AnswerFormat,
    OpenRouterClient,
    OpenRouterConfig,
    Picture,
    ProviderFailure,
    Reply,
    Unreadable,
    ask,
    say,
    without_thinking,
)
from backend.protocol import WireModel

DEFAULT_BUDGET_USD = 0.02
# A check whose reply reports no cost is counted at about what one costs.
UNPRICED_CHECK_USD = 0.0005
# The frame is small: the phone sends about 320 pixels on its longer side.
MAX_IMAGE_BYTES = 200 * 1024
MAX_IMAGE_SIDE = 512
# Recordings remembered for their spending, newest kept.
REMEMBERED = 64
# The floor is asked for once it has been out of view this many checks running.
FLOOR_MISSED = 2

QUESTION = (
    "This is one frame from a phone video of a room, filmed so that a 3D model of the room can be "
    "made from it. Answer with only a JSON object with these keys:\n"
    '"plain_close_up": true if the camera is so close to a plain, featureless surface (a bare '
    "wall, a door, a curtain) that little else of the room is in the frame;\n"
    '"floor_visible": true if any of the floor is in the frame;\n'
    '"in_shot": a few words naming what is in the frame.'
)
REPAIR = (
    'Answer again with only the JSON object: {"plain_close_up": true or false, '
    '"floor_visible": true or false, "in_shot": "a few words"}.'
)


class FilmingCheck(WireModel):
    plain_close_up: bool
    floor_visible: bool
    in_shot: str = Field(max_length=200)


def read_check(text: str) -> FilmingCheck:
    """Qwen's answer, as the JSON object asked for; raises Unreadable otherwise."""
    found = re.search(r"\{.*\}", without_thinking(text), flags=re.DOTALL)
    if found is None:
        raise Unreadable("the answer has no JSON object")
    try:
        return FilmingCheck.model_validate(json.loads(found.group(0)))
    except (json.JSONDecodeError, ValidationError) as exc:
        raise Unreadable(f"the JSON object is not the one asked for ({exc})") from exc


CHECK_FORMAT = AnswerFormat("filming check", read_check, REPAIR)


class CheckRequest(WireModel):
    recording: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    # Base64 of a JPEG or PNG.
    image: str = Field(max_length=MAX_IMAGE_BYTES * 4 // 3 + 4)


type Status = Literal["ok", "over_budget", "unavailable"]


@dataclass
class _Recording:
    spent_usd: float = 0.0
    floor_missed: int = 0


def picture_of(encoded: str) -> Picture:
    """The request's frame as Qwen is sent it; refuses anything that isn't a small image."""
    try:
        data = base64.b64decode(encoded, validate=True)
        with Image.open(io.BytesIO(data)) as image:
            rgb = image.convert("RGB")
    except (binascii.Error, ValueError, UnidentifiedImageError, OSError) as exc:
        raise Refusal("Send the frame as a base64 JPEG or PNG.", 422) from exc
    rgb.thumbnail((MAX_IMAGE_SIDE, MAX_IMAGE_SIDE))
    encoded_png = io.BytesIO()
    rgb.save(encoded_png, format="PNG")
    return Picture(encoded_png.getvalue())


class FilmingChecks:
    """Checks frames for the recordings being filmed, each within its spending limit."""

    def __init__(self, client: OpenRouterClient, budget_usd: float) -> None:
        self.client = client
        self.budget_usd = budget_usd
        self._recordings: OrderedDict[str, _Recording] = OrderedDict()
        self._lock = threading.Lock()

    @classmethod
    def from_environment(cls) -> "FilmingChecks":
        budget = float(os.environ.get("ESCAPE_ROOM_COACH_BUDGET_USD") or DEFAULT_BUDGET_USD)
        config = OpenRouterConfig.from_environment()
        return cls(OpenRouterClient(config, os.environ.get("OPENROUTER_API_KEY")), budget)

    def _recording(self, name: str) -> _Recording:
        with self._lock:
            recording = self._recordings.pop(name, None) or _Recording()
            self._recordings[name] = recording
            while len(self._recordings) > REMEMBERED:
                self._recordings.popitem(last=False)
            return recording

    def check(self, request: CheckRequest) -> dict[str, str | None]:
        """The prompt for this frame, if any, what is in shot, and whether Qwen was asked."""
        picture = picture_of(request.image)
        recording = self._recording(request.recording)
        if recording.spent_usd >= self.budget_usd:
            return self._answer("over_budget", None, None)

        def count(reply: Reply, _problem: str | None) -> None:
            recording.spent_usd += (
                reply.cost_usd if reply.cost_usd is not None else UNPRICED_CHECK_USD
            )

        try:
            seen = ask(self.client, [say("user", QUESTION, picture)], CHECK_FORMAT, count)
        except (ProviderFailure, Unreadable):
            # Quiet: no prompt, and the phone keeps filming.
            return self._answer("unavailable", None, None)
        recording.floor_missed = 0 if seen.floor_visible else recording.floor_missed + 1
        prompt = None
        if seen.plain_close_up:
            prompt = "Step back to show more of the room"
        elif recording.floor_missed >= FLOOR_MISSED:
            prompt = "Show the floor: tilt the phone down as you go"
        return self._answer("ok", prompt, seen.in_shot)

    @staticmethod
    def _answer(status: Status, prompt: str | None, in_shot: str | None) -> dict[str, str | None]:
        return {"status": status, "prompt": prompt, "in_shot": in_shot}
