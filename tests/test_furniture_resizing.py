"""Resizing a placed piece of furniture (#202); WebSocket seam, real Havok worker."""

import json

import pytest
from test_furniture_arranging import apart, piece, placed, settled
from test_manipulation import error_code, open_socket, receive_until
from test_physics_fall import ready, until_rest
from test_solver_grab import acquire, grip, owned_by

# The table's catalogue size, in metres.
TABLE = {"width": 1.4, "height": 0.75, "depth": 0.8}


def resize(ws, piece_id, scale, final=True, room_version=1):
    ws.send(
        json.dumps(
            {
                "type": "resize_furniture",
                "room_version": room_version,
                "id": piece_id,
                "scale": scale,
                "final": final,
            }
        )
    )


def resized(ws, piece_id, scale):
    """The first state with the piece at `scale`."""
    return receive_until(
        ws,
        lambda event: (
            event["type"] == "state"
            and (piece(event["state"], piece_id) or {}).get("scale") == pytest.approx(scale)
        ),
    )["state"]


def test_a_table_resized_to_twice_its_size_grows_evenly_for_both_devices(
    start_service, tmp_path
):
    with (
        start_service(tmp_path) as url,
        open_socket(url, "vr_solver") as headset,
        open_socket(url, "mobile_master") as phone,
    ):
        ready(headset)
        table = placed(headset, "table", {"x": 0.5, "y": 0.0, "z": 1.0})
        resize(headset, table["id"], 1.5)

        grown = piece(resized(phone, table["id"], 1.5), table["id"])
        assert grown["size"] == pytest.approx({key: value * 1.5 for key, value in TABLE.items()})
        # Grown from where it stands: still on the floor, in the same place.
        assert grown["position"] == pytest.approx(table["position"], abs=0.01)


def test_a_new_scale_is_of_the_catalogue_size_and_kept_within_a_quarter_and_three_times(
    start_service, tmp_path
):
    with start_service(tmp_path) as url, open_socket(url, "vr_solver") as headset:
        ready(headset)
        table = placed(headset, "table", {"x": 0.0, "y": 0.0, "z": 0.0})

        resize(headset, table["id"], 1.2)
        resized(headset, table["id"], 1.2)
        resize(headset, table["id"], 0.5)
        half = piece(resized(headset, table["id"], 0.5), table["id"])
        assert half["size"]["width"] == pytest.approx(0.7)

        resize(headset, table["id"], 0.1)
        assert piece(resized(headset, table["id"], 0.25), table["id"])["size"][
            "width"
        ] == pytest.approx(0.35)
        resize(headset, table["id"], 2.9, final=False)
        resized(headset, table["id"], 2.9)
        resize(headset, table["id"], 10, final=False)
        assert piece(resized(headset, table["id"], 3.0), table["id"])["size"][
            "height"
        ] == pytest.approx(2.25)


def test_a_box_let_go_above_a_grown_table_lands_on_its_new_top(start_service, tmp_path):
    with start_service(tmp_path) as url, open_socket(url, "vr_solver") as headset:
        start = ready(headset)
        table = placed(headset, "table", {"x": 0.5, "y": 0.0, "z": 1.0})
        resize(headset, table["id"], 1.6)
        resized(headset, table["id"], 1.6)

        hand = {"x": start["x"], "y": start["y"] + 0.5, "z": start["z"]}
        headset.send(json.dumps(acquire(hand)))
        identity = receive_until(headset, lambda event: owned_by(event, "vr_solver"))["state"][
            "manipulation"
        ]["id"]
        # Over the middle of the table, its bottom 30 cm above the new 1.2 m top.
        headset.send(json.dumps(grip(1, {"x": 0.5, "y": 2.0, "z": 1.0}, identity)))
        receive_until(
            headset,
            lambda event: (
                owned_by(event, "vr_solver") and event["state"]["manipulation"]["sequence"] == 1
            ),
        )
        headset.send(json.dumps({"type": "release", "manipulation_id": identity}))
        until_rest(headset)
        box = settled(url, headset)["box"]

        assert box["position"]["y"] == pytest.approx(TABLE["height"] * 1.6, abs=0.02)


def test_a_table_grown_into_a_chair_is_put_beside_it_when_the_resize_ends(
    start_service, tmp_path
):
    with start_service(tmp_path) as url, open_socket(url, "vr_solver") as headset:
        ready(headset)
        table = placed(headset, "table", {"x": 0.0, "y": 0.0, "z": 0.5})
        chair = placed(headset, "chair", {"x": 1.2, "y": 0.0, "z": 0.5}, before={table["id"]})

        # While the hands still move, it may pass through; let go, it moves out of the chair.
        resize(headset, table["id"], 2.0, final=False)
        resized(headset, table["id"], 2.0)
        resize(headset, table["id"], 2.0, final=True)
        until_rest(headset)
        final = settled(url, headset)

        assert final[table["id"]]["scale"] == pytest.approx(2.0)
        assert apart(final[table["id"]], final[chair["id"]])


def test_a_piece_the_other_person_holds_cant_be_resized(start_service, tmp_path):
    with (
        start_service(tmp_path) as url,
        open_socket(url, "vr_solver") as headset,
        open_socket(url, "mobile_master") as phone,
    ):
        ready(headset)
        lamp = placed(headset, "lamp", {"x": 1.0, "y": 0.0, "z": 1.0})
        headset.send(json.dumps(acquire({"x": 1.0, "y": 1.0, "z": 1.0}, entity=lamp["id"])))
        receive_until(headset, lambda event: owned_by(event, "vr_solver"))

        resize(phone, lamp["id"], 2.0)
        assert error_code(phone) == "controlled_by_other"


@pytest.mark.parametrize(
    ("piece_id", "room_version", "code"),
    [
        ("box", 1, "not_furniture"),
        ("furniture_99", 1, "unknown_entity"),
        ("furniture_1", 2, "room_version_mismatch"),
    ],
)
def test_only_placed_furniture_in_this_room_can_be_resized(
    service_url, piece_id, room_version, code
):
    with open_socket(service_url, "vr_solver") as headset:
        headset.recv(timeout=2)
        resize(headset, piece_id, 2.0, room_version=room_version)

        assert error_code(headset) == code
