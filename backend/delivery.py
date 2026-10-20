"""Deliver to one device without a backlog: all in order, but only the newest shared state."""

import asyncio
import contextlib
from collections import deque
from typing import Any

from fastapi import WebSocket

# How long one send may take before the device counts as stalled and is disconnected.
SEND_TIMEOUT = 2.0


class Outbox:
    """
    What one device still has to be sent, sent by its own task so a slow device holds up no one.

    Replies (welcome, errors, selection results) are all delivered, and everything goes in the
    order it was handed over. Shared state is coalesced: of the states due, only the newest is
    sent, so a long hold never builds a queue, and the last state, such as a release, always
    arrives. `delay` holds each item back that many seconds after it was handed over, to reproduce
    network latency on purpose; what waits is bounded by what arrives within that window. A device
    that stops taking messages is disconnected rather than left with a growing queue.
    """

    def __init__(self, socket: WebSocket, delay: float = 0.0) -> None:
        self.socket = socket
        self.delay = delay
        # (due time, is shared state, event), in the order handed over.
        self.waiting: deque[tuple[float, bool, dict[str, Any]]] = deque()
        self.ready = asyncio.Event()
        # Set while nothing is waiting or being sent.
        self.idle = asyncio.Event()
        self.idle.set()
        self.stalled = False
        self.task = asyncio.create_task(self.run())

    def reply(self, event: dict[str, Any]) -> None:
        self.hand_over(False, event)

    def publish(self, state: dict[str, Any]) -> None:
        self.hand_over(True, {"type": "state", "state": state})

    def hand_over(self, shared: bool, event: dict[str, Any]) -> None:
        if self.stalled:
            return
        self.waiting.append((asyncio.get_running_loop().time() + self.delay, shared, event))
        self.idle.clear()
        self.ready.set()

    async def run(self) -> None:
        loop = asyncio.get_running_loop()
        while True:
            if not self.waiting:
                self.idle.set()
                self.ready.clear()
                await self.ready.wait()
                continue
            # Items are handed over in order with the same delay, so the first is due first.
            wait = self.waiting[0][0] - loop.time()
            if wait > 0:
                await asyncio.sleep(wait)
            now = loop.time()
            due = [item for item in self.waiting if item[0] <= now]
            last_state = max((i for i, (_, shared, _) in enumerate(due) if shared), default=-1)
            for index, (_, shared, event) in enumerate(due):
                # Every reply goes; of the states, only the newest, in its place.
                if not shared or index == last_state:
                    if not await self.send(event):
                        return
                self.waiting.popleft()

    async def send(self, event: dict[str, Any]) -> bool:
        try:
            await asyncio.wait_for(self.socket.send_json(event), timeout=SEND_TIMEOUT)
            return True
        except asyncio.CancelledError:
            raise
        except Exception:
            # Gone, or too slow to take messages: stop queueing, and close the connection so its
            # endpoint cleans up the device instead of the queue growing until it disconnects.
            self.stalled = True
            self.waiting.clear()
            self.idle.set()
            with contextlib.suppress(Exception):
                await asyncio.wait_for(self.socket.close(code=1011), timeout=SEND_TIMEOUT)
            return False

    async def close(self, flush: bool = False) -> None:
        """Stop sending; with `flush`, first let what is waiting go out, such as a last error."""
        if flush:
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self.idle.wait(), timeout=self.delay + SEND_TIMEOUT)
        self.task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await self.task
        self.waiting.clear()
