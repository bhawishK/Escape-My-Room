"""Render-and-ask (#98): views of a splat room rendered on the server, and Qwen asked about them.

The committed test room (`assets/splat-room`) is a checkered floor with a red block standing at
z = -1, from x = -0.5 to 0.38 and up to 0.72 m. Its views are rendered for real, in headless Edge
with Spark; that needs `npm run build` in `frontend` first.
"""

import importlib.util
import io
import json
import math
from pathlib import Path

import pytest
from PIL import Image
from test_prepared_room import copy_room, edit_manifest

from backend.openrouter import OpenRouterClient, OpenRouterConfig, ProviderFailure, Reply
from backend.room_views import (
    SHORT_ANSWER,
    RenderedView,
    View,
    ask_about_views,
    filmed,
    orbit,
    overhead,
    render_views,
    standing,
)
from tests.fake_openrouter import FakeOpenRouter, fake_openrouter

ROOT = Path(__file__).resolve().parents[1]
TEST_ROOM = ROOT / "assets" / "splat-room"
BLOCK = (-0.06, 0.36, -1.0)


def red_share(png: bytes, box: tuple[float, float, float, float] = (0.0, 0.0, 1.0, 1.0)) -> float:
    """The share of pixels in a box (fractions of the image) that are the block's red."""
    with Image.open(io.BytesIO(png)) as image:
        rgb = image.convert("RGB")
    width, height = rgb.size
    left, top, right, bottom = box
    region = rgb.crop(
        (int(left * width), int(top * height), int(right * width), int(bottom * height))
    )
    pixels = list(region.get_flattened_data())
    return sum(r > 150 and g < 90 and b < 90 for r, g, b in pixels) / len(pixels)


CENTRE = (0.4, 0.4, 0.6, 0.6)
# The block is a thin wall: seen edge-on it covers only a narrow strip through the centre.
CENTRE_SPOT = (0.48, 0.48, 0.52, 0.52)


def test_a_view_shows_what_it_looks_at_and_nothing_behind_the_camera():
    towards, away = render_views(
        TEST_ROOM,
        [
            View(position=(0.0, 1.2, 1.0), look_at=BLOCK),
            View(position=(0.0, 1.2, 1.0), look_at=(0.0, 1.2, 3.0)),
        ],
    )

    assert towards.png.startswith(b"\x89PNG")
    with Image.open(io.BytesIO(towards.png)) as image:
        assert image.size == (640, 480)
    assert red_share(towards.png, CENTRE) > 0.9
    assert red_share(away.png) == 0
    assert towards.seconds > 0


def test_an_orbit_looks_at_its_target_from_all_round():
    views = orbit(BLOCK, distance=1.5, count=4, height=1.0)

    assert len(views) == 4
    for view in views:
        assert view.look_at == BLOCK
        assert view.position[1] == 1.0
        across = ((view.position[0] - BLOCK[0]) ** 2 + (view.position[2] - BLOCK[2]) ** 2) ** 0.5
        assert abs(across - 1.5) < 1e-9
    # The first view stands in front of the target, on its +z side; the others go round.
    assert views[0].position[0] == BLOCK[0] and views[0].position[2] > BLOCK[2]
    for rendered in render_views(TEST_ROOM, views):
        assert red_share(rendered.png, CENTRE_SPOT) > 0.9


def test_overhead_looks_straight_down_on_its_target():
    [view] = [overhead(BLOCK, height=3.0)]
    assert view.position == (BLOCK[0], 3.0, BLOCK[2])
    assert view.look_at == BLOCK

    [rendered] = render_views(TEST_ROOM, [view])
    assert red_share(rendered.png, CENTRE_SPOT) > 0.9
    # The checkered floor fills the view round the block: the room is seen from above.
    assert red_share(rendered.png) < 0.1


def test_the_solver_stands_on_the_floor_at_eye_height_and_looks_at_the_target():
    view = standing((0.8, 1.2), BLOCK)
    assert view.position == (0.8, 1.6, 1.2)
    assert view.look_at == BLOCK

    [rendered] = render_views(TEST_ROOM, [view])
    assert red_share(rendered.png, CENTRE_SPOT) > 0.9


def test_a_filmed_camera_is_placed_with_the_splat_and_still_sees_what_it_filmed(tmp_path):
    """The notebook's cameras are in the splat's own frame; the manifest's placement moves both."""
    room = copy_room(TEST_ROOM, tmp_path / "room")
    half = math.sqrt(0.5)
    placement = {
        "position": {"x": 0.0, "y": 0.5, "z": 0.0},
        "rotation": {"x": 0.0, "y": half, "z": 0.0, "w": half},  # 90 degrees about y
        "scale": 2.0,
    }
    edit_manifest(room, lambda manifest: manifest["splat"].update(placement))
    # Filmed from 1.2 m up, 1 m in front of the block, looking at it, in the splat's frame.
    towards = (BLOCK[0], BLOCK[1] - 1.2, BLOCK[2] - 1.0)
    length = math.sqrt(sum(c * c for c in towards))
    camera = {"position": [0.0, 1.2, 1.0], "forward": [c / length for c in towards]}
    (room / "report.json").write_text(json.dumps({"cameras": [camera]}), encoding="utf-8")

    [view] = filmed(room)

    # Scaled by 2 to (0, 2.4, 2), turned 90 degrees about y to (2, 2.4, 0), lifted 0.5.
    assert view.position == pytest.approx((2.0, 2.9, 0.0))
    [rendered] = render_views(room, [view])
    assert red_share(rendered.png, CENTRE_SPOT) > 0.9


