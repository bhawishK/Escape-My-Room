"""Landmarks from Qwen's object boxes (#110): objects placed in a splat room from rendered views,
and a camera located from the boxes of the objects it sees.

The committed test room (`assets/splat-room`) has one object, a red block standing at z = -1
with its splats from x = -0.5 to 0.38 and up to 0.72 m: the landmark in these tests.
"""

import json
import math

import pytest
from test_room_scale import BLOCK, TEST_ROOM, red_box

from backend.boxes import read_boxes
from backend.landmarks import (
    Landmark,
    build_landmarks,
    load_landmarks,
    locate,
    place_box,
    pose_view,
    save_landmarks,
    solve_pose,
)
from backend.openrouter import OpenRouterClient, OpenRouterConfig, Reply, Unreadable
from backend.room_scale import room_splats
from backend.room_views import View, project, render_views
from tests.fake_openrouter import FakeOpenRouter, fake_openrouter


def test_labelled_boxes_keep_their_label_as_asked():
    answer = (
        '```json\n[{"label": "Door", "bbox_2d": [283, 103, 383, 630]},\n'
        ' {"label": "waste bin", "bbox_2d": [500, 700, 600, 900], "confidence": 0.9}]\n```'
    )
    assert read_boxes(answer, ["door", "waste bin"]) == [
        ("door", (0.283, 0.103, 0.383, 0.63)),
        ("waste bin", (0.5, 0.7, 0.6, 0.9)),
    ]


def test_a_label_that_was_not_asked_for_is_unreadable():
    with pytest.raises(Unreadable, match="door, waste bin"):
        read_boxes('[{"label": "trash can", "bbox_2d": [1, 2, 3, 4]}]', ["door", "waste bin"])


@pytest.mark.parametrize(
    "position", [(0.0, 1.2, 1.0), (1.2, 0.5, 0.2), (-0.9, 1.6, 0.6)], ids=["front", "low", "high"]
)
def test_a_box_is_placed_in_the_room_where_its_object_stands(position):
    view = View(position=position, look_at=BLOCK)
    [rendered] = render_views(TEST_ROOM, [view])

    placed = place_box(room_splats(TEST_ROOM), view, red_box(rendered.png))

    # The block's middle: its splats run x -0.5..0.38, y 0..0.72, at z = -1, drawn ~0.1 m wider.
    assert placed is not None
    assert math.dist(placed, BLOCK) < 0.12


LANDMARKS = [
    Landmark("door", "door", (0.0, 1.0, -2.0)),
    Landmark("waste_bin", "waste bin", (1.5, 0.2, -1.5)),
    Landmark("mirror", "mirror", (-1.0, 1.6, -2.5)),
    Landmark("door_2", "door", (2.5, 1.0, 0.5)),
]
TRUE_POSE = (0.3, 1.4, 0.5)
TRUE_HEADING = math.radians(10)
PITCH = math.radians(-12)


def seen_from(position, heading, pitch, *names):
    """The boxes a camera at this pose sees round the named landmarks' centres."""
    view = pose_view(position, heading, pitch)
    sightings = []
    for landmark in LANDMARKS:
        if landmark.id in names:
            x, y = project(view, landmark.centre) or (0, 0)
            sightings.append((landmark.label, (x - 0.03, y - 0.05, x + 0.03, y + 0.05)))
    return sightings


@pytest.mark.parametrize(
    "names",
    [("door", "waste_bin", "mirror"), ("door", "mirror", "door_2")],
    ids=["three", "two doors"],
)
def test_a_camera_is_located_from_the_landmarks_it_sees(names):
    sightings = seen_from(TRUE_POSE, TRUE_HEADING, PITCH, *names)

    fix = solve_pose(sightings, LANDMARKS, PITCH)

    assert fix is not None
    assert math.dist(fix.position, TRUE_POSE) < 0.01
    assert math.degrees(abs(fix.heading - TRUE_HEADING)) < 0.5
    assert sorted(fix.landmarks) == sorted(names)


def test_one_landmark_is_not_enough_to_locate_a_camera():
    assert solve_pose(seen_from(TRUE_POSE, TRUE_HEADING, PITCH, "door"), LANDMARKS, PITCH) is None
    assert solve_pose([("sofa", (0.4, 0.4, 0.6, 0.6))], LANDMARKS, PITCH) is None


def client_for(fake: FakeOpenRouter, monkeypatch: pytest.MonkeyPatch) -> OpenRouterClient:
    monkeypatch.setenv("ESCAPE_ROOM_OPENROUTER_URL", fake.url)
    return OpenRouterClient(OpenRouterConfig.from_environment(), "sk-or-test-key-never-shown")


def boxes_answer(label: str, png: bytes) -> str:
    return json.dumps([{"label": label, "bbox_2d": [round(1000 * e) for e in red_box(png)]}])


