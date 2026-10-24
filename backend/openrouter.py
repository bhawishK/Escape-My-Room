"""Qwen through OpenRouter: one chat request at a time, and REST3D's four answer formats.

`OpenRouterClient.complete` sends messages to OpenRouter's OpenAI-compatible chat completions API
in their exact order, images included, and turns every HTTP failure into a `ProviderFailure` the
user can act on. It never retries a failed request: a spending limit or an outage is reported,
not looped on. The key comes from server settings only and appears in no record.

`ask` checks each answer against one of the formats REST3D and SAM 3 expect, and on a bad answer
asks again with the same repair message they use, a bounded number of times. The formats follow
REST3D at commit 9d68330 and SAM 3 at commit f1647e8; see `backend/prompts/NOTICE.md`.
"""

import base64
import io
import json
import os
import re
import textwrap
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, cast

from PIL import Image
from pydantic import BaseModel, ConfigDict, ValidationError

from backend.protocol import WireModel

PROMPTS = Path(__file__).with_name("prompts")
DEFAULT_URL = "https://openrouter.ai/api/v1"
DEFAULT_MODEL = "qwen/qwen3-vl-8b-instruct"

type FailureKind = Literal["configuration", "resource", "provider", "inference"]
type Role = Literal["system", "user", "assistant"]


class OpenRouterConfig(WireModel):
    """The OpenRouter settings a job records; the key is deliberately not one of them."""

    worker: Literal["openrouter"]
    version: str
    url: str
    model: str
    # The overview is scaled down so its longer side is at most this, to bound image tokens.
    max_image_side: int
    max_images: int
    max_output_tokens: int
    max_repairs: int
    timeout_seconds: float

    @classmethod
    def from_environment(cls) -> "OpenRouterConfig":
        def setting(name: str, default: str) -> str:
            return os.environ.get(f"ESCAPE_ROOM_OPENROUTER_{name}") or default

        return cls(
            worker="openrouter",
            version="openrouter-1",
            url=setting("URL", DEFAULT_URL).rstrip("/"),
            model=setting("MODEL", DEFAULT_MODEL),
            max_image_side=int(setting("MAX_IMAGE_SIDE", "1280")),
            max_images=int(setting("MAX_IMAGES", "7")),
            max_output_tokens=int(setting("MAX_OUTPUT_TOKENS", "2048")),
            max_repairs=int(setting("MAX_REPAIRS", "2")),
            timeout_seconds=float(setting("TIMEOUT_SECONDS", "120")),
        )


class ProviderFailure(Exception):
    """A request or its answers failed; the message is shown to the user."""

    def __init__(self, kind: FailureKind, message: str) -> None:
        super().__init__(message)
        self.kind: FailureKind = kind


@dataclass(frozen=True)
class Text:
    text: str


@dataclass(frozen=True)
class Picture:
    png: bytes

    @classmethod
    def from_file(cls, path: Path, max_side: int) -> "Picture":
        """The image as RGB PNG, scaled down so neither side exceeds `max_side`."""
        with Image.open(path) as image:
            rgb = image.convert("RGB")
        rgb.thumbnail((max_side, max_side))
        data = io.BytesIO()
        rgb.save(data, format="PNG")
        return cls(data.getvalue())


@dataclass(frozen=True)
class Message:
    role: Role
    parts: tuple[Text | Picture, ...]


def say(role: Role, *parts: Text | Picture | str) -> Message:
    return Message(role, tuple(Text(part) if isinstance(part, str) else part for part in parts))


@dataclass(frozen=True)
class Reply:
    text: str
    finish_reason: str | None
    model: str | None
    provider: str | None
    generation_id: str | None
    prompt_tokens: int | None
    completion_tokens: int | None
    cost_usd: float | None
    latency_seconds: float


