"""Where the two browsers look for a path to each other for the voice call (#13, #172).

The audio goes browser to browser. To find a path, each browser asks a STUN server for its public
address, and, on networks that block a direct path, sends the audio through a TURN relay. Which
servers to use is a server setting, so it can change without rebuilding the pages.
"""

import os
from typing import Any

# Used when nothing is set: finds a device's public address, and relays nothing.
DEFAULT_STUN = "stun:stun.l.google.com:19302"


def _urls(value: str, schemes: tuple[str, ...]) -> list[str]:
    urls = [url.strip() for url in value.split(",") if url.strip()]
    for url in urls:
        if not url.startswith(schemes):
            expected = " or ".join(schemes)
            raise ValueError(f"A voice server address must start with {expected}: {url}")
    return urls


def voice_config_from_environment() -> dict[str, Any]:
    """The ICE servers the pages give WebRTC, from the server's settings.

    A TURN credential has to reach the pages, since the browsers log in to the relay themselves.
    Anyone who can open the site can read it, so use one made for this prototype.
    """
    stun = os.environ.get("ESCAPE_ROOM_VOICE_STUN_URLS")
    servers: list[dict[str, Any]] = []
    stun_urls = _urls(DEFAULT_STUN if stun is None else stun, ("stun:", "stuns:"))
    if stun_urls:
        servers.append({"urls": stun_urls})
    turn_urls = _urls(os.environ.get("ESCAPE_ROOM_VOICE_TURN_URLS") or "", ("turn:", "turns:"))
    if turn_urls:
        username = os.environ.get("ESCAPE_ROOM_VOICE_TURN_USERNAME") or ""
        credential = os.environ.get("ESCAPE_ROOM_VOICE_TURN_CREDENTIAL") or ""
        if not username or not credential:
            raise ValueError(
                "ESCAPE_ROOM_VOICE_TURN_URLS needs ESCAPE_ROOM_VOICE_TURN_USERNAME and "
                "ESCAPE_ROOM_VOICE_TURN_CREDENTIAL."
            )
        servers.append({"urls": turn_urls, "username": username, "credential": credential})
    relay_only = (os.environ.get("ESCAPE_ROOM_VOICE_RELAY_ONLY") or "").strip() in ("1", "true")
    if relay_only and not turn_urls:
        raise ValueError("ESCAPE_ROOM_VOICE_RELAY_ONLY needs ESCAPE_ROOM_VOICE_TURN_URLS.")
    return {"ice_servers": servers, "relay_only": relay_only}
