"""Voice call set-up messages pass between the two people, and touch nothing else (#13)."""

import json

import pytest
from test_manipulation import box
from test_session_flow import open_socket, receive_until

OFFER = {"type": "voice_signal", "kind": "offer", "sdp": "v=0\r\no=- 1 2 IN IP4 127.0.0.1\r\n"}
ANSWER = {"type": "voice_signal", "kind": "answer", "sdp": "v=0\r\no=- 3 4 IN IP4 127.0.0.1\r\n"}
CANDIDATE = {
    "type": "voice_signal",
    "kind": "candidate",
    "candidate": {
        "candidate": "candidate:1 1 udp 2122260223 192.0.2.1 54321 typ host",
        "sdpMid": "0",
        "sdpMLineIndex": 0,
        "usernameFragment": "abcd",
    },
}
NO_MORE_CANDIDATES = {"type": "voice_signal", "kind": "candidate", "candidate": None}


def voice(event, role):
    return event.get("state", {}).get("voice", {}).get(role, {})


def ready(socket, value=True):
    socket.send(json.dumps({"type": "voice_ready", "ready": value}))


def both_ready(phone, headset):
    """Both say they are ready; returns once each has seen the other is."""
    ready(phone)
    ready(headset)
    for socket in (phone, headset):
        receive_until(
            socket,
            lambda event: (
                voice(event, "mobile_master").get("ready") is True
                and voice(event, "vr_solver").get("ready") is True
            ),
        )


def next_signal(socket):
    return receive_until(socket, lambda event: event.get("type") == "voice_signal")


def error(socket):
    return receive_until(socket, lambda event: event.get("type") == "error")["code"]


def test_nobody_is_ready_to_talk_at_first(service_url):
    with open_socket(service_url, "mobile_master") as phone:
        welcome = json.loads(phone.recv(timeout=2))
        assert voice(welcome, "mobile_master")["ready"] is False
        assert voice(welcome, "vr_solver")["ready"] is False


def test_each_person_sees_when_the_other_is_ready_and_when_they_stop(service_url):
    with (
        open_socket(service_url, "mobile_master") as phone,
        open_socket(service_url, "vr_solver") as headset,
    ):
        ready(phone)
        seen = receive_until(headset, lambda event: voice(event, "mobile_master").get("ready"))
        assert voice(seen, "vr_solver")["ready"] is False
        ready(phone, False)
        receive_until(headset, lambda event: voice(event, "mobile_master").get("ready") is False)


def test_starting_again_is_a_new_voice_session(service_url):
    with (
        open_socket(service_url, "mobile_master") as phone,
        open_socket(service_url, "vr_solver") as headset,
    ):
        ready(phone)
        first = receive_until(headset, lambda event: voice(event, "mobile_master").get("ready"))
        session = voice(first, "mobile_master")["session"]
        # Saying ready twice changes nothing.
        ready(phone)
        ready(phone, False)
        ready(phone)
        again = receive_until(
            headset,
            lambda event: (
                voice(event, "mobile_master").get("ready")
                and voice(event, "mobile_master")["session"] != session
            ),
        )
        assert voice(again, "mobile_master")["session"] == session + 1


def test_set_up_messages_reach_the_other_person_unchanged_and_in_order(service_url):
    with (
        open_socket(service_url, "mobile_master") as phone,
        open_socket(service_url, "vr_solver") as headset,
    ):
        both_ready(phone, headset)
        for message in (OFFER, CANDIDATE, NO_MORE_CANDIDATES):
            phone.send(json.dumps(message))
        offer = next_signal(headset)
        assert offer["from"] == "mobile_master"
        assert offer["kind"] == "offer"
        assert offer["sdp"] == OFFER["sdp"]
        assert offer["candidate"] is None
        candidate = next_signal(headset)
        assert candidate["kind"] == "candidate"
        assert candidate["candidate"] == CANDIDATE["candidate"]
        assert candidate["sdp"] is None
        last = next_signal(headset)
        assert last["kind"] == "candidate"
        assert last["candidate"] is None
        headset.send(json.dumps(ANSWER))
        answer = next_signal(phone)
        assert answer["from"] == "vr_solver"
        assert answer["sdp"] == ANSWER["sdp"]


def test_a_set_up_message_goes_to_the_other_person_alone(service_url):
    with (
        open_socket(service_url, "mobile_master") as phone,
        open_socket(service_url, "vr_solver") as headset,
    ):
        both_ready(phone, headset)
        phone.send(json.dumps(OFFER))
        next_signal(headset)
        # The sender hears nothing back: the next thing it gets is the answer to its own ready.
        ready(phone, False)
        after = json.loads(phone.recv(timeout=2))
        assert after["type"] == "state"
        assert voice(after, "mobile_master")["ready"] is False


def test_a_set_up_message_names_the_senders_voice_session(service_url):
    with (
        open_socket(service_url, "mobile_master") as phone,
        open_socket(service_url, "vr_solver") as headset,
    ):
        both_ready(phone, headset)
        phone.send(json.dumps(OFFER))
        first = next_signal(headset)["session"]
        ready(phone, False)
        ready(phone)
        receive_until(
            phone,
            lambda event: voice(event, "mobile_master").get("session") == first + 1,
        )
        phone.send(json.dumps(OFFER))
        assert next_signal(headset)["session"] == first + 1