class OpenRouterClient:
    def __init__(self, config: OpenRouterConfig, api_key: str | None) -> None:
        self.config = config
        self._api_key = api_key

    def complete(self, messages: list[Message]) -> Reply:
        if not self._api_key:
            raise ProviderFailure(
                "configuration",
                "The server has no OpenRouter key. Set OPENROUTER_API_KEY and restart the service.",
            )
        images = sum(isinstance(part, Picture) for message in messages for part in message.parts)
        if images > self.config.max_images:
            raise ProviderFailure(
                "configuration",
                f"This request has {images} images, more than the {self.config.max_images} "
                "the server allows (ESCAPE_ROOM_OPENROUTER_MAX_IMAGES).",
            )
        payload = {
            "model": self.config.model,
            "messages": [_wire(message) for message in messages],
            "max_tokens": self.config.max_output_tokens,
            "temperature": 0,
            # Asks OpenRouter to report the cost of the request with its token counts.
            "usage": {"include": True},
        }
        request = urllib.request.Request(
            f"{self.config.url}/chat/completions",
            data=json.dumps(payload).encode(),
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
                "X-Title": "Escape My Room",
            },
            method="POST",
        )
        started = time.monotonic()
        try:
            with urllib.request.urlopen(request, timeout=self.config.timeout_seconds) as response:
                body = _Completion.model_validate_json(response.read())
        except urllib.error.HTTPError as exc:
            raise _http_failure(exc.code, _error_message(exc.read())) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise ProviderFailure(
                "provider", f"OpenRouter could not be reached ({_reason(exc)}). Try again later."
            ) from exc
        except ValidationError as exc:
            raise ProviderFailure(
                "provider", "OpenRouter sent an answer it could not read."
            ) from exc
        latency = round(time.monotonic() - started, 3)
        # OpenRouter can report an upstream failure inside a 200 response.
        if body.error is not None:
            code = body.error.code if isinstance(body.error.code, int) else 502
            raise _http_failure(code, body.error.message)
        if not body.choices:
            raise ProviderFailure("provider", "OpenRouter sent an answer with no choices.")
        choice, usage = body.choices[0], body.usage or _Usage()
        return Reply(
            text=choice.message.content or "",
            finish_reason=choice.finish_reason,
            model=body.model,
            provider=body.provider,
            generation_id=body.id,
            prompt_tokens=usage.prompt_tokens,
            completion_tokens=usage.completion_tokens,
            cost_usd=usage.cost,
            latency_seconds=latency,
        )


class _Lenient(BaseModel):
    """OpenRouter's JSON, reading only the fields used here."""

    model_config = ConfigDict(extra="ignore")


class _ErrorBody(_Lenient):
    code: int | str | None = None
    message: str | None = None


class _ErrorEnvelope(_Lenient):
    error: _ErrorBody | None = None


class _ChoiceMessage(_Lenient):
    content: str | None = None


class _Choice(_Lenient):
    finish_reason: str | None = None
    message: _ChoiceMessage = _ChoiceMessage()


class _Usage(_Lenient):
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    cost: float | None = None


class _Completion(_ErrorEnvelope):
    id: str | None = None
    model: str | None = None
    provider: str | None = None
    choices: list[_Choice] = []
    usage: _Usage | None = None


def _wire(message: Message) -> dict[str, Any]:
    content: list[dict[str, Any]] = []
    for part in message.parts:
        if isinstance(part, Text):
            content.append({"type": "text", "text": part.text})
        else:
            url = "data:image/png;base64," + base64.b64encode(part.png).decode()
            content.append({"type": "image_url", "image_url": {"url": url}})
    return {"role": message.role, "content": content}


def _error_message(raw: bytes) -> str | None:
    try:
        error = _ErrorEnvelope.model_validate_json(raw).error
    except ValidationError:
        return None
    return error.message if error is not None else None


def _reason(exc: BaseException) -> str:
    reason = getattr(exc, "reason", None) or exc
    return str(reason) or type(exc).__name__


def _http_failure(status: int, message: str | None) -> ProviderFailure:
    detail = f" ({message})" if message else ""
    if status == 401:
        return ProviderFailure(
            "configuration", "OpenRouter refused the server's key. Check OPENROUTER_API_KEY."
        )
    if status == 402:
        return ProviderFailure(
            "resource",
            "The OpenRouter key has reached its spending limit. "
            "Ask for the limit to be raised, then submit again.",
        )
    if status == 429:
        return ProviderFailure(
            "provider",
            "OpenRouter is limiting requests right now. Wait a minute, then submit again.",
        )
    if status in (408, 502, 503, 504):
        return ProviderFailure(
            "provider", f"The model is unavailable right now{detail}. Try again later."
        )
    return ProviderFailure("provider", f"OpenRouter refused the request ({status}){detail}.")


class Unreadable(Exception):
    """An answer does not follow the expected format; the message says how."""


@dataclass(frozen=True)
class AnswerFormat[T]:
    """How to read one kind of answer, and what to ask when an answer is unreadable."""

    name: str
    read: Callable[[str], T]
    repair: str


