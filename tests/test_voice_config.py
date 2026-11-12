"""The pages are told which STUN and TURN servers to use for the voice call (#172)."""

import httpx
import pytest

from backend.voice import DEFAULT_STUN, voice_config_from_environment

SETTINGS = (
    "ESCAPE_ROOM_VOICE_STUN_URLS",
    "ESCAPE_ROOM_VOICE_TURN_URLS",
    "ESCAPE_ROOM_VOICE_TURN_USERNAME",
    "ESCAPE_ROOM_VOICE_TURN_CREDENTIAL",
    "ESCAPE_ROOM_VOICE_RELAY_ONLY",
)


@pytest.fixture(autouse=True)
def no_voice_settings(monkeypatch):
    for name in SETTINGS:
        monkeypatch.delenv(name, raising=False)


def test_without_settings_the_pages_get_one_public_stun_server(service_url):
    config = httpx.get(f"{service_url}/api/voice/config", timeout=5).json()
    assert config == {"ice_servers": [{"urls": [DEFAULT_STUN]}], "relay_only": False}


def test_the_pages_get_the_stun_and_turn_servers_from_the_settings(start_service, tmp_path):
    settings = {
        "ESCAPE_ROOM_VOICE_STUN_URLS": "stun:stun.example.org:3478, stun:other.example.org:3478",
        "ESCAPE_ROOM_VOICE_TURN_URLS": "turn:turn.example.org:3478,turns:turn.example.org:5349",
        "ESCAPE_ROOM_VOICE_TURN_USERNAME": "prototype",
        "ESCAPE_ROOM_VOICE_TURN_CREDENTIAL": "not-a-real-credential",
        "ESCAPE_ROOM_VOICE_RELAY_ONLY": "1",
    }
    with start_service(tmp_path, **settings) as url:
        config = httpx.get(f"{url}/api/voice/config", timeout=5).json()
    assert config == {
        "ice_servers": [
            {"urls": ["stun:stun.example.org:3478", "stun:other.example.org:3478"]},
            {
                "urls": ["turn:turn.example.org:3478", "turns:turn.example.org:5349"],
                "username": "prototype",
                "credential": "not-a-real-credential",
            },
        ],
        "relay_only": True,
    }


def test_an_empty_stun_setting_turns_stun_off(monkeypatch):
    monkeypatch.setenv("ESCAPE_ROOM_VOICE_STUN_URLS", "")
    assert voice_config_from_environment() == {"ice_servers": [], "relay_only": False}


def test_a_turn_server_without_its_login_is_refused(monkeypatch):
    monkeypatch.setenv("ESCAPE_ROOM_VOICE_TURN_URLS", "turn:turn.example.org:3478")
    with pytest.raises(ValueError, match="ESCAPE_ROOM_VOICE_TURN_USERNAME"):
        voice_config_from_environment()


def test_relay_only_without_a_turn_server_is_refused(monkeypatch):
    monkeypatch.setenv("ESCAPE_ROOM_VOICE_RELAY_ONLY", "1")
    with pytest.raises(ValueError, match="ESCAPE_ROOM_VOICE_TURN_URLS"):
        voice_config_from_environment()


def test_an_address_of_the_wrong_kind_is_refused(monkeypatch):
    monkeypatch.setenv("ESCAPE_ROOM_VOICE_STUN_URLS", "https://stun.example.org")
    with pytest.raises(ValueError, match="must start with stun:"):
        voice_config_from_environment()
