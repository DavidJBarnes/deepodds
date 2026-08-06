"""In-process WebSocket fan-out for the Verbatim console.

Ported from the standalone project's `verbatim/api/hub.py`. It stays a module
singleton, and that is now sound rather than a limitation: the GPU worker reaches
this process over HTTP, so every broadcast originates inside the API's own event
loop. There is no cross-process bridge to build — which is the main simplification
the DeepOdds-owns-the-API split buys.

Event types: ``transcript``, ``near_miss``, ``detection``, ``heartbeat``, ``market``.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Protocol

logger = logging.getLogger("app.verbatim.hub")


class _Socket(Protocol):
    """The slice of WebSocket we use — kept narrow so tests need no real socket."""

    async def send_json(self, data: Any) -> None: ...


class Hub:
    """Fan-out to every connected console client.

    A send failure means the peer is gone, so the socket is dropped rather than
    retried: a browser that closed mid-broadcast must never be able to stall the
    detection path behind it.
    """

    def __init__(self) -> None:
        self._clients: set[_Socket] = set()
        self._lock = asyncio.Lock()

    async def connect(self, ws: _Socket) -> None:
        async with self._lock:
            self._clients.add(ws)

    async def disconnect(self, ws: _Socket) -> None:
        async with self._lock:
            self._clients.discard(ws)

    @property
    def client_count(self) -> int:
        return len(self._clients)

    async def broadcast(self, event_type: str, payload: Any) -> None:
        """Send ``{"type": …, "data": …}`` to all clients, dropping dead ones."""
        async with self._lock:
            targets = list(self._clients)
        if not targets:
            return
        message = {"type": event_type, "data": payload}
        dead: list[_Socket] = []
        for ws in targets:
            try:
                await ws.send_json(message)
            except Exception:  # noqa: BLE001 — any failure means the peer is gone
                dead.append(ws)
        if dead:
            async with self._lock:
                for ws in dead:
                    self._clients.discard(ws)
            logger.info("dropped %d dead verbatim ws client(s)", len(dead))


hub = Hub()
