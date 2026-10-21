from __future__ import annotations

import json
from typing import Any

from fastapi import WebSocket


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
                await ws.send_text(data)
            except Exception:
                try:
                    self.disconnect(league_id, ws)
                except Exception:
                    pass


manager = ConnectionManager()
