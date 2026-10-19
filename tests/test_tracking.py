"""Camera calibrations the phone saves for marker tracking, through a spawned service."""

import json

import httpx
import pytest

CALIBRATION = {
    "width": 1280,
    "height": 720,
    "fx": 1012.5,
    "fy": 1010.25,
    "cx": 641.0,
    "cy": 358.5,
    "distortion": [0.08, -0.21, 0.0, 0.0, 0.0],
    "rms_px": 0.42,
    "views": 15,
    "user_agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 26_6_1 like Mac OS X) CriOS/155.0",
}


def cameras(url: str) -> list[dict]:
    response = httpx.get(f"{url}/api/tracking/cameras", timeout=5)
    assert response.status_code == 200
    return response.json()["calibrations"]


def save(url: str, calibration: dict) -> httpx.Response:
    return httpx.put(f"{url}/api/tracking/cameras", json=calibration, timeout=5)


def test_saved_calibration_survives_a_restart_and_is_replaced_per_resolution(
    start_service, tmp_path
):
    with start_service(tmp_path) as url:
        assert cameras(url) == []
        response = save(url, CALIBRATION)
        assert response.status_code == 200
        stored = response.json()
        assert {key: stored[key] for key in CALIBRATION} == CALIBRATION
        assert stored["recorded_at"]
        portrait = CALIBRATION | {"width": 720, "height": 1280, "cx": 359.0, "cy": 640.5}
        assert save(url, portrait).status_code == 200
    with start_service(tmp_path) as url:
        assert [(item["width"], item["height"]) for item in cameras(url)] == [
            (1280, 720),
            (720, 1280),
        ]
        assert save(url, CALIBRATION | {"fx": 1000.0, "fy": 1000.0}).status_code == 200
        landscape = [item for item in cameras(url) if item["width"] == 1280]
        assert [item["fx"] for item in landscape] == [1000.0]


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"rms_px": 2.5}, "Calibration error is 2.50 px"),
        ({"cx": 1400.0}, "principal point"),
        ({"cy": -1.0}, "principal point"),
        ({"fx": 0.0}, "Send a camera calibration"),
        ({"distortion": [0.1, 0.2]}, "Send a camera calibration"),
        ({"views": 3}, "Send a camera calibration"),
        ({"fx": float("nan")}, "Send a camera calibration"),
        ({"surprise": True}, "Send a camera calibration"),
    ],
)
def test_unusable_calibration_is_refused(service_url, change, message):
    # json.dumps writes NaN as a bare token, as a misbehaving client could.
    response = httpx.put(
        f"{service_url}/api/tracking/cameras",
        content=json.dumps(CALIBRATION | change),
        headers={"content-type": "application/json"},
        timeout=5,
    )
    assert response.status_code == 400
    assert message in response.json()["detail"]
    assert all(item["rms_px"] < 2.0 for item in cameras(service_url))