def ask[T](
    client: OpenRouterClient,
    messages: list[Message],
    answer: AnswerFormat[T],
    on_reply: Callable[[Reply, str | None], None],
) -> T:
    """The first answer that follows `answer`'s format, repairing a bounded number of times.

    `on_reply` sees every reply with the reason it was unreadable, or None when it was accepted.
    """
    conversation = list(messages)
    attempts = client.config.max_repairs + 1
    problem = "no answer was requested"
    for _ in range(attempts):
        reply = client.complete(conversation)
        try:
            if reply.finish_reason == "length":
                raise Unreadable("the answer was cut off")
            value = answer.read(reply.text)
        except Unreadable as exc:
            problem = str(exc)
            on_reply(reply, problem)
            conversation += [say("assistant", reply.text), say("user", answer.repair)]
            continue
        on_reply(reply, None)
        return value
    raise ProviderFailure(
        "inference",
        f"Qwen's answers did not follow the {answer.name} format after {attempts} attempts; "
        f"the last one: {problem}.",
    )


def _without_thinking(text: str) -> str:
    """The answer without <think> blocks, closed or cut off, as REST3D strips them."""
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    if "<think>" in text:
        text = text[: text.index("<think>")]
    return text.strip()


# REST3D's object list: one name per line, after stripping numbering and bullets.
MAX_OBJECTS = 60
MAX_OBJECT_NAME = 100


def read_object_list(text: str) -> list[str]:
    names: list[str] = []
    for line in _without_thinking(text).splitlines():
        name = re.sub(r"^[-*]\s*", "", re.sub(r"^\d+[.)]\s*", "", line.strip())).strip()
        if not name:
            continue
        if len(name) >= MAX_OBJECT_NAME or name.endswith(":"):
            raise Unreadable(
                f'"{textwrap.shorten(name, 60, placeholder="…")}" is not an object name'
            )
        # Object names never end like a sentence; an answer in prose instead of a list does.
        if name.endswith((".", "!", "?")):
            raise Unreadable(f'"{textwrap.shorten(name, 60, placeholder="…")}" reads as a sentence')
        if name.casefold() in (seen.casefold() for seen in names):
            raise Unreadable(f'"{name}" is listed twice')
        names.append(name)
    if not names:
        raise Unreadable("the answer lists no objects")
    if len(names) > MAX_OBJECTS:
        raise Unreadable(f"the answer lists {len(names)} objects, more than {MAX_OBJECTS}")
    return names


OBJECT_LIST = AnswerFormat(
    "object list",
    read_object_list,
    "Your answer did not follow the format. "
    "Output ONLY a plain list, one object per line. No numbering, no bullets, no explanation.",
)


# SAM 3's segmentation tool call: <tool> {"name": ..., "parameters": {...}} </tool>.
@dataclass(frozen=True)
class ToolCall:
    name: Literal[
        "segment_phrase", "examine_each_mask", "select_masks_and_return", "report_no_mask"
    ]
    text_prompt: str | None = None
    masks: tuple[int, ...] = ()


TOOL_EXAMPLE = (
    '<tool> {"name": "segment_phrase", "parameters": {"text_prompt": "noun phrase"}} </tool>'
)


def read_tool_call(text: str, *, first: bool, mask_count: int) -> ToolCall:
    """The tool call in an answer; `first` calls may only segment or report no mask."""
    clean = _without_thinking(text)
    if "<tool>" not in clean or "</tool>" not in clean:
        raise Unreadable("the answer has no <tool> call")
    raw = clean.split("<tool>")[-1].split("</tool>")[0].strip().replace("}}}", "}}")
    try:
        call = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise Unreadable("the <tool> call is not valid JSON") from exc
    if not isinstance(call, dict):
        raise Unreadable("the <tool> call needs a name and parameters")
    call = cast(dict[str, object], call)
    name, parameters = call.get("name"), call.get("parameters", {})
    if not isinstance(parameters, dict):
        raise Unreadable("the <tool> call's parameters must be an object")
    parameters = cast(dict[str, object], parameters)
    if first and name not in ("segment_phrase", "report_no_mask"):
        raise Unreadable("the first <tool> call must be segment_phrase or report_no_mask")
    if name == "segment_phrase":
        prompt = parameters.get("text_prompt")
        if list(parameters) != ["text_prompt"] or not isinstance(prompt, str) or not prompt.strip():
            raise Unreadable("segment_phrase needs exactly one non-empty text_prompt")
        return ToolCall("segment_phrase", text_prompt=prompt.strip())
    if name == "select_masks_and_return":
        masks = parameters.get("final_answer_masks")
        numbers = cast(list[object], masks) if isinstance(masks, list) else []
        if (
            list(parameters) != ["final_answer_masks"]
            or not isinstance(masks, list)
            or not all(type(mask) is int and 1 <= mask <= mask_count for mask in numbers)
        ):
            raise Unreadable(f"final_answer_masks must list mask numbers from 1 to {mask_count}")
        return ToolCall(
            "select_masks_and_return", masks=tuple(sorted({cast(int, n) for n in numbers}))
        )
    if name == "examine_each_mask":
        return ToolCall("examine_each_mask")
    if name == "report_no_mask":
        return ToolCall("report_no_mask")
    raise Unreadable(f'"{name}" is not a segmentation tool')


