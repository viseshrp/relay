from __future__ import annotations

import asyncio
from collections import defaultdict

from fastapi import WebSocket


class ConnectionManager:
    def __init__(self) -> None:
        self._connections: dict[int, WebSocket] = {}
        self._run_subscriptions: dict[int, set[str]] = defaultdict(set)
        self._subscribe_all: set[int] = set()
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self._connections[id(websocket)] = websocket

    async def disconnect(self, websocket: WebSocket) -> None:
        async with self._lock:
            connection_id = id(websocket)
            self._connections.pop(connection_id, None)
            self._run_subscriptions.pop(connection_id, None)
            self._subscribe_all.discard(connection_id)

    async def subscribe(self, websocket: WebSocket, run_id: str) -> None:
        async with self._lock:
            self._run_subscriptions[id(websocket)].add(run_id)

    async def unsubscribe(self, websocket: WebSocket, run_id: str) -> None:
        async with self._lock:
            self._run_subscriptions[id(websocket)].discard(run_id)

    async def subscribe_all(self, websocket: WebSocket) -> None:
        async with self._lock:
            self._subscribe_all.add(id(websocket))

    async def is_subscribed(self, websocket: WebSocket, run_id: str) -> bool:
        async with self._lock:
            connection_id = id(websocket)
            return connection_id in self._subscribe_all or run_id in self._run_subscriptions.get(connection_id, set())

    async def broadcast(self, event: dict[str, object], run_id: str | None = None) -> None:
        async with self._lock:
            targets = []
            for connection_id, websocket in self._connections.items():
                if connection_id in self._subscribe_all or (run_id and run_id in self._run_subscriptions.get(connection_id, set())):
                    targets.append(websocket)
        for websocket in targets:
            try:
                await websocket.send_json(event)
            except Exception:
                await self.disconnect(websocket)
