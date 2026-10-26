"""Room scale from objects of known size (#33): Qwen finds doors in rendered views, the splat
measures them, and the master's choice rescales the room.

The committed test room's red block (`assets/splat-room`) stands in for a door: it stands on the
floor at z = -1, its splats' centres run from x = -0.5 to 0.38 and up to y = 0.72.
"""

import importlib.util
import io
import json
from pathlib import Path

import pytest
from PIL import Image

from backend.openrouter import OpenRouterClient, OpenRouterConfig, Reply, Unreadable
from backend.prepared_room import load_prepared_room
from backend.room_scale import (
    measure_height,
    read_door_boxes,
    room_splats,
    scan_views,
    suggest_scale,
)
from backend.room_views import View, filmed, project, render_views
from tests.fake_openrouter import FakeOpenRouter, fake_openrouter

ROOT = Path(__file__).resolve().parents[1]
TEST_ROOM = ROOT / "assets" / "splat-room"
BLOCK = (-0.06, 0.36, -1.0)
BLOCK_TOP = 0.72


def red_box(png: bytes) -> tuple[float, float, float, float]:
    """The red block's extent in the image, as fractions: left, top, right, bottom."""
    with Image.open(io.BytesIO(png)) as image:
        rgb = image.convert("RGB")
    width, height = rgb.size
    red = [
        (i % width, i // width)
        for i, (r, g, b) in enumerate(rgb.get_flattened_data())
        if r > 150 and g < 90 and b < 90
    ]
    xs, ys = [x for x, _ in red], [y for _, y in red]
    return min(xs) / width, min(ys) / height, (max(xs) + 1) / width, (max(ys) + 1) / height


def test_a_point_projects_where_the_renderer_draws_it():
    view = View(position=(0.0, 1.2, 1.0), look_at=BLOCK, fov_degrees=50.0, width=800, height=600)
    [rendered] = render_views(TEST_ROOM, [view])
    left, top, right, bottom = red_box(rendered.png)

    # The block's top edge and its two sides, at the centres of its outermost splats. Each splat
    # is drawn about 0.1 m past its centre, 0.05 of this view, so the drawn edge lies just outside.
    _, top_y = project(view, (-0.06, BLOCK_TOP, -1.0)) or (0, 0)
    left_x, _ = project(view, (-0.5, 0.36, -1.0)) or (0, 0)
    right_x, _ = project(view, (0.38, 0.36, -1.0)) or (0, 0)
    assert top < top_y < top + 0.06
    assert left < left_x < left + 0.06
    assert right - 0.06 < right_x < right
    assert project(view, BLOCK) == pytest.approx((0.5, 0.5))


def test_a_point_behind_the_camera_is_not_in_the_view():
    view = View(position=(0.0, 1.2, 1.0), look_at=BLOCK)
    assert project(view, (0.0, 1.2, 3.0)) is None


@pytest.mark.parametrize(
    "position", [(0.0, 1.2, 1.0), (1.2, 0.5, 0.2), (-0.9, 1.6, 0.6)], ids=["front", "low", "high"]
)
def test_an_objects_visible_top_is_measured_from_its_box_in_a_view(position):
    view = View(position=position, look_at=BLOCK)
    [rendered] = render_views(TEST_ROOM, [view])

    measured = measure_height(room_splats(TEST_ROOM), view, red_box(rendered.png))

    # The splats' centres reach 0.72 m; they are drawn about 0.1 m further.
    assert measured is not None
    assert BLOCK_TOP < measured.height < BLOCK_TOP + 0.13
    assert measured.splats > 20


def test_a_box_with_nothing_in_it_is_not_measured():
    view = View(position=(0.0, 1.2, 1.0), look_at=(0.0, 3.0, -3.0))
    assert measure_height(room_splats(TEST_ROOM), view, (0.4, 0.1, 0.6, 0.3)) is None


def test_qwens_door_boxes_are_read_from_its_json_even_in_a_code_fence():
    answer = (
        '```json\n[{"label": "door", "bbox_2d": [283, 103, 383, 630], "confidence": 0.97},\n'
        ' {"label": "Door", "bbox_2d": [0, 0, 500, 1000]}]\n```'
    )
    assert read_door_boxes(answer) == [(0.283, 0.103, 0.383, 0.63), (0.0, 0.0, 0.5, 1.0)]
    assert read_door_boxes("[]") == []


@pytest.mark.parametrize(
    "answer",
    [
        "There is one door on the left.",
        '[{"label": "door", "bbox_2d": [283, 103, 383]}]',
        '[{"label": "door", "bbox_2d": [383, 103, 283, 630]}]',
        '[{"label": "door", "bbox_2d": [283, 103, 383, 1630]}]',
        '[{"label": "window", "bbox_2d": [283, 103, 383, 630]}]',
    ],
    ids=["prose", "three numbers", "left of right", "off the image", "not a door"],
)
def test_an_answer_that_is_not_door_boxes_is_unreadable(answer):
    with pytest.raises(Unreadable):
        read_door_boxes(answer)


def client_for(fake: FakeOpenRouter, monkeypatch: pytest.MonkeyPatch) -> OpenRouterClient:
    monkeypatch.setenv("ESCAPE_ROOM_OPENROUTER_URL", fake.url)
    return OpenRouterClient(OpenRouterConfig.from_environment(), "sk-or-test-key-never-shown")


def thousandths(box: tuple[float, float, float, float]) -> list[int]:
    return [round(1000 * edge) for edge in box]


def test_the_doors_qwen_finds_are_measured_into_a_suggested_scale(monkeypatch):
    """The block stands in for a door 0.8 m tall: the room should grow by about 0.8 / 0.78."""
    front = View(position=(0.0, 1.2, 1.0), look_at=BLOCK)
    above = View(position=(0.0, 3.0, -1.0), look_at=(0.0, 0.0, -1.0))
    away = View(position=(0.0, 1.2, 1.0), look_at=(0.0, 1.2, 3.0))
    [shot] = render_views(TEST_ROOM, [front])
    replies: list[tuple[Reply, str | None]] = []
    with fake_openrouter() as fake:
        fake.answer(f'[{{"label": "door", "bbox_2d": {thousandths(red_box(shot.png))}}}]')
        # Seen from above, the box reaches the top of the view: its top edge cannot be trusted.
        fake.answer('[{"label": "door", "bbox_2d": [300, 0, 700, 600]}]')
        fake.answer("[]")
        suggestion = suggest_scale(
            TEST_ROOM,
            client_for(fake, monkeypatch),
            lambda reply, problem: replies.append((reply, problem)),
            views=[front, above, away],
            typical_height=0.8,
        )

    [evidence] = suggestion.evidence
    assert evidence.view == front
    assert BLOCK_TOP < evidence.measured.height < BLOCK_TOP + 0.13
    assert suggestion.factor == pytest.approx(0.8 / evidence.measured.height)
    assert suggestion.skipped == ["View 2: the door's top is cut off by the edge of the view"]
    assert len(replies) == 3 and all(problem is None for _, problem in replies)
    assert [len(r.body["messages"][0]["content"]) for r in fake.received] == [3, 3, 3]


def test_no_doors_found_means_no_suggestion(monkeypatch):
    with fake_openrouter() as fake:
        fake.answer("[]")
        suggestion = suggest_scale(
            TEST_ROOM,
            client_for(fake, monkeypatch),
            lambda reply, problem: None,
            views=[View(position=(0.0, 1.2, 1.0), look_at=BLOCK)],
        )

    assert suggestion.factor is None
    assert suggestion.evidence == []


def load_build_room():
    spec = importlib.util.spec_from_file_location("splat_build_room", TEST_ROOM / "build_room.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def built_room(tmp_path: Path) -> Path:
    """The test room built as from a notebook download, filmed 1.2 m up: scaled to 1.4 m."""
    source = tmp_path / "download"
    source.mkdir()
    (source / "room.ply").write_bytes((TEST_ROOM / "room.ply").read_bytes())
    camera = {"position": [0.0, 1.2, 1.0], "forward": [0.0, -0.5, -0.8660254]}
    (source / "report.json").write_text(json.dumps({"cameras": [camera]}), encoding="utf-8")
    load_build_room().write_room(tmp_path / "room", source / "room.ply", source / "report.json", 1)
    return tmp_path / "room"


def manifest(room: Path) -> dict:
    return json.loads((room / "manifest.json").read_text(encoding="utf-8"))


def test_a_built_room_says_its_scale_is_assumed_from_the_camera_height(tmp_path):
    room = built_room(tmp_path)
    assert manifest(room)["splat"]["scale_source"] == "assumed: the phone was held 1.4 m up"
    # Devices are given the placement only.
    assert "scale_source" not in load_prepared_room(room).splat_placement.model_dump()


def test_rescaling_a_room_scales_the_splat_floor_box_and_filmed_views_together(tmp_path):
    room = built_room(tmp_path)
    before = manifest(room)
    [filmed_before] = filmed(room)

    load_build_room().rescale(room, 1.5, "door height 2.03 m (typical), found by Qwen")

    after = manifest(room)
    assert after["room_version"] == before["room_version"] + 1
    assert after["splat"]["scale"] == pytest.approx(1.5 * before["splat"]["scale"])
    for axis in "xyz":
        assert after["splat"]["position"][axis] == pytest.approx(
            1.5 * before["splat"]["position"][axis]
        )
    assert after["splat"]["rotation"] == before["splat"]["rotation"]
    assert after["splat"]["scale_source"] == "door height 2.03 m (typical), found by Qwen"
    floor_before, box_before = before["entities"]
    floor, box = after["entities"]
    assert floor["size"]["width"] == pytest.approx(1.5 * floor_before["size"]["width"])
    assert floor["size"]["depth"] == pytest.approx(1.5 * floor_before["size"]["depth"])
    assert floor["size"]["height"] == floor_before["size"]["height"]
    # The box is a real-sized prop: it keeps its size and stands on the floor, further out.
    assert box["size"] == box_before["size"]
    assert box["position"] == pytest.approx(
        {"x": 1.5 * box_before["position"]["x"], "y": 0.0, "z": 1.5 * box_before["position"]["z"]}
    )
    # It still loads: the floor model was rewritten to the floor's new size.
    load_prepared_room(room)
    [filmed_after] = filmed(room)
    assert filmed_after.position == pytest.approx(tuple(1.5 * c for c in filmed_before.position))


def test_the_room_is_scanned_from_where_it_was_filmed(tmp_path):
    room = built_room(tmp_path)
    [camera] = filmed(room)

    views = scan_views(room)

    assert len(views) == 8
    assert {view.position for view in views} == {(camera.position[0], 1.1, camera.position[2])}
    # Level, all the way round.
    assert all(view.look_at[1] == 1.1 for view in views)
    assert len({view.look_at for view in views}) == 8


def test_a_room_without_its_filming_is_scanned_from_the_origin():
    assert {view.position for view in scan_views(TEST_ROOM)} == {(0.0, 1.1, 0.0)}
