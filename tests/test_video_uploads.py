"""Room video uploads (#136) against a spawned service: chunks of any order make one video capture,
and the reasons a video is refused. The service's fixture probe stands in for ffprobe: it reads
ffprobe's JSON stored after a real MP4 header, so the real parsing is used."""

import hashlib
import json
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
from conftest import StartService

CHUNK = 1024
# The 20-byte start of an MP4 file: its `ftyp` box.
MP4_HEADER = b"\x00\x00\x00\x14ftypisom\x00\x00\x02\x00isom"


def fixture_video(seconds: float = 83.4, size: int = 3000) -> bytes:
    """A file the fixture probe reads as a portrait 1080p video `seconds` long, `size` bytes."""
    probe = {
        "streams": [
            {
                "codec_type": "video",
                "codec_name": "h264",
                "width": 1920,
                "height": 1080,
                "avg_frame_rate": "30/1",
                "side_data_list": [{"rotation": 90}],
            }
        ],
        "format": {"format_name": "mov,mp4,m4a,3gp,3g2,mj2", "duration": str(seconds)},
    }
    data = MP4_HEADER + json.dumps(probe).encode()
    return data + b" " * (size - len(data))


@pytest.fixture
def service(start_service: StartService, tmp_path: Path) -> Iterator[str]:
    with start_service(
        tmp_path,
        ESCAPE_ROOM_VIDEO_PROBE="fixture",
        ESCAPE_ROOM_VIDEO_CHUNK_BYTES=str(CHUNK),
        ESCAPE_ROOM_VIDEO_MAX_BYTES=str(64 * 1024),
        ESCAPE_ROOM_VIDEO_MAX_SECONDS="300",
    ) as url:
        yield url


def start(url: str, video: bytes, name: str = "room.mov", kind: str = "video/quicktime"):
    return httpx.post(
        f"{url}/api/videos",
        json={"filename": name, "size_bytes": len(video), "media_type": kind},
        timeout=5,
    )


def send(url: str, upload_id: str, number: int, data: bytes) -> httpx.Response:
    return httpx.put(f"{url}/api/videos/{upload_id}/chunks/{number}", content=data, timeout=5)


def chunks(video: bytes) -> list[bytes]:
    return [video[i : i + CHUNK] for i in range(0, len(video), CHUNK)]


def test_chunks_sent_in_any_order_become_one_video_capture(service: str) -> None:
    video = fixture_video()
    begun = start(service, video)
    assert begun.status_code == 201, begun.text
    upload = begun.json()
    assert upload["chunk_bytes"] == CHUNK

    parts = chunks(video)
    for number in (2, 0, 1):
        assert send(service, upload["id"], number, parts[number]).status_code == 204
    done = httpx.post(
        f"{service}/api/videos/{upload['id']}/complete",
        json={"instructions": "Walk round the desk."},
        timeout=5,
    )

    assert done.status_code == 201, done.text
    capture = done.json()
    assert capture["kind"] == "video"
    assert capture["original_filename"] == "room.mov"
    assert capture["size_bytes"] == 3000
    assert capture["sha256"] == hashlib.sha256(video).hexdigest()
    assert capture["instructions"] == "Walk round the desk."
    assert capture["video"] == {
        "seconds": 83.4,
        "width": 1080,
        "height": 1920,
        "frames_per_second": 30.0,
        "codec": "h264",
    }
    listed = httpx.get(f"{service}/api/captures", timeout=5).json()["captures"]
    assert [(c["id"], c["kind"]) for c in listed] == [(capture["id"], "video")]


def test_a_missing_chunk_is_named_and_the_upload_can_finish_after_a_retry(service: str) -> None:
    video = fixture_video()
    upload = start(service, video).json()
    parts = chunks(video)
    send(service, upload["id"], 0, parts[0])
    send(service, upload["id"], 2, parts[2])

    early = httpx.post(f"{service}/api/videos/{upload['id']}/complete", json={}, timeout=5)
    assert early.status_code == 409
    assert early.json()["detail"] == "1 of 3 chunks have not arrived yet, starting with chunk 1."

    # The retry of a chunk that already arrived, then the missing one.
    assert send(service, upload["id"], 0, parts[0]).status_code == 204
    assert send(service, upload["id"], 1, parts[1]).status_code == 204
    done = httpx.post(f"{service}/api/videos/{upload['id']}/complete", json={}, timeout=5)
    assert done.status_code == 201, done.text
    assert done.json()["sha256"] == hashlib.sha256(video).hexdigest()


