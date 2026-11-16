"""Moving, carrying and removing placed furniture (#183); WebSocket seam, real Havok worker."""

import json
import math

import httpx
import pytest
from test_furniture import add, furniture
from test_manipulation import error_code, open_socket, receive_until
from test_physics_fall import ready, until_rest
from test_solver_grab import acquire, grip, owned_by


def placed(ws, item, position, yaw=0.0, before=()):
    """Place a piece, wait until it rests, and return it as it came to rest. `before` names the
    pieces already in the room, so the new one is told apart."""
    add(ws, item, position, yaw)
    states = until_rest(ws)
    return next(piece for piece in furniture(states[-1][1]) if piece["id"] not in before)


def piece(state, piece_id):
    return next((entity for entity in state["room"]["entities"] if entity["id"] == piece_id), None)


def test_the_headset_grips_a_placed_chair_moves_it_and_lets_it_settle_there(
    start_service, tmp_path
):
    with start_service(tmp_path) as url, open_socket(url, "vr_solver") as headset:
        ready(headset)
        chair = placed(headset, "chair", {"x": 0.5, "y": 0.0, "z": 0.8})
        start = chair["position"]

        hand = {"x": start["x"], "y": 1.0, "z": start["z"]}
        headset.send(json.dumps(acquire(hand, entity=chair["id"])))
        held = receive_until(headset, lambda event: owned_by(event, "vr_solver"))["state"]
        identity = held["manipulation"]["id"]
        moved = {"x": hand["x"] - 1.0, "y": 1.0, "z": hand["z"] - 0.3}
        headset.send(json.dumps(grip(1, moved, identity)))
        receive_until(
            headset,
            lambda event: (
                owned_by(event, "vr_solver") and event["state"]["manipulation"]["sequence"] == 1
            ),
        )
        headset.send(json.dumps({"type": "release", "manipulation_id": identity}))
        rested = piece(until_rest(headset)[-1][1], chair["id"])

        assert rested["position"]["x"] == pytest.approx(start["x"] - 1.0, abs=0.05)
        assert rested["position"]["z"] == pytest.approx(start["z"] - 0.3, abs=0.05)
        assert rested["position"]["y"] == pytest.approx(0.0, abs=0.01)


def test_the_phone_carries_a_placed_armchair_across_the_floor(start_service, tmp_path):
    with (
        start_service(tmp_path) as url,
        open_socket(url, "vr_solver") as headset,
        open_socket(url, "mobile_master") as phone,
    ):
        ready(headset)
        armchair = placed(headset, "armchair", {"x": -0.8, "y": 0.0, "z": 1.0})
        phone.send(json.dumps({"type": "select", "room_version": 1, "id": armchair["id"]}))
        assert (
            receive_until(phone, lambda event: event["type"] == "selection")["id"] == armchair["id"]
        )
        walk(phone, 1, x=0.0, z=1.5, heading=math.pi / 2)
        phone.send(json.dumps({"type": "acquire", "room_version": 1, "id": armchair["id"]}))
        receive_until(phone, lambda event: owned_by(event, "mobile_master"))
        # Facing left (-x) with the screen 45° down from 1.5 m: the floor 1.5 m ahead.
        carried = walk(phone, 2, x=0.0, z=1.5, heading=math.pi / 2)

        assert piece(carried, armchair["id"])["position"]["x"] == pytest.approx(-1.5, abs=0.01)
        assert piece(carried, armchair["id"])["position"]["z"] == pytest.approx(1.5, abs=0.01)


def walk(phone, sequence, x, z, heading):
    """A tracked phone pose 1.5 m up with the screen 45° down; the state that answers it."""
    phone.send(
        json.dumps(
            {
                "type": "pose",
                "sequence": sequence,
                "tracking_status": "tracked",
                "reference_space": "room",
                "position": {"x": x, "y": 1.5, "z": z},
                "heading": heading,
                "pitch": -math.pi / 4,
            }
        )
    )
    return receive_until(phone, lambda event: event["type"] == "state")["state"]


def test_a_piece_one_person_holds_is_locked_for_the_other(start_service, tmp_path):
    with (
        start_service(tmp_path) as url,
        open_socket(url, "vr_solver") as headset,
        open_socket(url, "mobile_master") as phone,
    ):
        ready(headset)
        lamp = placed(headset, "lamp", {"x": 1.0, "y": 0.0, "z": 1.0})
        headset.send(json.dumps(acquire({"x": 1.0, "y": 1.0, "z": 1.0}, entity=lamp["id"])))
        receive_until(headset, lambda event: owned_by(event, "vr_solver"))

        phone.send(json.dumps({"type": "select", "room_version": 1, "id": lamp["id"]}))
        rejected = receive_until(phone, lambda event: event["type"] == "selection")["rejected"]
        assert rejected["code"] == "selection_held"


