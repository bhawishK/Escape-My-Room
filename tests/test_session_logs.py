"""Session logs (#259): each drill run recorded, positions and guidance only, for studies.

WebSocket and HTTP seams, real service; the fire is one already made, kept on disk."""

import json
import time
from typing import Any

import httpx
from test_manipulation import open_socket, receive_until
from test_session_hazards import ASSET, made_hazard


def send(ws, message: dict[str, Any]) -> None:
    ws.send(json.dumps(message))


def presence(sequence: int, x: float, z: float, heading: float = 0.0) -> dict[str, Any]:
    return {
        "type": "presence",
        "sequence": sequence,
        "tracking_status": "tracked",
        "position": {"x": x, "y": 0.0, "z": z},
        "heading": heading,
    }


def started(headset, phone) -> str:
    """Adds the kept fire and starts it; its id in the room."""
    send(headset, {"type": "add_hazard", "room_version": 1, "asset": ASSET})
    state = receive_until(
        phone, lambda e: e["type"] in ("welcome", "state") and e["state"]["room"]["hazards"]
    )["state"]
    hazard_id = state["room"]["hazards"][-1]["id"]
    send(headset, {"type": "start_hazard", "room_version": 1, "id": hazard_id})
    receive_until(
        phone,
        lambda e: e["type"] == "state" and any(h["playing"] for h in e["state"]["room"]["hazards"]),
    )
    return hazard_id


def until(ws, predicate, tries: int = 200) -> dict[str, Any]:
    """The first message that matches, past however many states the presence floods bring."""
    for _ in range(tries):
        event = json.loads(ws.recv(timeout=5))
        if predicate(event):
            return event
    raise AssertionError("Expected message was not received")


def logs(url: str) -> list[dict[str, Any]]:
    return httpx.get(f"{url}/api/session-logs", timeout=5).json()["runs"]


def lines(url: str, run_id: str) -> list[dict[str, Any]]:
    text = httpx.get(f"{url}/api/session-logs/{run_id}", timeout=5).text
    return [json.loads(line) for line in text.splitlines() if line]


def test_a_drill_run_is_logged_from_start_to_stop_and_summarised(start_service, tmp_path):
    made_hazard(tmp_path)
    with (
        start_service(tmp_path) as url,
        open_socket(url, "vr_solver") as headset,
        open_socket(url, "mobile_master") as phone,
    ):
        assert logs(url) == []
        hazard_id = started(headset, phone)
        # The occupant walks 1 m then 1 m more; the commander points at the door meanwhile.
        for sequence, (x, z) in enumerate([(0.0, 0.0), (0.0, -1.0), (1.0, -1.0)], start=1):
            send(phone, presence(sequence, x, z))
            time.sleep(0.25)
        send(headset, {"type": "guide", "sequence": 1, "spot": {"x": 2.0, "y": 0.0, "z": -1.0}})
        time.sleep(0.25)
        send(headset, {"type": "guide", "sequence": 2, "spot": None})
        time.sleep(0.1)
        send(headset, {"type": "stop_hazard", "room_version": 1, "id": hazard_id})
        receive_until(
            phone,
            lambda e: (
                e["type"] == "state"
                and not any(h["playing"] for h in e["state"]["room"]["hazards"])
            ),
        )

        (run,) = logs(url)
        assert run["object"] == "box" and run["hazard"] == "catches fire"
        assert run["ended"] == "stopped"
        assert run["occupant_path_metres"] == 2.0
        assert 0 < run["guided_share"] < 1
        assert run["seconds"] > 0.5

        logged = lines(url, run["id"])
        assert logged[0]["kind"] == "run" and logged[0]["event"] == "started"
        assert logged[-1]["kind"] == "run" and logged[-1]["event"] == "ended"
        times = [line["t"] for line in logged]
        assert times == sorted(times)
        walked = [
            (line["position"]["x"], line["position"]["z"])
            for line in logged
            if line["kind"] == "presence" and line["role"] == "mobile_master"
        ]
        assert walked == [(0.0, 0.0), (0.0, -1.0), (1.0, -1.0)]
        guides = [line["spot"] for line in logged if line["kind"] == "guide"]
        assert guides == [{"x": 2.0, "y": 0.0, "z": -1.0}, None]
        hazards = [line["event"] for line in logged if line["kind"] == "hazard"]
        assert hazards == ["started", "stopped"]
        # Positions and guidance only: no pictures, sound or video.
        assert {line["kind"] for line in logged} <= {"run", "presence", "guide", "hand", "hazard"}


def test_presence_sent_twenty_times_a_second_is_logged_at_most_five(start_service, tmp_path):
    made_hazard(tmp_path)
    with (
        start_service(tmp_path) as url,
        open_socket(url, "vr_solver") as headset,
        open_socket(url, "mobile_master") as phone,
    ):
        hazard_id = started(headset, phone)
        for sequence in range(1, 21):
            send(phone, presence(sequence, sequence * 0.01, 0.0))
            time.sleep(0.05)
        send(headset, {"type": "remove_hazard", "room_version": 1, "id": hazard_id})
        until(phone, lambda e: e["type"] == "state" and not e["state"]["room"]["hazards"])
        (run,) = logs(url)
        assert run["ended"] == "removed"
        phone_lines = [
            line
            for line in lines(url, run["id"])
            if line["kind"] == "presence" and line["role"] == "mobile_master"
        ]
        assert 3 <= len(phone_lines) <= 6


def test_with_logging_off_nothing_is_written(start_service, tmp_path):
    made_hazard(tmp_path)
    with (
        start_service(tmp_path, ESCAPE_ROOM_SESSION_LOGS="0") as url,
        open_socket(url, "vr_solver") as headset,
        open_socket(url, "mobile_master") as phone,
    ):
        hazard_id = started(headset, phone)
        send(phone, presence(1, 0.0, 0.0))
        send(headset, {"type": "stop_hazard", "room_version": 1, "id": hazard_id})
        receive_until(
            phone,
            lambda e: (
                e["type"] == "state"
                and not any(h["playing"] for h in e["state"]["room"]["hazards"])
            ),
        )
        assert logs(url) == []
    assert not (tmp_path / "session-logs").exists() or not any(
        (tmp_path / "session-logs").iterdir()
    )


def test_an_unknown_or_malformed_log_is_not_found(start_service, tmp_path):
    with start_service(tmp_path) as url:
        assert httpx.get(f"{url}/api/session-logs/../../etc", timeout=5).status_code == 404
        assert (
            httpx.get(f"{url}/api/session-logs/20261123T000000Z-abcdef", timeout=5).status_code
            == 404
        )
