"""Caption queue for Understand Me.

A caption is one utterance: {"speaker": str, "text": str, "ts": ISO string}.
This module keeps the in-memory list and fans new captions out to any
connected WebSocket clients.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone

from fastapi import WebSocket


def now_iso() -> str:
    """Current UTC time as an ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()


class CaptionStore:
    """In-memory, append-only list of captions."""

    def __init__(self) -> None:
        self._captions: list[dict] = []

    def add(self, speaker: str, text: str) -> dict:
        caption = {"speaker": speaker, "text": text, "ts": now_iso()}
        self._captions.append(caption)
        return caption

    def all(self) -> list[dict]:
        return list(self._captions)

    def clear(self) -> None:
        self._captions.clear()


class ConnectionManager:
    """Tracks live WebSocket clients and broadcasts new captions to them."""

    def __init__(self) -> None:
        self._connections: list[WebSocket] = []
        self._lock = asyncio.Lock()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        async with self._lock:
            self._connections.append(ws)

    async def disconnect(self, ws: WebSocket) -> None:
        async with self._lock:
            if ws in self._connections:
                self._connections.remove(ws)

    async def broadcast(self, caption: dict) -> None:
        payload = json.dumps(caption, ensure_ascii=False)
        async with self._lock:
            targets = list(self._connections)
        dead: list[WebSocket] = []
        for ws in targets:
            try:
                await ws.send_text(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            await self.disconnect(ws)