@pytest.mark.parametrize(
    ("name", "kind", "size", "status", "reason"),
    [
        ("big.mov", "video/quicktime", 65 * 1024, 413, "big.mov is 65 KB; the limit is 64 KB."),
        (
            "room.webm",
            "video/webm",
            3000,
            415,
            "Upload an MP4 or MOV video; room.webm is video/webm.",
        ),
        ("empty.mp4", "video/mp4", 0, 400, "empty.mp4 is empty."),
    ],
)
def test_a_video_too_large_empty_or_of_another_type_is_refused_before_any_chunk(
    service: str, name: str, kind: str, size: int, status: int, reason: str
) -> None:
    response = start(service, b"x" * size, name, kind)

    assert response.status_code == status
    assert response.json()["detail"] == reason


def test_a_video_too_long_is_refused_and_leaves_no_capture(service: str) -> None:
    video = fixture_video(seconds=301)
    upload = start(service, video).json()
    for number, part in enumerate(chunks(video)):
        send(service, upload["id"], number, part)

    done = httpx.post(f"{service}/api/videos/{upload['id']}/complete", json={}, timeout=5)

    assert done.status_code == 413
    assert done.json()["detail"] == "room.mov is 5 min 1 s long; keep it under 5 min 0 s."
    assert httpx.get(f"{service}/api/captures", timeout=5).json()["captures"] == []


def test_a_chunk_of_the_wrong_size_is_refused(service: str) -> None:
    upload = start(service, fixture_video()).json()

    response = send(service, upload["id"], 1, b"x" * 10)

    assert response.status_code == 400
    assert response.json()["detail"] == "Chunk 1 should be 1024 bytes; 10 came."


def test_finishing_again_after_a_lost_answer_gives_the_same_capture(service: str) -> None:
    video = fixture_video()
    upload = start(service, video).json()
    for number, part in enumerate(chunks(video)):
        send(service, upload["id"], number, part)
    first = httpx.post(f"{service}/api/videos/{upload['id']}/complete", json={}, timeout=5)

    # The answer was lost on the way back, so the page asks again.
    again = httpx.post(f"{service}/api/videos/{upload['id']}/complete", json={}, timeout=5)

    assert again.status_code == 201, again.text
    assert again.json() == first.json()


def test_without_ffprobe_the_upload_is_kept_to_finish_later(
    start_service: StartService, tmp_path: Path
) -> None:
    # No ffprobe on the search path: the server cannot check the video.
    with start_service(tmp_path, PATH="", ESCAPE_ROOM_VIDEO_CHUNK_BYTES=str(CHUNK)) as url:
        video = fixture_video()
        upload = start(url, video).json()
        for number, part in enumerate(chunks(video)):
            send(url, upload["id"], number, part)

        for _ in range(2):
            done = httpx.post(f"{url}/api/videos/{upload['id']}/complete", json={}, timeout=5)
            assert done.status_code == 503
            assert done.json()["detail"] == (
                "The server cannot check videos: ffprobe is not installed."
            )


def test_a_chunk_with_no_declared_length_is_cut_off_at_the_chunk_size(service: str) -> None:
    upload = start(service, fixture_video()).json()

    def streamed() -> Iterator[bytes]:
        # Sent in pieces, so the request has no Content-Length to check up front.
        for _ in range(3):
            yield b"x" * CHUNK

    response = httpx.put(
        f"{service}/api/videos/{upload['id']}/chunks/0", content=streamed(), timeout=5
    )

    assert response.status_code == 413
    assert response.json()["detail"] == "A chunk is at most 1024 bytes."