def test_a_room_without_a_report_has_no_filmed_views():
    assert filmed(TEST_ROOM) == []


def test_building_a_room_keeps_the_notebooks_report_for_its_filmed_views(tmp_path):
    spec = importlib.util.spec_from_file_location("splat_build_room", TEST_ROOM / "build_room.py")
    assert spec and spec.loader
    build_room = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(build_room)
    source = tmp_path / "download"
    source.mkdir()
    (source / "room.ply").write_bytes((TEST_ROOM / "room.ply").read_bytes())
    camera = {"position": [0.0, 1.2, 1.0], "forward": [0.0, -0.5, -0.8660254]}
    (source / "report.json").write_text(json.dumps({"cameras": [camera]}), encoding="utf-8")

    build_room.write_room(tmp_path / "room", source / "room.ply", source / "report.json", 1)

    assert json.loads((tmp_path / "room" / "report.json").read_text(encoding="utf-8")) == {
        "cameras": [camera]
    }
    # The room is scaled so the phone was held 1.4 m up; its camera moves with it.
    [view] = filmed(tmp_path / "room")
    assert view.position == pytest.approx((0.0, 1.4, 1.4 / 1.2))


def picture(colour: str) -> RenderedView:
    """A plain rendered view, standing in for a real one when only the asking is tested."""
    data = io.BytesIO()
    Image.new("RGB", (64, 48), colour).save(data, format="PNG")
    return RenderedView(View(position=(0.0, 1.6, 1.0), look_at=BLOCK), data.getvalue(), 0.1)


def client_for(fake: FakeOpenRouter, monkeypatch: pytest.MonkeyPatch) -> OpenRouterClient:
    monkeypatch.setenv("ESCAPE_ROOM_OPENROUTER_URL", fake.url)
    return OpenRouterClient(OpenRouterConfig.from_environment(), "sk-or-test-key-never-shown")


def test_qwen_sees_every_view_in_order_then_the_question(monkeypatch):
    replies: list[tuple[Reply, str | None]] = []
    with fake_openrouter() as fake:
        fake.answer("a red block", cost=0.0005)
        answer = ask_about_views(
            client_for(fake, monkeypatch),
            [picture("red"), picture("blue")],
            "What object is at the centre of these views?",
            SHORT_ANSWER,
            lambda reply, problem: replies.append((reply, problem)),
        )

    assert answer == "a red block"
    [request] = fake.received
    [message] = request.body["messages"]
    parts = message["content"]
    assert [part["type"] for part in parts] == ["text", "image_url", "text", "image_url", "text"]
    assert [parts[0]["text"], parts[2]["text"]] == ["View 1:", "View 2:"]
    assert parts[1]["image_url"]["url"].startswith("data:image/png;base64,")
    assert parts[4]["text"].startswith("What object is at the centre of these views?")
    [(reply, problem)] = replies
    assert (reply.cost_usd, reply.prompt_tokens, problem) == (0.0005, 1200, None)


def test_a_rambling_answer_is_repaired_and_both_replies_are_recorded(monkeypatch):
    replies: list[tuple[Reply, str | None]] = []
    with fake_openrouter() as fake:
        fake.answer("In the centre of the view there is a block.\nIt is red and stands on a floor.")
        fake.answer("a red block")
        answer = ask_about_views(
            client_for(fake, monkeypatch),
            [picture("red")],
            "What object is at the centre of this view?",
            SHORT_ANSWER,
            lambda reply, problem: replies.append((reply, problem)),
        )

    assert answer == "a red block"
    assert [problem is None for _, problem in replies] == [False, True]
    repair = fake.received[1].body["messages"][-1]["content"][0]["text"]
    assert "one short line" in repair


def test_a_spent_key_fails_once_with_a_clear_reason(monkeypatch):
    with fake_openrouter() as fake:
        fake.fail(402, "Insufficient credits")
        with pytest.raises(ProviderFailure) as failure:
            ask_about_views(
                client_for(fake, monkeypatch),
                [picture("red")],
                "What is this?",
                SHORT_ANSWER,
                lambda reply, problem: None,
            )

    assert failure.value.kind == "resource"
    assert "spending limit" in str(failure.value)
    assert len(fake.received) == 1


@pytest.mark.parametrize("count", [0, 8])
def test_qwen_is_asked_about_one_to_seven_views(monkeypatch, count):
    with fake_openrouter() as fake:
        with pytest.raises(ValueError, match="1 to 7 views"):
            ask_about_views(
                client_for(fake, monkeypatch),
                [picture("red")] * count,
                "What is this?",
                SHORT_ANSWER,
                lambda reply, problem: None,
            )

    assert fake.received == []