def remove(ws, piece_id, room_version=1):
    ws.send(json.dumps({"type": "remove_furniture", "room_version": room_version, "id": piece_id}))


def test_either_person_removes_a_piece_for_both_devices_and_for_physics(start_service, tmp_path):
    with (
        start_service(tmp_path) as url,
        open_socket(url, "vr_solver") as headset,
        open_socket(url, "mobile_master") as phone,
    ):
        ready(headset)
        armchair = placed(headset, "armchair", {"x": -0.8, "y": 0.0, "z": 1.0})
        remove(phone, armchair["id"])

        gone = receive_until(
            headset,
            lambda event: (
                event["type"] == "state" and piece(event["state"], armchair["id"]) is None
            ),
        )["state"]
        assert not furniture(gone)
        # Physics has only the box left moving about.
        counted = receive_until(
            headset,
            lambda event: (
                event["type"] == "state"
                and (event["state"]["physics"]["bodies"] or {}).get("dynamic") == 1
            ),
        )
        assert counted
        # The phone was sent the room without it too.
        receive_until(
            phone,
            lambda event: (
                event["type"] == "state" and piece(event["state"], armchair["id"]) is None
            ),
        )


def test_a_piece_the_other_person_holds_cant_be_removed_but_your_own_can(start_service, tmp_path):
    with (
        start_service(tmp_path) as url,
        open_socket(url, "vr_solver") as headset,
        open_socket(url, "mobile_master") as phone,
    ):
        ready(headset)
        lamp = placed(headset, "lamp", {"x": 1.0, "y": 0.0, "z": 1.0})
        headset.send(json.dumps(acquire({"x": 1.0, "y": 1.0, "z": 1.0}, entity=lamp["id"])))
        receive_until(headset, lambda event: owned_by(event, "vr_solver"))

        remove(phone, lamp["id"])
        assert error_code(phone) == "controlled_by_other"

        remove(headset, lamp["id"])
        after = receive_until(
            headset,
            lambda event: event["type"] == "state" and piece(event["state"], lamp["id"]) is None,
        )["state"]
        assert after["manipulation"] is None


@pytest.mark.parametrize(
    ("piece_id", "room_version", "code"),
    [
        ("box", 1, "not_furniture"),
        ("furniture_99", 1, "unknown_entity"),
        ("furniture_1", 2, "room_version_mismatch"),
    ],
)
def test_only_placed_furniture_in_this_room_can_be_removed(
    service_url, piece_id, room_version, code
):
    with open_socket(service_url, "mobile_master") as phone:
        phone.recv(timeout=2)
        remove(phone, piece_id, room_version)

        assert error_code(phone) == code


def footprint(entity):
    """(min x, max x, min z, max z) of an unturned piece standing at its position."""
    p, size = entity["position"], entity["size"]
    return (
        p["x"] - size["width"] / 2,
        p["x"] + size["width"] / 2,
        p["z"] - size["depth"] / 2,
        p["z"] + size["depth"] / 2,
    )


def apart(a, b):
    """True when two unturned pieces' footprints don't overlap (touching is fine)."""
    ax0, ax1, az0, az1 = footprint(a)
    bx0, bx1, bz0, bz1 = footprint(b)
    return ax1 <= bx0 + 0.01 or bx1 <= ax0 + 0.01 or az1 <= bz0 + 0.01 or bz1 <= az0 + 0.01


def test_a_piece_placed_on_top_of_another_lands_beside_it_on_the_floor(start_service, tmp_path):
    with start_service(tmp_path) as url, open_socket(url, "vr_solver") as headset:
        ready(headset)
        sofa = placed(headset, "sofa", {"x": 0.0, "y": 0.0, "z": 1.0})
        chair = placed(headset, "chair", {"x": 0.0, "y": 0.0, "z": 1.0}, before={sofa["id"]})
        final = settled(url, headset)

        sofa, chair = final[sofa["id"]], final[chair["id"]]
        assert apart(sofa, chair)
        # Beside the sofa, as near the place asked for as it could be, and on the floor.
        assert math.hypot(chair["position"]["x"], chair["position"]["z"] - 1.0) < 1.2
        assert chair["position"]["y"] == pytest.approx(0.0, abs=0.01)
        assert sofa["position"]["y"] == pytest.approx(0.0, abs=0.01)


def test_a_chair_put_on_a_rug_stays_on_the_rug(start_service, tmp_path):
    with start_service(tmp_path) as url, open_socket(url, "vr_solver") as headset:
        ready(headset)
        rug = placed(headset, "rug", {"x": 0.0, "y": 0.0, "z": 0.5})
        chair = placed(headset, "chair", {"x": 0.2, "y": 0.0, "z": 0.5}, before={rug["id"]})

        assert chair["position"]["x"] == pytest.approx(0.2, abs=0.05)
        assert chair["position"]["z"] == pytest.approx(0.5, abs=0.05)


