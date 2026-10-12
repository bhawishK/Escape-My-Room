"""Serve the built browser app and its same-origin HTTP/WebSocket contract."""

import asyncio
import json
import secrets
from pathlib import Path

from fastapi import FastAPI, HTTPException, Response, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from backend.protocol import JoinRequest, PoseMessage, ReleaseRequest
from backend.sessions import SessionStore


def create_app() -> FastAPI:
    app = FastAPI(title="Escape My Room diagnostics")
    store = SessionStore()

    @app.get("/api/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/api/sessions", status_code=201)
    async def create_session() -> dict[str, str]:
        return {"session_id": store.create().session_id}

    @app.post("/api/sessions/{session_id}/participants", status_code=201)
    async def join_session(session_id: str, request: JoinRequest) -> dict[str, str]:
        participant = await store.join(session_id, request)
        return {
            "participant_id": participant.participant_id,
            "connection_token": participant.token,
            "role": participant.role,
        }

    @app.post("/api/sessions/{session_id}/participants/{participant_id}/release", status_code=204)
    async def release_participant(
        session_id: str, participant_id: str, request: ReleaseRequest
    ) -> Response:
        session = store.get(session_id)
        async with session.lock:
            participant = session.participants.get(participant_id)
            if participant is None:
                return Response(status_code=204)
            if not secrets.compare_digest(request.connection_token, participant.token):
                raise HTTPException(
                    403, "The connection credential does not match this participant."
                )
            socket = participant.socket
            session.remove_participant(participant)
            if socket is not None:
                try:
                    await asyncio.wait_for(socket.close(code=1000), timeout=2)
                except (RuntimeError, OSError, TimeoutError):
                    pass
            await session.broadcast()
        return Response(status_code=204)

    @app.websocket("/api/sessions/{session_id}/ws")
    async def session_socket(
        socket: WebSocket,
        session_id: str,
        participant_id: str,
    ) -> None:
        session = store.sessions.get(session_id)
        if session is None:
            await socket.close(code=1008)
            return
        participant = None
        protocols = [
            value.strip() for value in socket.headers.get("sec-websocket-protocol", "").split(",")
        ]

        async def reject(code: str, message: str) -> None:
            await socket.send_json({"type": "error", "code": code, "message": message})

        try:
            async with session.lock:
                # Resolve the grant while holding the same lock as release and role assignment.
                participant = session.participants.get(participant_id)
                if (
                    participant is None
                    or len(protocols) != 2
                    or protocols[0] != "escape-my-room"
                    or not secrets.compare_digest(protocols[1], participant.token)
                ):
                    await socket.close(code=1008)
                    return
                await socket.accept(subprotocol="escape-my-room")
                previous_socket = participant.socket
                participant.generation += 1
                participant.sequence = 0
                participant.socket = socket
                generation = participant.generation
                session.reset_master_marker(participant)
                if previous_socket is not None:
                    await previous_socket.close(code=1008, reason="Connection replaced")
                session.revision += 1
                await socket.send_json(
                    {
                        "type": "welcome",
                        "session_id": session_id,
                        "participant_id": participant_id,
                        "connection_generation": generation,
                        "state": session.snapshot(),
                    }
                )
                await session.broadcast(exclude=socket)
            while True:
                message = await socket.receive()
                if message["type"] == "websocket.disconnect":
                    raise WebSocketDisconnect(message.get("code", 1000))
                raw = message.get("text")
                if not isinstance(raw, str):
                    await reject("invalid_message", "Send JSON text, not a binary WebSocket frame.")
                    continue
                if len(raw.encode("utf-8")) > 16384:
                    await reject("invalid_message", "Diagnostic messages must be at most 16 KiB.")
                    continue
                try:
                    pose = PoseMessage.model_validate(json.loads(raw))
                except (ValueError, ValidationError):
                    await reject(
                        "invalid_message", "Send a valid pose using the documented contract."
                    )
                    continue
                async with session.lock:
                    if participant.role != "mobile_master":
                        await reject(
                            "role_forbidden", "Only the mobile master publishes the marker pose."
                        )
                        continue
                    if participant.socket is not socket or pose.connection_generation != generation:
                        await reject("stale_connection", "Use this socket's assigned generation.")
                        continue
                    if pose.sequence <= participant.sequence:
                        await reject(
                            "stale_sequence", "Pose sequences must increase on this connection."
                        )
                        continue
                    if (
                        participant.tracking_source == "simulator"
                        and pose.tracking_status in ("tracked", "emulated")
                    ) or (
                        participant.tracking_source == "webxr"
                        and pose.tracking_status == "simulated"
                    ):
                        await reject(
                            "source_mismatch", "Simulator poses must remain labelled simulated."
                        )
                        continue
                    session.accept_pose(participant, pose)
                    await session.broadcast()
        except WebSocketDisconnect:
            pass
        finally:
            async with session.lock:
                if participant is not None and participant.socket is socket:
                    session.remove_participant(participant)
                    await session.broadcast()

    dist = Path(__file__).resolve().parents[1] / "frontend" / "dist"
    if dist.is_dir():
        app.mount("/", StaticFiles(directory=dist, html=True), name="frontend")
    return app


app = create_app()
