"""Objects stay in the room (#213): a let-go outside it or under the floor lands on the floor, and
one that falls out anyway is put back without freezing the others. The default room's floor is
4 x 4 m round the origin, its top at y = 0."""

import asyncio
import json
from pathlib import Path

import pytest
from test_manipulation import box, open_socket, receive_until
from test_physics_fall import let_go_from, ready, until_rest
from test_solver_grab import acquire, grip, owned_by

from backend.prepared_room import load_prepared_room
from backend.sessions import PrototypeRoom

ROOM = Path(__file__).resolve().parents[1] / "assets" / "prepared-room"
HALF_FLOOR = 2.0
HALF_BOX = 0.1


def let_go_at(ws, start, place):
    """Take the box from `start`, carry it to `place` and let go there."""
    ws.send(json.dumps(acquire(start)))
    held = receive_until(ws, lambda event: owned_by(event, "vr_solver"))["state"]
    identity = held["manipulation"]["id"]
    ws.send(json.dumps(grip(1, place, identity)))
    receive_until(
        ws,
        lambda event: (
            owned_by(event, "vr_solver") and event["state"]["manipulation"]["sequence"] == 1
        ),
    )
    ws.send(json.dumps({"type": "release", "manipulation_id": identity}))


def test_a_box_let_go_outside_the_room_lands_on_its_floor(start_service, tmp_path):
    with start_service(tmp_path) as url, open_socket(url, "vr_solver") as headset:
        start = ready(headset)
        let_go_at(headset, start, {"x": HALF_FLOOR + 0.6, "y": 0.4, "z": start["z"]})
        rested = box(until_rest(headset)[-1][1])
        assert rested["x"] <= HALF_FLOOR - HALF_BOX + 1e-6
        assert rested["y"] == pytest.approx(0.0, abs=0.01)


def test_a_box_let_go_under_the_floor_comes_up_onto_it(start_service, tmp_path):
    with start_service(tmp_path) as url, open_socket(url, "vr_solver") as headset:
        start = ready(headset)
        let_go_from(headset, start, -0.5)
        rested = box(until_rest(headset)[-1][1])
        assert rested["y"] == pytest.approx(0.0, abs=0.01)
        assert rested["x"] == pytest.approx(start["x"], abs=0.01)


def test_an_object_fallen_out_of_the_room_is_put_back_and_the_others_still_move():
    room = PrototypeRoom()
    room.entities = load_prepared_room(ROOM).entities
    still = {"x": 0.0, "y": 0.0, "z": 0.0, "w": 1.0}
    poses = [
        {"id": "box", "position": {"x": 2.9, "y": -150.0, "z": -0.4}, "rotation": still},
        {"id": "desk", "position": {"x": 0.0, "y": 0.0, "z": -1.2}, "rotation": still},
    ]
    room.entities.append(room.entity("box").model_copy(update={"id": "crate"}))
    poses.append({"id": "crate", "position": {"x": 0.3, "y": 0.5, "z": 0.3}, "rotation": still})

    asyncio.run(room._apply_physics(poses))

    back = room.entity("box").position
    assert back.y == pytest.approx(0.0)
    assert -HALF_FLOOR <= back.x <= HALF_FLOOR - HALF_BOX + 1e-6
    assert room.entity("crate").position.y == pytest.approx(0.5)