def tool_call_format(*, first: bool, mask_count: int) -> AnswerFormat[ToolCall]:
    return AnswerFormat(
        "segmentation tool",
        lambda text: read_tool_call(text, first=first, mask_count=mask_count),
        "Your response was cut off before the <tool> call. "
        f"Output ONLY the <tool> JSON call now, no thinking. Example: {TOOL_EXAMPLE}",
    )


# SAM 3's mask check: <verdict>Accept</verdict> or <verdict>Reject</verdict>.
def read_verdict(text: str) -> Literal["Accept", "Reject"]:
    clean = _without_thinking(text)
    if "<verdict>" not in clean:
        raise Unreadable("the answer has no <verdict>")
    verdict = clean.split("<verdict>")[-1].split("</verdict>")[0].strip()
    if ("Accept" in verdict) == ("Reject" in verdict):
        raise Unreadable("the verdict must be exactly one of Accept or Reject")
    return "Accept" if "Accept" in verdict else "Reject"


VERDICT = AnswerFormat(
    "mask verdict",
    read_verdict,
    "Your response was cut off. Output ONLY your verdict now: "
    "<verdict>Accept</verdict> or <verdict>Reject</verdict>.",
)


# REST3D's support line: "<object> -> <parent> | <relation> | <type>".
type Relation = Literal["on", "inside", "attach", "hang", "on-attach"]
type SupportType = Literal["fixed", "movable"]
SUPPORT_ROOTS = ("floor", "wall", "ceiling", "floor-wall")
RELATIONS: tuple[Relation, ...] = ("on", "inside", "attach", "hang", "on-attach")
TYPES: tuple[SupportType, ...] = ("fixed", "movable")
RELATION_NAMES: dict[str, Relation] = {relation: relation for relation in RELATIONS}
TYPE_NAMES: dict[str, SupportType] = {kind: kind for kind in TYPES}


@dataclass(frozen=True)
class SupportEdge:
    child: str
    parent: str
    relation: Relation
    type: SupportType


def read_support_line(text: str, child: str, parents: list[str]) -> SupportEdge:
    """The support edge for `child`; unlike REST3D, an unknown parent is refused, not floored."""
    for line in _without_thinking(text).splitlines():
        if "->" not in line:
            continue
        named, rest = (part.strip() for part in line.split("->", 1))
        if named.casefold() != child.casefold():
            raise Unreadable(f'the line is about "{named}", not "{child}"')
        fields = [field.strip() for field in rest.split("|")]
        if len(fields) != 3:
            raise Unreadable("the line needs a parent, a relation and a type")
        parent = next((p for p in parents if p.casefold() == fields[0].casefold()), None)
        if parent is None or parent.casefold() == child.casefold():
            raise Unreadable(f'"{fields[0]}" is not one of the allowed parents')
        relation = RELATION_NAMES.get(fields[1].lower())
        if relation is None:
            raise Unreadable(f'"{fields[1]}" is not a relation')
        kind = TYPE_NAMES.get(fields[2].lower())
        if kind is None:
            raise Unreadable(f'"{fields[2]}" is not fixed or movable')
        return SupportEdge(child, parent, relation, kind)
    raise Unreadable("the answer has no support line")


def support_format(child: str, parents: list[str]) -> AnswerFormat[SupportEdge]:
    return AnswerFormat(
        "support",
        lambda text: read_support_line(text, child, parents),
        f"Output ONLY one line:\n{child} -> parent_name | relation | type\n",
    )
