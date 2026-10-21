"""Room-frame conversion and per-device alignment storage."""

import json
import math

from test_session_flow import open_socket, receive_until

from backend.alignment import Alignment, xr_to_room
from backend.protocol import Position


def test_yaw_zero_keeps_forward_toward_the_desk():
    room = xr_to_room(Alignment(), Position(x=0.0, y=0.0, z=-1.0))
    assert room.x == 0.0
    assert room.y == 0.0
    assert room.z == -1.0


def test_origin_places_the_xr_origin_in_the_room():
    alignment = Alignment(status="aligned", yaw=0.0, origin=Position(x=1.0, y=0.0, z=2.0))
    room = xr_to_room(alignment, Position(x=0.0, y=0.0, z=0.0))
    assert (room.x, room.y, room.z) == (1.0, 0.0, 2.0)


def test_desk_width_stays_1_2_meters_after_rotation():
    alignment = Alignment(status="aligned", yaw=0.4, origin=Position(x=0.2, y=0.0, z=-0.3))
    left = xr_to_room(alignment, Position(x=-0.6, y=0.0, z=-1.2))
    right = xr_to_room(alignment, Position(x=0.6, y=0.0, z=-1.2))
    width = math.dist((left.x, left.y, left.z), (right.x, right.y, right.z))
    assert abs(width - 1.2) < 1e-9


def view_forward(orientation):
    """Match the viewer forward used by frontend/src/alignment.ts. Order is x, y, z, w."""
    qx, qy, qz, qw = orientation
    return (-2 * (qw * qy + qx * qz), -1 + 2 * (qx * qx + qy * qy))


# As in frontend/src/alignment.ts: the head is this high above the floor on confirming.
STANDING_EYE_HEIGHT = 1.5


def alignment_from_pose(position, orientation):
    """Same yaw and origin as frontend/src/alignment.ts for a yaw-only viewer pose."""
    forward_x, forward_z = view_forward(orientation)
    yaw = math.atan2(forward_x, -forward_z)
    cosine = math.cos(yaw)
    sine = math.sin(yaw)
    return Alignment(
        status="aligned",
        yaw=yaw,
        origin=Position(
            x=-(cosine * position.x + sine * position.z),
            y=STANDING_EYE_HEIGHT - position.y,
            z=-(-sine * position.x + cosine * position.z),
        ),
    )


def pose_point(position, orientation, right_m, forward_m):
    """A floor point this many meters right and forward of the head, in that device's XR frame.

    The floor is `STANDING_EYE_HEIGHT` under the head the device confirmed from.
    """
    forward_x, forward_z = view_forward(orientation)
    right_x, right_z = -forward_z, forward_x
    return Position(
        x=position.x + right_x * right_m + forward_x * forward_m,
        y=position.y - STANDING_EYE_HEIGHT,
        z=position.z + right_z * right_m + forward_z * forward_m,
    )


# Two devices, two XR origins. Offsets are viewer-right and viewer-forward, in meters.
PHONE_POSE = (Position(x=0.4, y=1.5, z=0.25), (0.0, 0.0, 0.0, 1.0))
HEADSET_POSE = (
    Position(x=-0.7, y=1.6, z=1.1),
    (0.0, math.sin(0.25), 0.0, math.cos(0.25)),
)
LANDMARKS = (
    ("floor center", 0.0, 0.0, (0.0, 0.0, 0.0)),
    ("one meter toward the desk", 0.0, 1.0, (0.0, 0.0, -1.0)),
    ("desk left edge", -0.6, 1.2, (-0.6, 0.0, -1.2)),
    ("desk right edge", 0.6, 1.2, (0.6, 0.0, -1.2)),
)


def room_of(alignment, pose, right_m, forward_m):
    position, orientation = pose
    return xr_to_room(alignment, pose_point(position, orientation, right_m, forward_m))


