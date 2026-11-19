"""Throw the box in a room with the server's real physics, and record its flight (#213).

Starts a local server on ROOM_DIR (as the tests do, data in a scratch folder), then, as the
headset, takes the box, carries it to each throw's hand position and lets go at its velocity.
Every state the server sends while the box moves is kept: time, position (bottom centre) and
rotation. `throw_video.mjs` draws them as the headset would.

Usage: python throw_trace.py ROOM_DIR OUT.json
"""

from __future__ import annotations

import json
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from conftest import _service  # noqa: E402
from websockets.sync.client import connect  # noqa: E402

IDENTITY = {"x": 0.0, "y": 0.0, "z": 0.0, "w": 1.0}
# Where the thrower stands (eyes), and each throw: a name, the hand's position, its velocity.
EYE = (1.6, 1.6, 0.25)
THROWS = [
    ("at the far bed", (1.35, 1.25, 0.1), (-2.6, 1.2, -2.0)),
    ("lob onto the far bed", (1.35, 1.25, 0.1), (-1.6, 2.2, -1.3)),
    ("hard at the far bed", (1.35, 1.25, 0.1), (-5.0, 0.5, -3.5)),
    ("at the near bed", (1.35, 1.25, 0.4), (-2.6, 1.2, 2.0)),
    ("hard at the near bed", (1.35, 1.25, 0.4), (-5.0, 0.5, 3.5)),
]
START = {"x": 1.6, "y": 0.0, "z": 0.25}


def entity(state: dict, entity_id: str) -> dict:
    return next(e for e in state["room"]["entities"] if e["id"] == entity_id)


def until(ws, test, timeout: float = 5.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        event = json.loads(ws.recv(timeout=timeout))
        if event.get("type") == "error":
            raise RuntimeError(f"The server refused: {event}")
        if test(event):
            return event
    raise TimeoutError


def drain(ws, seconds: float) -> dict | None:
    """Every message for `seconds`; the last state among them."""
    last, deadline = None, time.monotonic() + seconds
    while (left := deadline - time.monotonic()) > 0:
        try:
            event = json.loads(ws.recv(timeout=left))
        except TimeoutError:
            break
        if event.get("type") == "error":
            raise RuntimeError(f"The server refused: {event}")
        last = event.get("state") or last
    return last


def main() -> None:
    room, out = Path(sys.argv[1]), Path(sys.argv[2])
    with tempfile.TemporaryDirectory() as data, _service(room, Path(data)) as url:
        ws = connect(url.replace("http", "ws") + "/api/ws?role=vr_solver")
        state = until(ws, lambda e: (e.get("state") or {}).get("physics", {}).get("status") == "running"
                      and e["state"]["physics"]["room_version"] is not None, 20)["state"]
        version = state["room"]["room_version"]
        flights = []
        for sequence, (name, hand, velocity) in enumerate(THROWS, start=1):
            ws.send(json.dumps({"type": "entity_transform", "id": "box", "position": START}))
            drain(ws, 1.5)
            ws.send(json.dumps({"type": "acquire", "room_version": version, "id": "box",
                                "position": START, "orientation": IDENTITY}))
            held = until(ws, lambda e: ((e.get("state") or {}).get("manipulation") or {}).get("owner") == "vr_solver")
            identity = held["state"]["manipulation"]["id"]
            ws.send(json.dumps({"type": "grip", "manipulation_id": identity, "sequence": sequence,
                                "position": dict(zip("xyz", hand)), "orientation": IDENTITY}))
            until(ws, lambda e: ((e.get("state") or {}).get("manipulation") or {}).get("id") == identity
                  and e["state"]["manipulation"].get("sequence") == sequence)
            ws.send(json.dumps({"type": "release", "manipulation_id": identity,
                                "velocity": dict(zip("xyz", velocity))}))
            started, frames, moved = time.monotonic(), [], False
            while time.monotonic() - started < 6:
                event = json.loads(ws.recv(timeout=3))
                state = event.get("state")
                if not state:
                    continue
                box = entity(state, "box")
                frames.append({"t": time.monotonic() - started, "position": box["position"],
                               "rotation": box["rotation"]})
                moved = moved or bool(state["physics"]["moving"])
                if moved and not state["physics"]["moving"]:
                    break
            end = frames[-1]["position"]
            print(f"{name}: {len(frames)} states over {frames[-1]['t']:.2f} s, rests at "
                  f"x {end['x']:.2f} y {end['y']:.2f} z {end['z']:.2f}")
            flights.append({"name": name, "hand": hand, "velocity": velocity, "frames": frames})
        box = entity(state, "box")
        out.write_text(json.dumps({"eye": EYE, "box_size": box["size"], "flights": flights}, indent=1))


if __name__ == "__main__":
    main()