def test_sightings_from_several_views_become_one_landmark_on_the_map(monkeypatch, tmp_path):
    views = [
        View(position=(0.0, 1.2, 1.0), look_at=BLOCK),
        View(position=(1.2, 0.5, 0.2), look_at=BLOCK),
    ]
    shots = render_views(TEST_ROOM, views)
    replies: list[tuple[Reply, str | None]] = []
    with fake_openrouter() as fake:
        for shot in shots:
            fake.answer(boxes_answer("red block", shot.png))
        built = build_landmarks(
            TEST_ROOM,
            client_for(fake, monkeypatch),
            lambda reply, problem: replies.append((reply, problem)),
            ["red block"],
            views=views,
        )

    [landmark] = built.landmarks
    assert (landmark.id, landmark.label) == ("red_block", "red block")
    assert math.dist(landmark.centre, BLOCK) < 0.12
    assert [sighting.view_number for sighting in built.sightings] == [1, 2]
    assert len(replies) == 2
    # Every request asked for the labels, and nothing else.
    for request in fake.received:
        assert "red block" in request.body["messages"][0]["content"][-1]["text"]

    save_landmarks(tmp_path, built.landmarks)
    assert load_landmarks(tmp_path) == built.landmarks


def test_a_view_with_only_one_landmark_in_it_is_not_located(monkeypatch):
    view = View(position=(0.0, 1.2, 1.0), look_at=BLOCK)
    [shot] = render_views(TEST_ROOM, [view])
    with fake_openrouter() as fake:
        fake.answer(boxes_answer("red block", shot.png))
        located = locate(
            client_for(fake, monkeypatch),
            lambda reply, problem: None,
            shot,
            [Landmark("red_block", "red block", BLOCK)],
            pitch=0.0,
        )

    assert located.fix is None
    assert [label for label, _ in located.sightings] == ["red block"]


def test_one_object_qwen_names_two_ways_is_one_landmark_that_answers_to_both(monkeypatch):
    """Qwen called the hallway's cupboard both a door and a cupboard, with the same box."""
    view = View(position=(0.0, 1.2, 1.0), look_at=BLOCK)
    [shot] = render_views(TEST_ROOM, [view])
    edges = [round(1000 * e) for e in red_box(shot.png)]
    nudged = [edges[0] + 4, edges[1], edges[2], edges[3] - 3]
    with fake_openrouter() as fake:
        fake.answer(
            json.dumps(
                [
                    {"label": "door", "bbox_2d": edges},
                    {"label": "cupboard", "bbox_2d": nudged},
                ]
            )
        )
        built = build_landmarks(
            TEST_ROOM,
            client_for(fake, monkeypatch),
            lambda reply, problem: None,
            ["door", "cupboard"],
            views=[view],
        )

    [landmark] = built.landmarks
    assert (landmark.label, landmark.aliases) == ("door", ("cupboard",))
    # Located later, either name finds it.
    other = Landmark("bin", "waste bin", (1.5, 0.2, -1.5))
    cupboard = Landmark("door", "door", BLOCK, aliases=("cupboard",))
    sightings = seen_from(TRUE_POSE, TRUE_HEADING, PITCH)
    for name in ("door", "cupboard"):
        pose = pose_view(TRUE_POSE, TRUE_HEADING, PITCH)
        boxes = []
        for mark, label in ((cupboard, name), (other, "waste bin")):
            x, y = project(pose, mark.centre) or (0, 0)
            boxes.append((label, (x - 0.03, y - 0.05, x + 0.03, y + 0.05)))
        fix = solve_pose([*sightings, *boxes], [cupboard, other], PITCH)
        assert fix is not None and math.dist(fix.position, TRUE_POSE) < 0.01


def test_the_same_box_under_two_labels_is_one_sighting_when_locating():
    pose = pose_view(TRUE_POSE, TRUE_HEADING, PITCH)
    door = next(mark for mark in LANDMARKS if mark.id == "door")
    x, y = project(pose, door.centre) or (0, 0)
    box = (x - 0.03, y - 0.05, x + 0.03, y + 0.05)
    # The door, seen once but named twice, is still one landmark: not enough to locate from.
    assert solve_pose([("door", box), ("mirror", box)], LANDMARKS, PITCH) is None


def test_a_wrong_box_among_good_ones_is_left_out_of_the_fix():
    sightings = seen_from(TRUE_POSE, TRUE_HEADING, PITCH, "door", "waste_bin", "mirror")
    # Qwen also boxes a "door" where there is none: half the view away from either door.
    wrong = ("door", (0.05, 0.05, 0.12, 0.2))

    fix = solve_pose([*sightings, wrong], LANDMARKS, PITCH)

    assert fix is not None
    assert math.dist(fix.position, TRUE_POSE) < 0.01
    assert sorted(fix.landmarks) == ["door", "mirror", "waste_bin"]
    assert fix.agreeing == 3


def test_two_landmarks_locate_a_camera_only_near_where_it_roughly_is():
    """Two landmarks fit several poses exactly; on the hallway's views most were metres off. The
    phone's own tracking says roughly where it is, which picks the right one."""
    sightings = seen_from(TRUE_POSE, TRUE_HEADING, PITCH, "door", "waste_bin")
    assert solve_pose(sightings, LANDMARKS, PITCH) is None

    drifted = (TRUE_POSE[0] + 0.4, TRUE_POSE[1], TRUE_POSE[2] - 0.3)
    fix = solve_pose(sightings, LANDMARKS, PITCH, near=drifted)
    assert fix is not None and fix.agreeing == 2
    assert math.dist(fix.position, TRUE_POSE) < 0.01

    # A rough place far from any fitting pose does not force one.
    assert solve_pose(sightings, LANDMARKS, PITCH, near=(5.0, 1.4, 5.0)) is None