def test_two_known_poses_agree_on_the_floor_center_and_desk():
    phone = alignment_from_pose(*PHONE_POSE)
    headset = alignment_from_pose(*HEADSET_POSE)
    converted = []
    for _name, right_m, forward_m, expected in LANDMARKS:
        phone_room = room_of(phone, PHONE_POSE, right_m, forward_m)
        headset_room = room_of(headset, HEADSET_POSE, right_m, forward_m)
        disagreement = math.dist(
            (phone_room.x, phone_room.y, phone_room.z),
            (headset_room.x, headset_room.y, headset_room.z),
        )
        assert disagreement < 1e-9
        assert math.dist((phone_room.x, phone_room.y, phone_room.z), expected) < 1e-9
        converted.append(phone_room)
    width = math.dist(
        (converted[2].x, converted[2].y, converted[2].z),
        (converted[3].x, converted[3].y, converted[3].z),
    )
    assert abs(width - 1.2) < 1e-9


def send_alignment(socket, alignment):
    socket.send(
        json.dumps(
            {
                "type": "calibrate",
                "yaw": alignment.yaw,
                "origin": {
                    "x": alignment.origin.x,
                    "y": alignment.origin.y,
                    "z": alignment.origin.z,
                },
            }
        )
    )


def stored_alignment(state, role):
    raw = state["alignment"][role]
    return Alignment(
        status=raw["status"],
        yaw=raw["yaw"],
        origin=Position(x=raw["origin"]["x"], y=raw["origin"]["y"], z=raw["origin"]["z"]),
    )


def test_connected_devices_share_the_same_landmarks(service_url):
    phone_alignment = alignment_from_pose(*PHONE_POSE)
    headset_alignment = alignment_from_pose(*HEADSET_POSE)
    with open_socket(service_url, "mobile_master") as phone, open_socket(
        service_url, "vr_solver"
    ) as headset:
        phone.recv(timeout=2)
        headset.recv(timeout=2)
        send_alignment(phone, phone_alignment)
        send_alignment(headset, headset_alignment)

        def both_aligned(event):
            alignment = event.get("state", {}).get("alignment", {})
            return (
                alignment.get("mobile_master", {}).get("status") == "aligned"
                and alignment.get("vr_solver", {}).get("status") == "aligned"
            )

        shared = receive_until(phone, both_aligned)["state"]
        for right_m, forward_m, expected in (
            (item[1], item[2], item[3]) for item in LANDMARKS
        ):
            from_phone = room_of(
                stored_alignment(shared, "mobile_master"), PHONE_POSE, right_m, forward_m
            )
            from_headset = room_of(
                stored_alignment(shared, "vr_solver"), HEADSET_POSE, right_m, forward_m
            )
            assert math.dist(
                (from_phone.x, from_phone.y, from_phone.z),
                (from_headset.x, from_headset.y, from_headset.z),
            ) < 1e-9
            assert math.dist((from_phone.x, from_phone.y, from_phone.z), expected) < 1e-9
        repeated_pose = (Position(x=1.0, y=1.4, z=-0.2), (0.0, 0.0, 0.0, 1.0))
        repeated = alignment_from_pose(*repeated_pose)
        send_alignment(phone, repeated)

        def phone_replaced(event):
            origin = event.get("state", {}).get("alignment", {}).get("mobile_master", {}).get(
                "origin", {}
            )
            return math.isclose(origin.get("x", 0.0), repeated.origin.x, abs_tol=1e-9)

        replaced = receive_until(headset, phone_replaced)["state"]
        assert math.isclose(
            stored_alignment(replaced, "vr_solver").yaw, headset_alignment.yaw, abs_tol=1e-9
        )
        moved = room_of(stored_alignment(replaced, "mobile_master"), repeated_pose, 0.0, 0.0)
        assert math.dist((moved.x, moved.y, moved.z), (0.0, 0.0, 0.0)) < 1e-9