def test_a_message_before_starting_voice_is_refused(service_url):
    with (
        open_socket(service_url, "mobile_master") as phone,
        open_socket(service_url, "vr_solver") as headset,
    ):
        ready(headset)
        receive_until(phone, lambda event: voice(event, "vr_solver").get("ready"))
        phone.send(json.dumps(OFFER))
        assert error(phone) == "voice_not_ready"


def test_a_message_to_someone_who_has_not_started_voice_is_refused(service_url):
    with (
        open_socket(service_url, "mobile_master") as phone,
        open_socket(service_url, "vr_solver") as headset,
    ):
        headset.recv(timeout=2)
        ready(phone)
        phone.send(json.dumps(OFFER))
        assert error(phone) == "voice_peer_not_ready"
        # The session carries on.
        ready(headset)
        receive_until(phone, lambda event: voice(event, "vr_solver").get("ready"))
        phone.send(json.dumps(OFFER))
        assert next_signal(headset)["kind"] == "offer"


def test_a_message_to_someone_who_is_not_connected_is_refused(service_url):
    with open_socket(service_url, "mobile_master") as phone:
        phone.recv(timeout=2)
        ready(phone)
        phone.send(json.dumps(OFFER))
        assert error(phone) == "voice_peer_unavailable"


def test_leaving_ends_that_persons_readiness_and_a_new_page_starts_without_it(service_url):
    with open_socket(service_url, "mobile_master") as phone:
        phone.recv(timeout=2)
        with open_socket(service_url, "vr_solver") as headset:
            both_ready(phone, headset)
        gone = receive_until(
            phone, lambda event: event.get("state", {}).get("vr_connected") is False
        )
        assert voice(gone, "vr_solver")["ready"] is False
        assert voice(gone, "mobile_master")["ready"] is True
        with open_socket(service_url, "vr_solver") as headset:
            welcome = json.loads(headset.recv(timeout=2))
            assert voice(welcome, "vr_solver")["ready"] is False
            phone.send(json.dumps(OFFER))
            assert error(phone) == "voice_peer_not_ready"


def test_a_second_tab_in_the_same_role_starts_without_readiness(service_url):
    with (
        open_socket(service_url, "mobile_master") as phone,
        open_socket(service_url, "vr_solver") as headset,
    ):
        both_ready(phone, headset)
        with open_socket(service_url, "vr_solver") as second:
            welcome = json.loads(second.recv(timeout=2))
            assert voice(welcome, "vr_solver")["ready"] is False
            receive_until(phone, lambda event: voice(event, "vr_solver").get("ready") is False)


@pytest.mark.parametrize(
    "message",
    [
        {"type": "voice_ready"},
        {"type": "voice_ready", "ready": "yes"},
        {"type": "voice_signal", "kind": "offer"},
        {"type": "voice_signal", "kind": "offer", "sdp": ""},
        {"type": "voice_signal", "kind": "offer", "sdp": "v=0", "candidate": None, "extra": 1},
        {
            "type": "voice_signal",
            "kind": "offer",
            "sdp": "v=0",
            **{"candidate": CANDIDATE["candidate"]},
        },
        {"type": "voice_signal", "kind": "candidate", "sdp": "v=0"},
        {"type": "voice_signal", "kind": "hangup", "sdp": "v=0"},
        {"type": "voice_signal", "kind": "candidate", "candidate": {"sdpMid": "0"}},
        {"type": "voice_signal", "kind": "offer", "sdp": "x" * 12001},
        {"type": "voice_signal", "kind": "candidate", "candidate": {"candidate": "x" * 2049}},
    ],
)
def test_malformed_and_oversized_voice_messages_are_rejected(service_url, message):
    with (
        open_socket(service_url, "mobile_master") as phone,
        open_socket(service_url, "vr_solver") as headset,
    ):
        both_ready(phone, headset)
        phone.send(json.dumps(message))
        assert error(phone) == "invalid_message"
        # Nothing was passed on: the next thing the headset gets is a good offer.
        phone.send(json.dumps(OFFER))
        assert next_signal(headset)["sdp"] == OFFER["sdp"]


def test_voice_changes_no_object_and_no_hold(service_url):
    with (
        open_socket(service_url, "mobile_master") as phone,
        open_socket(service_url, "vr_solver") as headset,
    ):
        start = json.loads(phone.recv(timeout=2))["state"]
        both_ready(phone, headset)
        for message in (OFFER, CANDIDATE):
            phone.send(json.dumps(message))
            next_signal(headset)
        ready(phone, False)
        after = receive_until(
            headset, lambda event: voice(event, "mobile_master").get("ready") is False
        )["state"]
        assert box(after) == pytest.approx(box(start))
        assert after["manipulation"] is None
        assert after["room"]["entities"] == start["room"]["entities"]
        assert after["room"]["room_version"] == start["room"]["room_version"]
