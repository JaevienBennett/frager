from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Callable, Coroutine

from fastapi import WebSocket

log = logging.getLogger(__name__)

# How long a single websocket send may take before it is treated as a dead
# connection. Without this one stalled client blocks the whole broadcast.
SEND_TIMEOUT_SECONDS = 5.0


class ConnectionManager:
    def __init__(self) -> None:
        # league_id -> set of websockets
        self.active: dict[int, set[WebSocket]] = {}
        # user id -> set of websockets
        self.by_user: dict[int, set[WebSocket]] = {}
        # websocket -> user id
        self.socket_user: dict[WebSocket, int] = {}
        # websocket -> league id
        self.socket_league: dict[WebSocket, int] = {}

    async def connect(
        self, league_id: int, websocket: WebSocket, user_id: int | None = None
    ) -> None:
        await websocket.accept()
        self.active.setdefault(league_id, set()).add(websocket)
        self.socket_league[websocket] = league_id
        if user_id is not None:
            self.by_user.setdefault(user_id, set()).add(websocket)
            self.socket_user[websocket] = user_id

    def disconnect(self, league_id: int, websocket: WebSocket) -> None:
        conns = self.active.get(league_id)
        if conns:
            conns.discard(websocket)
            if not conns:
                self.active.pop(league_id, None)
        self.socket_league.pop(websocket, None)
        user_id = self.socket_user.pop(websocket, None)
        if user_id is not None:
            user_socks = self.by_user.get(user_id)
            if user_socks:
                user_socks.discard(websocket)
                if not user_socks:
                    self.by_user.pop(user_id, None)

    async def drop(self, league_id: int, websocket: WebSocket) -> None:
        """Forget a dead socket and close it.

        Closing matters: without it the browser never sees the socket go
        away, so it never reconnects and the tab silently stops receiving
        updates.
        """
        self.disconnect(league_id, websocket)
        try:
            await websocket.close()
        except Exception:
            log.debug("websocket close failed", exc_info=True)

    async def close_user(self, user_id: int) -> int:
        """Close every live socket of one user (password change, account delete)."""
        sockets = list(self.by_user.get(user_id, set()))
        for websocket in sockets:
            league_id = self.socket_league.get(websocket)
            if league_id is not None:
                await self.drop(league_id, websocket)
            else:
                self.socket_user.pop(websocket, None)
        self.by_user.pop(user_id, None)
        return len(sockets)

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
                await self.drop(league_id, ws)
            except Exception:
                log.warning(
                    "websocket send failed for league %s; dropping connection",
                    league_id,
                    exc_info=True,
                )
                await self.drop(league_id, ws)


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


def _schedule(make_coro: Callable[[], Coroutine[Any, Any, Any]]) -> None:
    """Run a coroutine on the loop that owns the websockets.

    Safe to call from a sync endpoint (worker thread), from the event loop
    itself, and from a plain script.
    """
    try:
        running = asyncio.get_running_loop()
    except RuntimeError:
        running = None

    if running is not None:
        # Already on the event loop: schedule and move on.
        task = running.create_task(make_coro())
        task.add_done_callback(_report_failure)
        return

    if _loop is not None and not _loop.is_closed():
        try:
            future = asyncio.run_coroutine_threadsafe(make_coro(), _loop)
            future.add_done_callback(_report_failure)
        except Exception:
            log.exception("failed to schedule websocket work")
        return

    # No startup loop captured (e.g. a test client without the lifespan
    # running): hop back onto the loop this worker thread belongs to.
    try:
        import anyio

        anyio.from_thread.run(make_coro)
    except Exception:
        log.exception("failed to run websocket work")


def broadcast_nowait(league_id: int, message: dict[str, Any]) -> None:
    """Broadcast to a league without blocking the calling thread."""
    _schedule(lambda: manager.broadcast(league_id, message))


def close_user_nowait(user_id: int) -> None:
    """Close a user's live sockets without blocking the calling thread."""
    _schedule(lambda: manager.close_user(user_id))