def test_a_chair_let_go_inside_the_sofa_ends_up_beside_it(start_service, tmp_path):
    with start_service(tmp_path) as url, open_socket(url, "vr_solver") as headset:
        ready(headset)
        sofa = placed(headset, "sofa", {"x": 0.0, "y": 0.0, "z": 1.0})
        chair = placed(headset, "chair", {"x": 1.5, "y": 0.0, "z": -0.2}, before={sofa["id"]})

        hand = {"x": 1.5, "y": 1.0, "z": -0.2}
        headset.send(json.dumps(acquire(hand, entity=chair["id"])))
        identity = receive_until(headset, lambda event: owned_by(event, "vr_solver"))["state"][
            "manipulation"
        ]["id"]
        headset.send(json.dumps(grip(1, {"x": 0.2, "y": 1.0, "z": 1.0}, identity)))
        receive_until(
            headset,
            lambda event: (
                owned_by(event, "vr_solver") and event["state"]["manipulation"]["sequence"] == 1
            ),
        )
        headset.send(json.dumps({"type": "release", "manipulation_id": identity}))
        until_rest(headset)
        final = settled(url, headset)

        assert apart(final[sofa["id"]], final[chair["id"]])


def settled(url, ws):
    """The room's pieces by id, read from the server once this device has been sent nothing for
    a moment: physics reports every move, so a quiet socket means nothing moves."""
    try:
        while True:
            ws.recv(timeout=0.5)
    except TimeoutError:
        pass
    entities = httpx.get(f"{url}/api/room", timeout=5).json()["entities"]
    return {entity["id"]: entity for entity in entities}


def test_a_box_let_go_above_a_table_lands_on_it(start_service, tmp_path):
    with start_service(tmp_path) as url, open_socket(url, "vr_solver") as headset:
        start = ready(headset)
        table = placed(headset, "table", {"x": 0.5, "y": 0.0, "z": 1.0})

        hand = {"x": start["x"], "y": start["y"] + 0.5, "z": start["z"]}
        headset.send(json.dumps(acquire(hand)))
        identity = receive_until(headset, lambda event: owned_by(event, "vr_solver"))["state"][
            "manipulation"
        ]["id"]
        # Over the middle of the table, its bottom 30 cm above the 75 cm top.
        headset.send(json.dumps(grip(1, {"x": 0.5, "y": 1.55, "z": 1.0}, identity)))
        receive_until(
            headset,
            lambda event: (
                owned_by(event, "vr_solver") and event["state"]["manipulation"]["sequence"] == 1
            ),
        )
        headset.send(json.dumps({"type": "release", "manipulation_id": identity}))
        until_rest(headset)
        box = settled(url, headset)["box"]

        assert box["position"]["x"] == pytest.approx(0.5, abs=0.05)
        assert box["position"]["z"] == pytest.approx(1.0, abs=0.05)
        assert box["position"]["y"] == pytest.approx(table["size"]["height"], abs=0.02)


def test_a_chair_fits_in_the_corner_beside_a_turned_sofa(start_service, tmp_path):
    with start_service(tmp_path) as url, open_socket(url, "vr_solver") as headset:
        ready(headset)
        sofa = placed(headset, "sofa", {"x": 0.0, "y": 0.0, "z": 0.5}, yaw=math.pi / 4)
        # The box around the turned sofa reaches here; the sofa itself is 35 cm away.
        chair = placed(headset, "chair", {"x": 0.8, "y": 0.0, "z": 1.3}, before={sofa["id"]})

        assert chair["position"]["x"] == pytest.approx(0.8, abs=0.02)
        assert chair["position"]["z"] == pytest.approx(1.3, abs=0.02)


def test_a_chair_let_go_in_a_tenth_size_dollhouse_settles_at_the_matching_room_point(
    start_service, tmp_path
):
    """The headset turns the fingertip into room metres (#184): a tenth-size dollhouse on a
    table 1 m ahead at 0.8 m, unturned, aligned facing -z with the floor 1.6 m below the eyes.
    A fingertip at (0.1, 0.82, -0.9) is 1 m right, 1 m back and 1.8 m up in the room."""
    with start_service(tmp_path) as url, open_socket(url, "vr_solver") as headset:
        ready(headset)
        chair = placed(headset, "chair", {"x": 1.0, "y": 1.8, "z": 1.0})

        # It fell the 1.8 m to the floor, where the fingertip pointed.
        assert chair["position"]["x"] == pytest.approx(1.0, abs=0.02)
        assert chair["position"]["z"] == pytest.approx(1.0, abs=0.02)
        assert chair["position"]["y"] == pytest.approx(0.0, abs=0.01)
