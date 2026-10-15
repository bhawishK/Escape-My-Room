"""Exercise the actual HTTP/WebSocket seam over a running Python process."""

import os
import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def service_url() -> Iterator[str]:
    with _service(ROOT / "assets" / "prepared-room") as url:
        yield url


@pytest.fixture(scope="session")
def multi_asset_service_url() -> Iterator[str]:
    with _service(ROOT / "assets" / "multi-asset-room") as url:
        yield url


@contextmanager
def _service(prepared_dir: Path) -> Iterator[str]:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "backend.app:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--ws-max-size",
            "16384",
        ],
        cwd=ROOT,
        env=os.environ | {"ESCAPE_ROOM_PREPARED_DIR": str(prepared_dir)},
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    url = f"http://127.0.0.1:{port}"
    try:
        for _ in range(100):
            if process.poll() is not None:
                pytest.fail("Diagnostic service exited before startup")
            try:
                if httpx.get(f"{url}/api/health", timeout=0.25).status_code == 200:
                    break
            except httpx.TransportError:
                pass
            time.sleep(0.05)
        else:
            pytest.fail("Diagnostic service did not start within five seconds")
        yield url
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
