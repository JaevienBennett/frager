"""Milestone 22 backend tests: websocket broadcasts actually reach clients.

Every endpoint that touches a league is a sync function, so FastAPI runs it in
a worker thread. `asyncio.create_task` has no event loop there, so the
broadcast was raised away and never sent: live updates had never worked.
"""

import threading
import uuid
import warnings

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app import models, ws
from app.database import SessionLocal
from app.main import app
from app.security import create_access_token, hash_password


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


def _make_user():
    """Create a user plus a league directly and return ids and headers."""
    tag = uuid.uuid4().hex[:10]
    db = SessionLocal()
    try:
        user = models.User(
            email=f"m22-{tag}@example.com",
            nickname=f"m22-{tag}",
            password_hash=hash_password("pass123456"),
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        league = models.League(
            name=f"M22 League {tag}",
            invite_code=f"m22-{tag}",
            owner_id=user.id,
        )
        db.add(league)
        db.commit()
        db.refresh(league)
        db.add(models.Membership(league_id=league.id, user_id=user.id))
        db.commit()
        return {
            "user_id": user.id,
            "league_id": league.id,
            "headers": {"Authorization": f"Bearer {create_access_token(str(user.id))}"},
            "token": create_access_token(str(user.id)),
        }
    finally:
        db.close()


def _receive_until(session, wanted_type, timeout=10.0):
    """Collect websocket messages until one of `wanted_type` shows up.

    `WebSocketTestSession.receive` blocks forever when nothing is sent, so the
    wait is done on a helper thread with a deadline.
    """
    messages = []
    result = {}

    def _pump():
        try:
            while True:
                messages.append(session.receive_json())
                if messages[-1].get("type") == wanted_type:
                    result["found"] = messages[-1]
                    return
        except Exception as exc:  # closed socket, json error, ...
            result["error"] = exc

    thread = threading.Thread(target=_pump, daemon=True)
    thread.start()
    thread.join(timeout)
    if "found" in result:
        return result["found"], messages
    if "error" in result:
        raise AssertionError(f"websocket receive failed: {result['error']!r}")
    raise AssertionError(
        f"timed out after {timeout}s waiting for {wanted_type!r}; got {messages!r}"
    )


# --------------------------------------------------------------------------
# tests
# --------------------------------------------------------------------------


def test_pick_broadcast_reaches_connected_client():
    """A pick made over HTTP must show up on an open websocket."""
    ctx = _make_user()

    with TestClient(app) as client:
        created = client.post(
            f"/api/leagues/{ctx['league_id']}/predictions",
            json={"question": "Does the broadcast arrive?"},
            headers=ctx["headers"],
        )
        assert created.status_code == 201, created.text
        prediction_id = created.json()["id"]

        with client.websocket_connect(
            f"/ws/leagues/{ctx['league_id']}?token={ctx['token']}"
        ) as session:
            picked = client.post(
                f"/api/predictions/{prediction_id}/pick",
                json={"side": "yes", "stake": 10},
                headers=ctx["headers"],
            )
            assert picked.status_code == 201, picked.text

            message, _ = _receive_until(session, "pick_updated")
            assert message["league_id"] == ctx["league_id"]
            assert message["prediction_id"] == prediction_id


def test_prediction_creation_broadcast_reaches_connected_client():
    ctx = _make_user()

    with TestClient(app) as client:
        with client.websocket_connect(
            f"/ws/leagues/{ctx['league_id']}?token={ctx['token']}"
        ) as session:
            created = client.post(
                f"/api/leagues/{ctx['league_id']}/predictions",
                json={"question": "Created while watching?"},
                headers=ctx["headers"],
            )
            assert created.status_code == 201, created.text

            message, _ = _receive_until(session, "prediction_created")
            assert message["prediction_id"] == created.json()["id"]


def test_broadcast_does_not_leak_an_unawaited_coroutine():
    """The old code created a coroutine and threw it away on the floor."""
    ctx = _make_user()

    with TestClient(app) as client:
        created = client.post(
            f"/api/leagues/{ctx['league_id']}/predictions",
            json={"question": "Any stray coroutines?"},
            headers=ctx["headers"],
        )
        assert created.status_code == 201, created.text
        prediction_id = created.json()["id"]

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            picked = client.post(
                f"/api/predictions/{prediction_id}/pick",
                json={"side": "no", "stake": 1},
                headers=ctx["headers"],
            )
            assert picked.status_code == 201, picked.text
        offenders = [
            str(w.message)
            for w in caught
            if issubclass(w.category, RuntimeWarning) and "never awaited" in str(w.message)
        ]
        assert offenders == []


def test_a_broadcast_from_a_plain_thread_reaches_a_connected_client():
    """The helper is also called from places without an event loop.

    The old test only checked that nothing was raised, which cannot fail:
    the helper swallows every error. This one checks that the message really
    arrives.
    """
    ctx = _make_user()
    errors = []

    with TestClient(app) as client:
        with client.websocket_connect(
            f"/ws/leagues/{ctx['league_id']}?token={ctx['token']}"
        ) as session:

            def _worker():
                try:
                    ws.broadcast_nowait(
                        ctx["league_id"],
                        {
                            "type": "leaderboard_updated",
                            "league_id": ctx["league_id"],
                        },
                    )
                except Exception as exc:  # pragma: no cover - must not happen
                    errors.append(exc)

            thread = threading.Thread(target=_worker)
            thread.start()
            thread.join(5)
            assert not thread.is_alive()
            assert errors == []

            message, _ = _receive_until(session, "leaderboard_updated")
            assert message["league_id"] == ctx["league_id"]


def test_websocket_rejects_a_stranger():
    ctx = _make_user()
    other = _make_user()

    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect(
                f"/ws/leagues/{ctx['league_id']}?token={other['token']}"
            ):
                pass


def test_websocket_rejects_a_bad_token():
    ctx = _make_user()

    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect(
                f"/ws/leagues/{ctx['league_id']}?token=not-a-token"
            ):
                pass
