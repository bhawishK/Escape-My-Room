"""The server's one physics simulation (#159): a Havok worker beside Python; WebSocket seam."""

from pathlib import Path

import pytest
from test_live_room import activate, reconstructed
from test_manipulation import Phone, box, open_socket, receive_until
from test_reconstruction_jobs import settings


def physics_when(ws, ready):
    """The physics status from the welcome or a later state, once `ready(status)` holds."""
    return receive_until(
        ws,
        lambda event: event["type"] in ("welcome", "state") and ready(event["state"]["physics"]),
    )["state"]["physics"]


def unavailable(physics):
    return physics["status"] == "unavailable"


def test_the_session_reports_physics_running_with_the_rooms_floor_and_box(service_url):
    with open_socket(service_url, "vr_solver") as ws:
        # The worker reports itself ready, then the room it has loaded.
        physics = physics_when(ws, lambda status: status["room_version"] is not None)
        assert physics["status"] == "running"
        assert physics["engine"] == "havok"
        assert physics["reason"] is None
        # The prepared room's floor and the four walls along its edges (#162) are solid, and its
        # box can move; the desk and cabinet aren't colliders yet.
        assert physics["room_version"] == 1
        assert physics["bodies"] == {"static": 5, "dynamic": 1}


def assert_the_phone_still_carries_the_box(url):
    with open_socket(url, "mobile_master") as ws:
        phone = Phone(ws)
        resting = box(phone.walk_to(0.0, 1.6))
        held = phone.pick_up()
        assert box(held) == pytest.approx({"x": 0.0, "y": resting["y"], "z": 0.1})
        phone.walk_to(0.5, 1.6)
        dropped = phone.drop(held["manipulation"]["id"])
        assert box(dropped) == pytest.approx({"x": 0.5, "y": resting["y"], "z": 0.1})


def test_a_worker_that_cant_start_leaves_physics_unavailable_and_holds_working(
    start_service, tmp_path
):
    missing = tmp_path / "missing-worker.mjs"
    with start_service(tmp_path / "data", ESCAPE_ROOM_PHYSICS_WORKER=str(missing)) as url:
        with open_socket(url, "vr_solver") as ws:
            physics = physics_when(ws, unavailable)
            assert physics["reason"].startswith("The physics worker exited with code 1: ")
            assert "Cannot find module" in physics["reason"]
            assert physics["bodies"] is None
        assert_the_phone_still_carries_the_box(url)


def test_a_worker_that_dies_leaves_physics_unavailable_with_its_reason_and_holds_working(
    start_service, tmp_path
):
    dying = Path(__file__).with_name("fake_physics_worker.mjs")
    with start_service(tmp_path / "data", ESCAPE_ROOM_PHYSICS_WORKER=str(dying)) as url:
        with open_socket(url, "vr_solver") as ws:
            physics = physics_when(ws, unavailable)
            assert physics["reason"] == (
                "The physics worker exited with code 3: The fake worker crashed on purpose."
            )
        assert_the_phone_still_carries_the_box(url)


def test_making_a_room_live_loads_it_into_physics(start_service, tmp_path):
    with start_service(tmp_path, **settings()) as url:
        job = reconstructed(url)
        with open_socket(url, "vr_solver") as ws:
            physics_when(ws, lambda status: status["room_version"] == 1)
            assert activate(url, job).status_code == 200
            physics = physics_when(ws, lambda status: status["room_version"] == 2)
        # The reconstructed room's floor, its four edge walls and its box.
        assert physics["status"] == "running"
        assert physics["bodies"] == {"static": 5, "dynamic": 1}
