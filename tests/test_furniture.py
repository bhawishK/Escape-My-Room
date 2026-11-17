"""Catalogue furniture both devices see at true size (#181); HTTP and WebSocket seams, real Havok.
"""

import json
import math

import httpx
import pytest
from test_live_room import activate, next_state, reconstructed
from test_manipulation import error_code, open_socket, receive_until
from test_physics_fall import ready, until_rest
from test_reconstruction_jobs import settings

# The built-in pieces and their true sizes in metres, as the catalogue promises them.
CATALOGUE = {
    "sofa": (2.0, 0.9, 0.85),
    "armchair": (0.85, 0.85, 0.9),
    "table": (1.4, 0.8, 0.75),
    "chair": (0.45, 0.5, 0.9),
    "lamp": (0.35, 0.35, 1.6),
    "shelf": (0.8, 0.35, 1.8),
    "rug": (2.0, 1.4, 0.01),
}


def catalogue(url):
    return httpx.get(f"{url}/api/furniture", timeout=5).json()["items"]


def test_the_catalogue_lists_each_piece_with_its_true_size_and_a_model_to_draw(service_url):
    items = catalogue(service_url)

    sizes = {
        item["id"]: (item["size"]["width"], item["size"]["depth"], item["size"]["height"])
        for item in items
    }
    assert sizes == CATALOGUE
    for item in items:
        assert item["name"]
        model = httpx.get(f"{service_url}{item['model_url']}", timeout=5)
        assert model.status_code == 200


def furniture(state):
    return [entity for entity in state["room"]["entities"] if entity.get("furniture")]


def add(ws, item, position, yaw=0.0, room_version=1):
    ws.send(
        json.dumps(
            {
                "type": "add_furniture",
                "room_version": room_version,
                "item": item,
                "position": position,
                "yaw": yaw,
            }
        )
    )


def test_a_placed_armchair_falls_to_the_floor_at_true_size_and_both_devices_see_it(
    start_service, tmp_path
):
    with (
        start_service(tmp_path) as url,
        open_socket(url, "vr_solver") as headset,
        open_socket(url, "mobile_master") as phone,
    ):
        ready(headset)
        add(headset, "armchair", {"x": 1.0, "y": 0.5, "z": 0.6}, yaw=math.pi / 2)
        states = until_rest(headset)

        (armchair,) = furniture(states[-1][1])
        assert armchair["furniture"] == "armchair"
        assert armchair["kind"] == "movable" and armchair["selectable"]
        assert armchair["size"] == {"width": 0.85, "height": 0.9, "depth": 0.85}
        # It fell 0.5 m and stands on the floor, whose top is at 0, where it was put, turned left.
        assert armchair["position"]["y"] == pytest.approx(0.0, abs=0.01)
        assert armchair["position"]["x"] == pytest.approx(1.0, abs=0.02)
        assert armchair["position"]["z"] == pytest.approx(0.6, abs=0.02)
        assert armchair["rotation"]["y"] == pytest.approx(math.sin(math.pi / 4), abs=0.01)
        assert armchair["rotation"]["w"] == pytest.approx(math.cos(math.pi / 4), abs=0.01)
        assert states[-1][1]["physics"]["bodies"]["dynamic"] == 2
        # The phone was sent it too.
        seen = receive_until(
            phone, lambda event: event["type"] == "state" and furniture(event["state"])
        )
        assert furniture(seen["state"])[0]["id"] == armchair["id"]


@pytest.mark.parametrize(
    ("item", "position", "room_version", "code"),
    [
        ("throne", {"x": 0.0, "y": 0.0, "z": 0.5}, 1, "unknown_furniture"),
        # The floor is 4 m square around the origin.
        ("chair", {"x": 2.5, "y": 0.0, "z": 0.0}, 1, "outside_room"),
        ("chair", {"x": 0.0, "y": 0.0, "z": -2.1}, 1, "outside_room"),
        # Its centre is on the floor, but the 2 m sofa would hang 0.1 m over the edge.
        ("sofa", {"x": 1.1, "y": 0.0, "z": 0.0}, 1, "outside_room"),
        ("chair", {"x": 0.0, "y": 0.0, "z": 0.5}, 2, "room_version_mismatch"),
    ],
)
def test_a_piece_that_is_unknown_off_the_floor_or_for_another_room_is_refused_and_not_placed(
    service_url, item, position, room_version, code
):
    with open_socket(service_url, "vr_solver") as headset:
        headset.recv(timeout=2)
        add(headset, item, position, room_version=room_version)

        assert error_code(headset) == code
    assert not [entity for entity in room(service_url)["entities"] if entity.get("furniture")]


def test_a_sofa_turned_a_quarter_fits_where_it_would_not_fit_lengthways(start_service, tmp_path):
    with start_service(tmp_path) as url, open_socket(url, "vr_solver") as headset:
        headset.recv(timeout=2)
        # Turned, its 2 m length runs along z, and 0.45 m either side of x = 1.5 is on the floor.
        add(headset, "sofa", {"x": 1.5, "y": 0.0, "z": 0.8}, yaw=math.pi / 2)

        receive_until(headset, lambda event: event["type"] == "state" and furniture(event["state"]))


def test_only_the_headset_places_furniture(service_url):
    with open_socket(service_url, "mobile_master") as phone:
        phone.recv(timeout=2)
        add(phone, "chair", {"x": 0.0, "y": 0.0, "z": 0.5})

        assert error_code(phone) == "role_forbidden"


def test_a_room_holds_at_most_24_pieces(start_service, tmp_path):
    with start_service(tmp_path) as url, open_socket(url, "vr_solver") as headset:
        headset.recv(timeout=2)
        # Rugs side by side, 0.5 m apart, on the 4 m floor.
        for index in range(24):
            add(
                headset,
                "rug",
                {"x": -1.0 + (index % 5) * 0.5, "y": 0.0, "z": -1.25 + (index // 5) * 0.5},
            )
        add(headset, "rug", {"x": 0.0, "y": 0.0, "z": 0.0})

        assert error_code(headset) == "too_much_furniture"
        assert len([entity for entity in room(url)["entities"] if entity.get("furniture")]) == 24


def room(url):
    return httpx.get(f"{url}/api/room", timeout=5).json()


def test_a_device_that_joins_later_gets_the_furniture_where_it_came_to_rest(
    start_service, tmp_path
):
    with start_service(tmp_path) as url:
        with open_socket(url, "vr_solver") as headset:
            ready(headset)
            add(headset, "sofa", {"x": -0.5, "y": 0.3, "z": 1.2})
            (rested,) = furniture(until_rest(headset)[-1][1])
        with open_socket(url, "mobile_master") as phone:
            welcome = json.loads(phone.recv(timeout=2))

    assert welcome["type"] == "welcome"
    (sofa,) = furniture(welcome["state"])
    assert sofa["furniture"] == "sofa"
    assert sofa["position"] == rested["position"]
    assert sofa["position"]["y"] == pytest.approx(0.0, abs=0.01)


def test_making_another_room_live_clears_the_furniture(start_service, tmp_path):
    with start_service(tmp_path, **settings()) as url:
        job = reconstructed(url)
        with open_socket(url, "vr_solver") as headset:
            ready(headset)
            add(headset, "lamp", {"x": 0.5, "y": 0.0, "z": 0.5})
            receive_until(
                headset, lambda event: event["type"] == "state" and furniture(event["state"])
            )

            assert activate(url, job).status_code == 200
            state = next_state(headset, 2)

        assert not furniture(state)
        assert not [entity for entity in room(url)["entities"] if entity.get("furniture")]
