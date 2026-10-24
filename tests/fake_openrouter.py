"""A stand-in for OpenRouter's chat completions endpoint that replays scripted replies.

Tests queue replies and read back every request it received, so the service under test talks to
real HTTP without a key, a model or any spending.
"""

import json
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


@dataclass
class Received:
    headers: dict[str, str]
    body: dict[str, Any]


@dataclass
class FakeOpenRouter:
    url: str
    replies: list[tuple[int, dict[str, Any]]] = field(default_factory=lambda: [])
    received: list[Received] = field(default_factory=lambda: [])

    def answer(self, text: str, *, finish_reason: str = "stop", cost: float = 0.0004) -> None:
        """Queue a successful completion carrying `text`."""
        self.replies.append(
            (
                200,
                {
                    "id": f"gen-{len(self.replies) + 1}",
                    "model": "qwen/qwen3-vl-8b-instruct",
                    "provider": "FakeProvider",
                    "choices": [
                        {
                            "finish_reason": finish_reason,
                            "message": {"role": "assistant", "content": text},
                        }
                    ],
                    "usage": {"prompt_tokens": 1200, "completion_tokens": 40, "cost": cost},
                },
            )
        )

    def fail(self, status: int, message: str) -> None:
        """Queue an error reply shaped like OpenRouter's."""
        self.replies.append((status, {"error": {"code": status, "message": message}}))


@contextmanager
def fake_openrouter() -> Iterator[FakeOpenRouter]:
    fake: FakeOpenRouter

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(length) or b"{}")
            fake.received.append(Received(dict(self.headers.items()), body))
            if self.path != "/api/v1/chat/completions":
                status, reply = 404, {"error": {"code": 404, "message": "Not found"}}
            elif fake.replies:
                status, reply = fake.replies.pop(0)
            else:
                status, reply = 500, {"error": {"code": 500, "message": "No reply queued"}}
            data = json.dumps(reply).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, format: str, *args: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    fake = FakeOpenRouter(f"http://127.0.0.1:{server.server_address[1]}/api/v1")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield fake
    finally:
        server.shutdown()
        server.server_close()
