"""Server-Sent Events (SSE) alert broadcaster.

Maintains an in-process registry of subscriber queues.  The pipeline calls
``broadcast_alert`` whenever a new alert is emitted; each SSE subscriber
drains its own queue.

Thread-safe: the registry is protected by an asyncio Lock.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

# ──────────────────────────────────────────────────────────────────────────────
# Broadcast registry
# ──────────────────────────────────────────────────────────────────────────────

_subscribers: list[asyncio.Queue[dict[str, Any]]] = []
_lock = asyncio.Lock()


async def _register() -> asyncio.Queue[dict[str, Any]]:
    q: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=256)
    async with _lock:
        _subscribers.append(q)
    return q


async def _unregister(q: asyncio.Queue[dict[str, Any]]) -> None:
    async with _lock:
        try:
            _subscribers.remove(q)
        except ValueError:
            pass


async def broadcast_alert(payload: dict[str, Any]) -> None:
    """Push *payload* to all active SSE subscriber queues (non-blocking)."""
    async with _lock:
        subs = list(_subscribers)
    for q in subs:
        try:
            q.put_nowait(payload)
        except asyncio.QueueFull:
            pass  # slow subscriber — drop rather than block


# ──────────────────────────────────────────────────────────────────────────────
# SSE generator
# ──────────────────────────────────────────────────────────────────────────────


async def alert_event_stream(
    timeout_seconds: float = 30.0,
) -> AsyncIterator[dict[str, Any]]:
    """Async generator that yields SSE-compatible event dicts.

    Each yielded dict has the shape expected by sse-starlette:
    ``{"data": "<json string>", "event": "alert"}``.

    Sends a ``{"event": "heartbeat"}`` every *timeout_seconds* to keep
    the connection alive through HTTP proxies.
    """
    q = await _register()
    try:
        while True:
            try:
                payload = await asyncio.wait_for(q.get(), timeout=timeout_seconds)
                yield {
                    "event": "alert",
                    "data": json.dumps(payload, default=str),
                }
            except TimeoutError:
                yield {
                    "event": "heartbeat",
                    "data": json.dumps({"ts": datetime.now(UTC).isoformat()}),
                }
    finally:
        await _unregister(q)
