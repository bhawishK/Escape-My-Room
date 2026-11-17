"""Generating a piece of furniture from a description (#186), through a spawned service with the
built-in fixture generator. That generator draws a small picture and, for the model, a box 4 m
wide, 2 m tall and 1 m deep whose corner is not at its origin, so sizing and centring show."""

import time
from pathlib import Path
from typing import Any

import httpx
import pytest
from test_furniture import add, furniture
from test_manipulation import open_socket
from test_physics_fall import ready, until_rest

from backend.gltf import read_asset, transform_point

GENERATOR = {"ESCAPE_ROOM_FURNITURE_GENERATOR": "fixture"}


def start(url: str, description: str) -> httpx.Response:
    return httpx.post(f"{url}/api/furniture/jobs", json={"description": description}, timeout=5)


def job(url: str, job_id: str) -> dict[str, Any]:
    return httpx.get(f"{url}/api/furniture/jobs/{job_id}", timeout=5).json()


def wait_for(url: str, job_id: str, states: set[str], timeout: float = 10) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        current = job(url, job_id)
        if current["state"] in states:
            return current
        time.sleep(0.05)
    raise AssertionError(f"Job {job_id} never reached {states}; it is {current['state']}.")


def model_bounds(
    url: str, model_url: str, folder: Path
) -> tuple[tuple[float, ...], tuple[float, ...]]:
    """The served model's bounds in its own frame, around the node the catalogue names."""
    path = folder / "model.glb"
    path.write_bytes(httpx.get(f"{url}{model_url}", timeout=5).content)
    asset = read_asset(path)
    node = asset.find_node("piece")
    assert node is not None
    bounds = asset.local_bounds(node)
    assert bounds is not None
    matrix = asset.local_matrix(node)
    corners = [
        transform_point(matrix, (x, y, z))
        for x in (bounds[0][0], bounds[1][0])
        for y in (bounds[0][1], bounds[1][1])
        for z in (bounds[0][2], bounds[1][2])
    ]
    return tuple(map(min, zip(*corners, strict=True))), tuple(map(max, zip(*corners, strict=True)))


def test_a_description_becomes_an_image_then_a_true_size_piece_in_the_catalogue(
    start_service, tmp_path
):
    with start_service(tmp_path, **GENERATOR) as url:
        response = start(url, "a green mid-century sofa, 2 m long")
        assert response.status_code == 202, response.text
        started = response.json()
        assert started["state"] in ("queued", "image_ready")

        shown = wait_for(url, started["id"], {"image_ready", "ready"})
        image = httpx.get(f"{url}{shown['image_url']}", timeout=5)
        assert image.status_code == 200
        assert image.headers["content-type"] == "image/png"

        done = wait_for(url, started["id"], {"ready"})
        item = done["item"]
        # The 4 m box, 2 m long as asked: half size all round.
        assert item["size"] == {"width": 2.0, "height": 1.0, "depth": 0.5}
        low, high = model_bounds(url, item["model_url"], tmp_path)
        # Its bottom face's centre is the model's origin, as every room entity's is.
        assert low == pytest.approx((-1.0, 0.0, -0.25))
        assert high == pytest.approx((1.0, 1.0, 0.25))
        catalogue = httpx.get(f"{url}/api/furniture", timeout=5).json()["items"]
        assert item in catalogue


def made(url: str, description: str) -> dict[str, Any]:
    """The catalogue piece a finished job made from the description."""
    response = start(url, description)
    assert response.status_code == 202, response.text
    return wait_for(url, response.json()["id"], {"ready"})["item"]


def test_a_made_piece_is_placed_like_a_built_in_one_and_is_still_there_after_a_restart(
    start_service, tmp_path
):
    with start_service(tmp_path, **GENERATOR) as url:
        item = made(url, "a low oak coffee table, 1.2 m long")
        with open_socket(url, "vr_solver") as headset:
            ready(headset)
            add(headset, item["id"], {"x": 0.5, "y": 0.0, "z": 0.8})
            (placed,) = furniture(until_rest(headset)[-1][1])
        assert placed["furniture"] == item["id"]
        assert placed["size"] == item["size"]
        assert placed["asset_url"] == item["model_url"]
        assert placed["node"] == "piece"

    with start_service(tmp_path, **GENERATOR) as url:
        catalogue = httpx.get(f"{url}/api/furniture", timeout=5).json()["items"]
        assert item in catalogue
        assert httpx.get(f"{url}{item['model_url']}", timeout=5).status_code == 200


