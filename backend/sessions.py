"""In-memory diagnostic sessions; socket identity is assigned by the server."""

import asyncio
import secrets
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from fastapi import HTTPException, WebSocket

from backend.protocol import JoinRequest, PoseMessage, Role, TrackingSource


@dataclass
class Participant:
    participant_id: str
    role: Role
    tracking_source: TrackingSource
    token: str = field(default_factory=lambda: secrets.token_urlsafe(32))
    generation: int = 0
    sequence: int = 0
    socket: WebSocket | None = None


@dataclass
class Session:
    session_id: str
    participants: dict[str, Participant] = field(default_factory=lambda: dict[str, Participant]())
    revision: int = 0
    marker: dict[str, Any] = field(
        default_factory=lambda: {
            "participant_id": None,
            "source": None,
            "tracking_status": "inactive",
            "reference_space": None,
            "position": None,
        }
    )
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def snapshot(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "revision": self.revision,
            "participants": [
                {
                    "participant_id": p.participant_id,
                    "role": p.role,
                    "tracking_source": p.tracking_source,
                    "connected": p.socket is not None,
                    "connection_generation": p.generation,
                }
                for p in self.participants.values()
            ],
            "marker": dict(self.marker),
        }

    async def broadcast(self, exclude: WebSocket | None = None) -> None:
        event = {"type": "state", "state": self.snapshot()}
        for participant in list(self.participants.values()):
            socket = participant.socket
            if socket is not None and socket is not exclude:
                try:
                    await asyncio.wait_for(socket.send_json(event), timeout=2)
                except (RuntimeError, OSError, TimeoutError):
                    # Its endpoint's disconnect handler owns removal and state cleanup.
                    continue

    def accept_pose(self, participant: Participant, pose: PoseMessage) -> None:
        participant.sequence = pose.sequence
        self.marker = {
            "participant_id": participant.participant_id,
            "source": participant.tracking_source,
            "tracking_status": pose.tracking_status,
            "reference_space": pose.reference_space,
            "position": pose.position.model_dump() if pose.position else None,
        }
        self.revision += 1


class SessionStore:
    def __init__(self) -> None:
        self.sessions: dict[str, Session] = {}

    def create(self) -> Session:
        session = Session(str(uuid4()))
        self.sessions[session.session_id] = session
        return session

    def get(self, session_id: str) -> Session:
        session = self.sessions.get(session_id)
        if session is None:
            raise HTTPException(404, "Session not found. Ask the master for its current link.")
        return session

    async def join(self, session_id: str, request: JoinRequest) -> Participant:
        session = self.get(session_id)
        async with session.lock:
            if any(p.role == request.role for p in session.participants.values()):
                raise HTTPException(409, "That role is already occupied in this session.")
            participant = Participant(str(uuid4()), request.role, request.tracking_source)
            session.participants[participant.participant_id] = participant
            return participant
