"""A piece of furniture from the resident's photo (#187), through a spawned service with the
fixture generator, whose 3D step makes a box 4 m wide, 2 m tall and 1 m deep."""

import io
import json
from typing import Any

import httpx
import pytest
from PIL import Image
from test_furniture_generation import GENERATOR, wait_for
from test_manipulation import open_socket, receive_until


def photo(size=(320, 240), colour=(120, 90, 60), format="JPEG") -> bytes:
    out = io.BytesIO()
    Image.new("RGB", size, colour).save(out, format=format)
    return out.getvalue()


def send(url: str, data: bytes, description: str = "", name="chair.jpg") -> httpx.Response:
    return httpx.post(
        f"{url}/api/furniture/jobs/photo",
        files={"image": (name, data, "image/jpeg")},
        data={"description": description},
        timeout=10,
    )


def test_a_photo_becomes_a_true_size_piece_in_the_catalogue(start_service, tmp_path):
    with start_service(tmp_path, **GENERATOR) as url:
        response = send(url, photo(), "an armchair")
        assert response.status_code == 202, response.text
        job: dict[str, Any] = response.json()

        # The photo is the picture: it shows at once, before the 3D piece is made.
        shown = wait_for(url, job["id"], {"image_ready", "ready"})
        picture = httpx.get(f"{url}{shown['image_url']}", timeout=5)
        with Image.open(io.BytesIO(picture.content)) as image:
            assert image.size == (320, 240)

        item = wait_for(url, job["id"], {"ready"})["item"]
        # An armchair is 0.9 m tall: the 2 m tall box at 0.45 of its size.
        assert item["size"] == pytest.approx({"width": 1.8, "height": 0.9, "depth": 0.45})
        assert item["name"] == "An armchair"
        assert item in httpx.get(f"{url}/api/furniture", timeout=5).json()["items"]


def test_a_photo_without_a_description_is_a_piece_a_metre_at_its_largest(start_service, tmp_path):
    with start_service(tmp_path, **GENERATOR) as url:
        job = send(url, photo()).json()
        item = wait_for(url, job["id"], {"ready"})["item"]

        assert item["size"] == pytest.approx({"width": 1.0, "height": 0.5, "depth": 0.25})
        assert item["name"] == "Piece from a photo"


def test_a_file_that_isnt_a_photo_or_is_too_big_is_refused_by_the_photo_rules(
    start_service, tmp_path
):
    settings = GENERATOR | {"ESCAPE_ROOM_CAPTURE_MAX_IMAGE_BYTES": "20000"}
    with start_service(tmp_path, **settings) as url:
        not_a_photo = send(url, b"these are not the pixels you are looking for")
        assert not_a_photo.status_code == 400
        assert "JPEG or PNG" in not_a_photo.json()["detail"]

        noisy = Image.effect_noise((400, 400), 120).convert("RGB")
        big = io.BytesIO()
        noisy.save(big, format="PNG")
        too_big = send(url, big.getvalue(), name="noise.png")
        assert too_big.status_code == 413


def test_a_photo_job_that_fails_says_why_and_adds_nothing(start_service, tmp_path):
    settings = GENERATOR | {"ESCAPE_ROOM_FIXTURE_GENERATOR_FAIL": "model"}
    with start_service(tmp_path, **settings) as url:
        before = httpx.get(f"{url}/api/furniture", timeout=5).json()["items"]
        failed = wait_for(url, send(url, photo()).json()["id"], {"failed"})

        assert "couldn't turn the picture into a 3D piece" in failed["error"]
        assert httpx.get(f"{url}/api/furniture", timeout=5).json()["items"] == before


def test_the_headset_is_told_when_a_new_piece_joins_the_catalogue(start_service, tmp_path):
    with start_service(tmp_path, **GENERATOR) as url, open_socket(url, "vr_solver") as headset:
        before = json.loads(headset.recv(timeout=2))["state"]["catalogue_version"]
        job = send(url, photo(), "a chair").json()
        wait_for(url, job["id"], {"ready"})

        told = receive_until(
            headset,
            lambda event: event["type"] == "state" and event["state"]["catalogue_version"] > before,
        )
        assert told["state"]["catalogue_version"] == before + 1


def test_a_large_photo_is_made_no_larger_than_1024_px_for_the_3d_step(start_service, tmp_path):
    with start_service(tmp_path, **GENERATOR) as url:
        job = send(url, photo(size=(2000, 1500)), "a chair").json()
        picture = httpx.get(f"{url}{job['image_url']}", timeout=5)

        with Image.open(io.BytesIO(picture.content)) as image:
            assert image.size == (1024, 768)
