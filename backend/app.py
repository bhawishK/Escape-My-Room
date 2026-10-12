"""Serve the browser app and a direct, unauthenticated prototype connection."""

import asyncio
import json
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from backend.protocol import MarkerState, PoseMessage, Role
from backend.sessions import PrototypeRoom


def create_app() -> FastAPI:
    app = FastAPI(title="Escape My Room prototype")
    room = PrototypeRoom()

    @app.get("/api/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.websocket("/api/ws")
    async def room_socket(socket: WebSocket, role: Role) -> None:
        sequence = 0

        async def reject(code: str, message: str) -> None:
            await socket.send_json({"type": "error", "code": code, "message": message})

        try:
            async with room.lock:
                await socket.accept()
                previous = room.sockets.get(role)
                room.sockets[role] = socket
                if role == "mobile_master":
                    room.marker = MarkerState()
                if previous is not None:
                    try:
                        await asyncio.wait_for(
                            previous.close(code=1000, reason="Device connected in another tab"),
                            timeout=2,
                        )
                    except (RuntimeError, OSError, TimeoutError):
                        pass
                room.revision += 1
                await socket.send_json({"type": "welcome", "state": room.snapshot()})
                await room.broadcast(exclude=socket)
            while True:
                message = await socket.receive()
                if message["type"] == "websocket.disconnect":
                    raise WebSocketDisconnect(message.get("code", 1000))
                raw = message.get("text")
                if not isinstance(raw, str) or len(raw.encode("utf-8")) > 16384:
                    await reject("invalid_message", "Send a JSON text pose of at most 16 KiB.")
                    continue
                try:
                    pose = PoseMessage.model_validate(json.loads(raw))
                except (ValueError, ValidationError):
                    await reject("invalid_message", "Send a valid XR pose using the contract.")
                    continue
                async with room.lock:
                    if room.sockets.get(role) is not socket:
                        return
                    if role != "mobile_master":
                        await reject("role_forbidden", "Only the phone sends the marker pose.")
                        continue
                    if pose.sequence <= sequence:
                        await reject(
                            "stale_sequence", "Pose sequences must increase on this socket."
                        )
                        continue
                    sequence = pose.sequence
                    room.accept_pose(pose)
                    await room.broadcast()
        except WebSocketDisconnect:
            pass
        finally:
            async with room.lock:
                if room.sockets.get(role) is socket:
                    room.disconnect(role)
                    await room.broadcast()

    dist = Path(__file__).resolve().parents[1] / "frontend" / "dist"
    if dist.is_dir():
        app.mount("/", StaticFiles(directory=dist, html=True), name="frontend")
    return app


app = create_app()