def test_each_device_stores_its_own_alignment(service_url):
    with open_socket(service_url, "mobile_master") as phone, open_socket(
        service_url, "vr_solver"
    ) as headset:
        phone_state = json.loads(phone.recv(timeout=2))["state"]["alignment"]
        headset.recv(timeout=2)
        assert phone_state["mobile_master"]["status"] == "not_aligned"
        assert phone_state["vr_solver"]["status"] == "not_aligned"
        phone.send(
            json.dumps(
                {"type": "calibrate", "yaw": 0.0, "origin": {"x": 0.0, "y": 0.0, "z": 0.0}}
            )
        )

        def phone_aligned(event):
            alignment = event.get("state", {}).get("alignment", {}).get("mobile_master", {})
            return alignment.get("status") == "aligned"

        shared = receive_until(headset, phone_aligned)["state"]["alignment"]
        assert shared["mobile_master"]["status"] == "aligned"
        assert shared["vr_solver"]["status"] == "not_aligned"
        headset.send(
            json.dumps(
                {"type": "calibrate", "yaw": 1.0, "origin": {"x": 0.5, "y": 0.0, "z": -1.0}}
            )
        )

        def headset_aligned(event):
            alignment = event.get("state", {}).get("alignment", {}).get("vr_solver", {})
            return alignment.get("yaw") == 1.0

        replaced = receive_until(phone, headset_aligned)["state"]["alignment"]
        assert replaced["vr_solver"]["origin"] == {"x": 0.5, "y": 0.0, "z": -1.0}
        assert replaced["mobile_master"]["status"] == "aligned"


def test_disconnect_clears_only_that_device(service_url):
    with open_socket(service_url, "mobile_master") as phone:
        phone.recv(timeout=2)
        send_alignment(phone, alignment_from_pose(*PHONE_POSE))
        with open_socket(service_url, "vr_solver") as headset:
            headset.recv(timeout=2)
            send_alignment(headset, alignment_from_pose(*HEADSET_POSE))

            def both_aligned(event):
                alignment = event.get("state", {}).get("alignment", {})
                return (
                    alignment.get("mobile_master", {}).get("status") == "aligned"
                    and alignment.get("vr_solver", {}).get("status") == "aligned"
                )

            receive_until(phone, both_aligned)

        def headset_cleared(event):
            alignment = event.get("state", {}).get("alignment", {})
            return (
                alignment.get("vr_solver", {}).get("status") == "not_aligned"
                and alignment.get("mobile_master", {}).get("status") == "aligned"
            )

        cleared = receive_until(phone, headset_cleared)["state"]["alignment"]["vr_solver"]
        assert cleared["yaw"] == 0.0
        assert cleared["origin"] == {"x": 0.0, "y": 0.0, "z": 0.0}


def test_a_new_tab_drops_the_previous_alignment_for_that_role(service_url):
    with open_socket(service_url, "mobile_master") as phone, open_socket(
        service_url, "vr_solver"
    ) as headset:
        phone.recv(timeout=2)
        headset.recv(timeout=2)
        send_alignment(phone, alignment_from_pose(*PHONE_POSE))
        send_alignment(headset, alignment_from_pose(*HEADSET_POSE))

        def both_aligned(event):
            alignment = event.get("state", {}).get("alignment", {})
            return (
                alignment.get("mobile_master", {}).get("status") == "aligned"
                and alignment.get("vr_solver", {}).get("status") == "aligned"
            )

        receive_until(phone, both_aligned)
        with open_socket(service_url, "vr_solver") as replacement:
            welcome = json.loads(replacement.recv(timeout=2))
            assert welcome["state"]["alignment"]["vr_solver"]["status"] == "not_aligned"
            assert welcome["state"]["alignment"]["vr_solver"]["origin"] == {
                "x": 0.0,
                "y": 0.0,
                "z": 0.0,
            }
            assert welcome["state"]["alignment"]["mobile_master"]["status"] == "aligned"
