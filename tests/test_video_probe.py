"""Reading ffprobe's description of an uploaded room video (#136): its length, resolution as seen
upright, and frame rate, or why it is not a room video."""

import pytest

from backend.videos import VideoError, parse_ffprobe


def iphone_portrait() -> dict:
    """What `ffprobe -print_format json -show_format -show_streams` says of a portrait iPhone video,
    cut down to the fields that matter: stored landscape, turned a quarter by its display matrix."""
    return {
        "streams": [
            {
                "codec_type": "video",
                "codec_name": "hevc",
                "width": 1920,
                "height": 1080,
                "avg_frame_rate": "30000/1001",
                "side_data_list": [{"side_data_type": "Display Matrix", "rotation": -90}],
            },
            {"codec_type": "audio", "codec_name": "aac"},
        ],
        "format": {"format_name": "mov,mp4,m4a,3gp,3g2,mj2", "duration": "83.416667"},
    }


def test_a_portrait_iphone_video_is_upright_with_its_length_and_frame_rate() -> None:
    info = parse_ffprobe(iphone_portrait())

    assert info.model_dump() == {
        "seconds": 83.417,
        "width": 1080,
        "height": 1920,
        "frames_per_second": 29.97,
        "codec": "hevc",
    }


def test_a_sound_recording_is_not_a_room_video() -> None:
    sound = iphone_portrait()
    sound["streams"] = [stream for stream in sound["streams"] if stream["codec_type"] == "audio"]

    with pytest.raises(VideoError, match="has no video in it"):
        parse_ffprobe(sound)


def test_a_webm_video_is_refused_as_not_mp4_or_mov() -> None:
    webm = iphone_portrait()
    webm["format"]["format_name"] = "matroska,webm"

    with pytest.raises(VideoError, match="MP4 or MOV"):
        parse_ffprobe(webm)
