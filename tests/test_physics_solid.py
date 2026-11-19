"""Room furniture marked solid collides (#211); WebSocket seam, real Havok worker."""

import json
import shutil
from pathlib import Path

import pytest
from test_manipulation import box, open_socket, receive_until
from test_physics_fall import ready, until_rest
from test_solver_grab import acquire, grip, owned_by

ROOM = Path(__file__).resolve().parents[1] / "assets" / "prepared-room"
# The stand-in room's desk: 1.2 x 0.75 x 0.6 m, standing at (0, 0, -1.2).
DESK_TOP = 0.75


def room_with_desk(tmp_path: Path, solid: bool | None) -> Path:
    room = tmp_path / f"room-{solid}"
    shutil.copytree(ROOM, room)
    manifest = json.loads((room / "manifest.json").read_text(encoding="utf-8"))
    for entity in manifest["entities"]:
        if entity["id"] == "desk" and solid is not None:
            entity["solid"] = solid
    (room / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return room


def drop_over_the_desk(url):
    """Where the box rests after being let go 0.4 m above the desk's middle."""
    with open_socket(url, "vr_solver") as headset:
        start = ready(headset)
        headset.send(json.dumps(acquire(start)))
        identity = receive_until(headset, lambda event: owned_by(event, "vr_solver"))["state"][
            "manipulation"
        ]["id"]
        headset.send(json.dumps(grip(1, {"x": 0.0, "y": DESK_TOP + 0.4, "z": -1.2}, identity)))
        receive_until(
            headset,
            lambda event: (
                owned_by(event, "vr_solver") and event["state"]["manipulation"]["sequence"] == 1
            ),
        )
        headset.send(json.dumps({"type": "release", "manipulation_id": identity}))
        return box(until_rest(headset)[-1][1])


def test_a_box_let_go_above_a_solid_desk_rests_on_its_top(start_service, tmp_path):
    room = room_with_desk(tmp_path, True)
    with start_service(tmp_path / "data", ESCAPE_ROOM_PREPARED_DIR=str(room)) as url:
        rest = drop_over_the_desk(url)
    assert rest["y"] == pytest.approx(DESK_TOP, abs=0.02)


@pytest.mark.parametrize("solid", [None, False])
def test_furniture_not_marked_solid_lets_the_box_fall_to_the_floor_as_before(
    start_service, tmp_path, solid
):
    room = room_with_desk(tmp_path, solid)
    with start_service(tmp_path / "data", ESCAPE_ROOM_PREPARED_DIR=str(room)) as url:
        rest = drop_over_the_desk(url)
    assert rest["y"] == pytest.approx(0.0, abs=0.02)


def test_a_solid_piece_is_counted_among_the_static_bodies(start_service, tmp_path):
    room = room_with_desk(tmp_path, True)
    with (
        start_service(tmp_path / "data", ESCAPE_ROOM_PREPARED_DIR=str(room)) as url,
        open_socket(url, "vr_solver") as ws,
    ):
        state = receive_until(
            ws,
            lambda event: (
                event["type"] in ("welcome", "state")
                and event["state"]["physics"]["room_version"] is not None
            ),
        )["state"]
    # The floor, its four walls and now the desk; the cabinet still isn't solid.
    assert state["physics"]["bodies"] == {"static": 6, "dynamic": 1}
