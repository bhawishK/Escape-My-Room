"""A lost pose or a forgotten alignment leaves the box where it was."""

import json

import pytest
from test_manipulation import Phone, box, open_socket, receive_until
from test_solver_grab import acquire, grip, restore


def test_letting_go_on_a_loss_leaves_the_box_and_a_later_pose_does_not_move_it(service_url):
    with open_socket(service_url, "mobile_master") as phone_ws, open_socket(
        service_url, "vr_solver"
    ) as headset:
        phone = Phone(phone_ws)
        start = box(json.loads(headset.recv(timeout=2))["state"])
        phone.walk_to(0.0, 1.6)
        held = phone.pick_up()
        carried = box(held)
        identity = held["manipulation"]["id"]
        phone.drop(identity)
        phone_ws.send(
            json.dumps(
                {
                    "type": "pose",
                    "sequence": phone.sequence + 1,
                    "tracking_status": "lost",
                    "reference_space": None,
                    "position": None,
                    "heading": None,
                    "pitch": None,
                }
            )
        )
        def lost_marker(event):
            marker = (event.get("state") or {}).get("marker") or {}
            return event.get("type") == "state" and marker.get("tracking_status") == "lost"

        lost = receive_until(headset, lost_marker)["state"]
        assert lost["manipulation"] is None
        assert box(lost) == pytest.approx(carried)
        restore(phone_ws, start)


def test_forgetting_alignment_does_not_move_a_grip_hold(service_url):
    with open_socket(service_url, "mobile_master") as phone_ws, open_socket(
        service_url, "vr_solver"
    ) as headset:
        phone_ws.recv(timeout=2)
        start = box(json.loads(headset.recv(timeout=2))["state"])
        headset.send(
            json.dumps(
                {"type": "calibrate", "yaw": 0.0, "origin": {"x": 0.0, "y": 0.0, "z": 0.0}}
            )
        )

        def aligned(event):
            status = event.get("state", {}).get("alignment", {}).get("vr_solver", {}).get("status")
            return status == "aligned"

        receive_until(headset, aligned)
        receive_until(phone_ws, aligned)
        headset.send(json.dumps(acquire(start)))

        def owned(event):
            manipulation = (event.get("state") or {}).get("manipulation") or {}
            return manipulation.get("owner") == "vr_solver"

        grabbed = receive_until(headset, owned)["state"]
        identity = grabbed["manipulation"]["id"]
        lifted = {"x": start["x"], "y": start["y"] + 0.4, "z": start["z"]}
        headset.send(json.dumps(grip(1, lifted, identity)))

        def gripped(event):
            manipulation = (event.get("state") or {}).get("manipulation") or {}
            return manipulation.get("sequence") == 1

        receive_until(headset, gripped)
        headset.send(json.dumps({"type": "release", "manipulation_id": identity}))

        def released(event):
            return event.get("type") == "state" and event["state"]["manipulation"] is None

        receive_until(headset, released)
        headset.send(json.dumps({"type": "clear_alignment"}))

        def cleared_alignment(event):
            status = event.get("state", {}).get("alignment", {}).get("vr_solver", {}).get("status")
            return status == "not_aligned"

        cleared = receive_until(phone_ws, cleared_alignment)["state"]
        assert box(cleared) == pytest.approx(lifted)
        restore(headset, start)
