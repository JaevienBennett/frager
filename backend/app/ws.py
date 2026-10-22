from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import WebSocket

log = logging.getLogger(__name__)

# How long a single websocket send may take before it is treated as a dead
# connection. Without this one stalled client blocks the whole broadcast.
SEND_TIMEOUT_SECONDS = 5.0


class ConnectionManager:
    def __init__(self) -> None:
        # league_id -> set of websockets
        self.active: dict[int, set[WebSocket]] = {}

    async def connect(self, league_id: int, websocket: WebSocket) -> None:
        await websocket.accept()
        self.active.setdefault(league_id, set()).add(websocket)

    def disconnect(self, league_id: int, websocket: WebSocket) -> None:
        conns = self.active.get(league_id)
        if not conns:
            return
        conns.discard(websocket)
        if not conns:
            self.active.pop(league_id, None)

    async def broadcast(self, league_id: int, message: dict[str, Any]) -> None:
        conns = list(self.active.get(league_id, set()))
        if not conns:
            return
        data = json.dumps(message)
        for ws in conns:
            try:
                await asyncio.wait_for(
                    ws.send_text(data), timeout=SEND_TIMEOUT_SECONDS
                )
            except asyncio.TimeoutError:
                log.warning(
                    "websocket send timed out for league %s; dropping connection",
                    league_id,
                )
                self.disconnect(league_id, ws)
            except Exception:
                log.warning(
                    "websocket send failed for league %s; dropping connection",
                    league_id,
                    exc_info=True,
                )
                self.disconnect(league_id, ws)


manager = ConnectionManager()

# The event loop the application runs on. FastAPI runs `def` endpoints in a
# worker thread, and a worker thread has no running event loop, so
# `asyncio.create_task` there raises "no running event loop" and the update is
# silently dropped. The loop is captured during startup and used to hand the
# broadcast back to the main loop.
_loop: asyncio.AbstractEventLoop | None = None


def set_event_loop(loop: asyncio.AbstractEventLoop | None) -> None:
    """Remember the loop the app runs on (called from the lifespan hook)."""
    global _loop
    _loop = loop
    if loop is not None:
        log.info("websocket broadcast loop captured")
    else:
        log.info("websocket broadcast loop cleared")


def _report_failure(future: "asyncio.Future[Any]") -> None:
    """Log a broadcast that blew up instead of losing it in a future."""
    try:
        exc = future.exception()
    except Exception:  # pragma: no cover - cancelled future
        return
    if exc is not None:
        log.error("websocket broadcast failed", exc_info=exc)


def broadcast_nowait(league_id: int, message: dict[str, Any]) -> None:
    """Broadcast to a league without blocking the calling thread.

    Safe to call from a sync endpoint (worker thread), from the event loop
    itself, and from a plain script.
    """
    try:
        running = asyncio.get_running_loop()
    except RuntimeError:
        running = None

    if running is not None:
        # Already on the event loop: schedule and move on.
        task = running.create_task(manager.broadcast(league_id, message))
        task.add_done_callback(_report_failure)
        return

    if _loop is not None and not _loop.is_closed():
        try:
            future = asyncio.run_coroutine_threadsafe(
                manager.broadcast(league_id, message), _loop
            )
            future.add_done_callback(_report_failure)
        except Exception:
            log.exception("failed to schedule broadcast for league %s", league_id)
        return

    # No startup loop captured (e.g. a test client without the lifespan
    # running): hop back onto the loop this worker thread belongs to.
    try:
        import anyio

        anyio.from_thread.run(manager.broadcast, league_id, message)
    except Exception:
        log.exception("failed to broadcast for league %s", league_id)
