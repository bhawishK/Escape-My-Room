"""Capture rules the browser cannot exercise, checked against a spawned service process."""

import hashlib
from pathlib import Path
from typing import Any

import httpx

PHOTOS = Path(__file__).resolve().parents[1] / "frontend" / "tests" / "fixtures" / "photos"


def upload(url: str, *names: str, overview: int = 0) -> httpx.Response:
    files = [("images", (name, (PHOTOS / name).read_bytes())) for name in names]
    return httpx.post(
        f"{url}/api/captures",
        files=files,
        data={"overview": str(overview), "instructions": "Desk by the window."},
        timeout=5,
    )


def save_capture(url: str, *names: str, overview: int = 0) -> dict[str, Any]:
    response = upload(url, *names, overview=overview)
    assert response.status_code == 201, response.text
    return response.json()


def test_overview_must_be_one_of_the_uploaded_photos(service_url):
    before = httpx.get(f"{service_url}/api/captures", timeout=5).json()["captures"]
    response = upload(service_url, "overview.png", "desk.jpg", overview=2)
    assert response.status_code == 400
    assert response.json()["detail"] == "Choose one of the selected photos as the overview."
    assert httpx.get(f"{service_url}/api/captures", timeout=5).json()["captures"] == before


def test_changed_overview_must_be_a_photo_in_the_capture(service_url):
    capture = save_capture(service_url, "overview.png", "desk.jpg")
    other = save_capture(service_url, "camera.jpg")
    response = httpx.put(
        f"{service_url}/api/captures/{capture['id']}/overview",
        json={"image_id": other["images"][0]["id"]},
        timeout=5,
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "That photo is not part of this capture."
    kept = httpx.get(f"{service_url}/api/captures/{capture['id']}", timeout=5).json()
    assert kept["overview_image_id"] == capture["images"][0]["id"]


def test_saved_capture_survives_a_service_restart(start_service, tmp_path):
    with start_service(tmp_path) as url:
        capture = save_capture(url, "overview.png", "sideways.jpg", overview=1)
    with start_service(tmp_path) as url:
        listed = httpx.get(f"{url}/api/captures", timeout=5).json()["captures"]
        assert [item["id"] for item in listed] == [capture["id"]]
        restored = httpx.get(f"{url}/api/captures/{capture['id']}", timeout=5).json()
        assert restored == capture
        assert restored["instructions"] == "Desk by the window."
        assert restored["overview_image_id"] == restored["images"][1]["id"]
        for image, name in zip(restored["images"], ("overview.png", "sideways.jpg"), strict=True):
            original = (PHOTOS / name).read_bytes()
            assert image["original_filename"] == name
            assert image["sha256"] == hashlib.sha256(original).hexdigest()
            assert httpx.get(f"{url}{image['original_url']}", timeout=5).content == original
