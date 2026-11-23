"""The phone drops and throws (#219): let go, the box falls under the server's physics where the
phone put it; flicked before letting go, it flies at the speed it was being carried. WebSocket
seam, real Havok worker."""

import math
import time

import pytest
from test_manipulation import Phone, box, open_socket
from test_physics_fall import ready, until_rest
from test_physics_throw import inside_the_floor

from backend.sessions import THROW_MIN_SPEED, phone_throw


def test_the_speed_is_read_from_the_carry_s_last_moments():
    # 0.6 m in 0.1 s along x: 6 m/s; anything older than the window doesn't count.
    track = [(0.0, -5.0, 0.0, 0.0), (10.0, 0.0, 0.0, 0.0), (10.1, 0.6, 0.0, 0.0)]
    velocity = phone_throw(track, 10.1)
    assert velocity is not None
    assert velocity.x == pytest.approx(6.0) and velocity.y == 0 and velocity.z == 0
    # Still or slow: no throw.
    assert phone_throw([(0.0, 1.0, 0.0, 1.0), (0.1, 1.0, 0.0, 1.0)], 0.1) is None
    slow = 0.5 * THROW_MIN_SPEED * 0.1
    assert phone_throw([(0.0, 0.0, 0.0, 0.0), (0.1, slow, 0.0, 0.0)], 0.1) is None
    # One point, or none recent: no throw.
    assert phone_throw([(0.0, 0.0, 0.0, 0.0)], 0.0) is None
    assert phone_throw([(0.0, 0.0, 0.0, 0.0), (0.05, 1.0, 0.0, 0.0)], 5.0) is None


def carried(phone: Phone, heading: float = 0.0):
    """Pick the box up and aim it 1.5 m ahead of the phone standing at the origin."""
    phone.walk_to(0.0, 0.0, heading)
    held = phone.pick_up()
    return held["manipulation"]["id"]


def test_a_still_let_go_leaves_it_where_the_phone_put_it(start_service, tmp_path):
    with (
        start_service(tmp_path) as url,
        open_socket(url, "vr_solver") as headset,
        open_socket(url, "mobile_master") as socket,
    ):
        ready(headset)
        phone = Phone(socket)
        identity = carried(phone)
        put = box(phone.walk_to(0.0, 0.3))
        time.sleep(0.3)  # still for longer than the throw window
        phone.drop(identity)
        rest = until_rest(headset)[-1][1]
        assert math.hypot(box(rest)["x"] - put["x"], box(rest)["z"] - put["z"]) < 0.05


def test_a_flick_before_letting_go_throws_it_further_than_a_still_let_go(start_service, tmp_path):
    with (
        start_service(tmp_path) as url,
        open_socket(url, "vr_solver") as headset,
        open_socket(url, "mobile_master") as socket,
    ):
        ready(headset)
        phone = Phone(socket)
        identity = carried(phone, heading=math.pi / 2)
        # Swinging the phone from facing left to facing ahead sweeps the box quickly across.
        steps = 5
        put = None
        for step in range(1, steps + 1):
            put = box(phone.walk_to(0.0, 0.0, math.pi / 2 * (1 - step / steps)))
            time.sleep(0.02)
        assert put is not None
        phone.drop(identity)
        rest = until_rest(headset)[-1][1]
        moved = math.hypot(box(rest)["x"] - put["x"], box(rest)["z"] - put["z"])
        assert moved > 0.2
        assert inside_the_floor(box(rest))