SIZES = [
    # A size in the description sets the length (the longer side across the floor) or the height.
    ("an armchair, 90 cm tall", {"width": 1.8, "height": 0.9, "depth": 0.45}),
    ("a bookshelf 2 m tall", {"width": 4.0, "height": 2.0, "depth": 1.0}),
    # Wide sets the width and deep the depth, whichever side is longer.
    ("a bookshelf 30 cm deep", {"width": 1.2, "height": 0.6, "depth": 0.3}),
    ("a cabinet 2 m wide", {"width": 2.0, "height": 1.0, "depth": 0.5}),
    # Else the usual size of the kind it names: a lamp is 1.6 m tall, a sofa 2 m long.
    ("a tall brass floor lamp", {"width": 3.2, "height": 1.6, "depth": 0.8}),
    ("a velvet couch", {"width": 2.0, "height": 1.0, "depth": 0.5}),
    # The kind named first wins: a lamp, not the table it stands by.
    ("a lamp next to a table", {"width": 3.2, "height": 1.6, "depth": 0.8}),
    # Else 1 m at its largest.
    ("a strange sculpture", {"width": 1.0, "height": 0.5, "depth": 0.25}),
]


def test_each_piece_is_sized_by_its_description_else_by_its_kind(start_service, tmp_path):
    with start_service(tmp_path, **GENERATOR) as url:
        jobs = [(start(url, description).json()["id"], size) for description, size in SIZES]
        for job_id, size in jobs:
            assert wait_for(url, job_id, {"ready"})["item"]["size"] == pytest.approx(size)


@pytest.mark.parametrize(
    ("fail", "message"),
    [
        ("image", "couldn't make a picture"),
        ("model", "couldn't turn the picture into a 3D piece"),
        ("unreadable", "couldn't be read"),
        ("too_large", "too large to use"),
        ("slow", "took too long"),
        ("quota", "out of GPU time"),
        # A model almost flat can't be sized: a 1.6 m tall lamp would be kilometres wide.
        ("flat", "a strange shape"),
    ],
)
def test_a_failed_job_says_why_plainly_and_adds_nothing(start_service, tmp_path, fail, message):
    settings = GENERATOR | {
        "ESCAPE_ROOM_FIXTURE_GENERATOR_FAIL": fail,
        "ESCAPE_ROOM_FURNITURE_TIMEOUT_SECONDS": "1",
    }
    with start_service(tmp_path, **settings) as url:
        before = httpx.get(f"{url}/api/furniture", timeout=5).json()["items"]
        failed = wait_for(url, start(url, "a chair").json()["id"], {"failed"})

        assert message in failed["error"]
        assert failed["item"] is None
        assert httpx.get(f"{url}/api/furniture", timeout=5).json()["items"] == before


def test_a_cancelled_job_ends_cancelled_and_never_joins_the_catalogue(start_service, tmp_path):
    with start_service(tmp_path, **GENERATOR, ESCAPE_ROOM_FIXTURE_GENERATOR_SECONDS="0.5") as url:
        before = httpx.get(f"{url}/api/furniture", timeout=5).json()["items"]
        job_id = start(url, "a chair").json()["id"]
        wait_for(url, job_id, {"image_ready"})

        cancelled = httpx.post(f"{url}/api/furniture/jobs/{job_id}/cancel", timeout=5).json()
        assert cancelled["state"] == "cancelled"
        # The model step finishes after 0.5 s; the job stays cancelled and nothing is added.
        time.sleep(1.0)
        assert job(url, job_id)["state"] == "cancelled"
        assert httpx.get(f"{url}/api/furniture", timeout=5).json()["items"] == before


def test_a_server_without_a_generator_says_so(service_url):
    response = start(service_url, "a chair")

    assert response.status_code == 503
    assert "isn't set up" in response.json()["detail"]


def test_the_generators_key_never_reaches_the_browser(start_service, tmp_path):
    with start_service(tmp_path, **GENERATOR, HF_TOKEN="hf_secret_never_shown") as url:
        job_id = start(url, "a chair").json()["id"]
        done = wait_for(url, job_id, {"ready"})
        seen = [
            httpx.get(f"{url}/api/furniture/jobs/{job_id}", timeout=5).text,
            httpx.get(f"{url}/api/furniture", timeout=5).text,
            httpx.get(f"{url}{done['item']['model_url']}", timeout=5).text,
        ]
        assert not any("hf_secret_never_shown" in text for text in seen)


def test_one_bad_piece_never_stops_the_next_one(start_service, tmp_path):
    settings = GENERATOR | {"ESCAPE_ROOM_FIXTURE_GENERATOR_FAIL": "flat"}
    with start_service(tmp_path, **settings) as url:
        first = start(url, "a floor lamp").json()["id"]
        second = start(url, "a floor lamp").json()["id"]

        assert wait_for(url, first, {"failed", "ready"})["state"] == "failed"
        # The runner carried on: the next job was made too, and failed the same way.
        assert wait_for(url, second, {"failed", "ready"})["state"] == "failed"
