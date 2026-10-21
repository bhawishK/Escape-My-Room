"""Movement logs a phone sends during device checks, saved where the developer can read them."""

import json

import httpx


def test_a_sent_movement_log_is_saved_as_sent(start_service, tmp_path):
    log = {
        "user_agent": "iPhone test",
        "entries": [
            {"t": 0, "kind": "event", "name": "mode", "detail": "measured"},
            {"t": 100, "kind": "pose", "mode": "measured", "x": 0.4, "y": 1.62, "z": 0.9},
        ],
    }
    with start_service(tmp_path) as url:
        response = httpx.post(f"{url}/api/movement-logs", json=log, timeout=5)
    assert response.status_code == 201, response.text
    saved = list((tmp_path / "movement-logs").glob("*.json"))
    assert [path.name for path in saved] == [response.json()["file"]]
    assert json.loads(saved[0].read_text(encoding="utf-8")) == log
    assert response.json()["entries"] == 2


def test_a_log_without_entries_or_too_large_is_refused(start_service, tmp_path):
    with start_service(tmp_path) as url:
        no_entries = httpx.post(f"{url}/api/movement-logs", json={"user_agent": "x"}, timeout=5)
        too_large = httpx.post(
            f"{url}/api/movement-logs",
            json={"entries": [{"t": 0, "note": "x" * 4_000_000}]},
            timeout=5,
        )
    assert no_entries.status_code == 400
    assert no_entries.json()["detail"] == "A movement log needs a list of entries."
    assert too_large.status_code == 413
    assert not list((tmp_path / "movement-logs").glob("*.json"))
