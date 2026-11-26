"""Caption queue for Understand Me.

A caption is one utterance: {"speaker": str, "text": str, "ts": ISO string}.
This module keeps the in-memory list and fans new captions out to any
connected WebSocket clients.
"""

from __future__ import annotations

import asyncio
import json
import os
from collections import deque
from datetime import datetime, timezone

from fastapi import WebSocket

DEFAULT_CAPTION_MAX = 200


def now_iso() -> str:
    """Current UTC time as an ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()


def _env_int(name: str, default: int) -> int:
    """Positive int from the environment, falling back to `default`."""
    try:
        value = int(os.environ.get(name, ""))
    except ValueError:
        return default
    return value if value > 0 else default


class CaptionStore:
    """In-memory caption list bounded to the newest entries.

    The bound keeps a long-running process from accumulating stale
    captions: once `max_items` is exceeded, the oldest are dropped.
    """

    def __init__(self, max_items: int | None = None) -> None:
        if max_items is None:
            max_items = _env_int("UM_CAPTION_MAX", DEFAULT_CAPTION_MAX)
        self._captions: deque[dict] = deque(maxlen=max_items)

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
