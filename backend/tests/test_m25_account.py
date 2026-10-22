"""Milestone 25 backend tests: password change, account deletion, and the
predictions that have to outlive the account that made them.

The point of the milestone is that deleting an account does not quietly
rewrite anybody else's score: a prediction stays, the picks other members
made on it stay, and their points stay.
"""

import threading
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from starlette.websockets import WebSocketDisconnect

from app import models
from app.database import SessionLocal, engine
from app.main import app
from app.security import create_access_token, hash_password


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


def _make_user(password="pass123456"):
    """Create a user directly and return its ids, password and headers."""
    tag = uuid.uuid4().hex[:10]
    db = SessionLocal()
    try:
        user = models.User(
            email=f"m25-{tag}@example.com",
            nickname=f"m25-{tag}",
            password_hash=hash_password(password),
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return {
            "id": user.id,
            "email": user.email,
            "nickname": user.nickname,
            "password": password,
            "token": create_access_token(str(user.id)),
            "headers": {"Authorization": f"Bearer {create_access_token(str(user.id))}"},
        }
    finally:
        db.close()


def _make_league(owner_id, name="M25 League"):
    """A league with its owner as the only member."""
    tag = uuid.uuid4().hex[:10]
    db = SessionLocal()
    try:
        league = models.League(
            name=name, invite_code=f"m25-{tag}", owner_id=owner_id
        )
        db.add(league)
        db.commit()
        db.refresh(league)
        db.add(models.Membership(league_id=league.id, user_id=owner_id))
        db.commit()
        return league.id
    finally:
        db.close()


def _add_member(league_id, user_id):
    db = SessionLocal()
    try:
        db.add(models.Membership(league_id=league_id, user_id=user_id))
        db.commit()
    finally:
        db.close()


def _prediction_row(prediction_id):
    db = SessionLocal()
    try:
        row = (
            db.query(models.Prediction)
            .filter(models.Prediction.id == prediction_id)
            .first()
        )
        if row is None:
            return None
        return {
            "id": row.id,
            "status": row.status,
            "creator_id": row.creator_id,
            "resolution_source": row.resolution_source,
        }
    finally:
        db.close()


def _pick_count(prediction_id):
    db = SessionLocal()
    try:
        return (
            db.query(models.Pick)
            .filter(models.Pick.prediction_id == prediction_id)
            .count()
        )
    finally:
        db.close()


def _expect_disconnect(session, timeout=5.0):
    """Wait for the server to close the socket."""
    errors = []

    def _pump():
        try:
            session.receive_json()
        except Exception as exc:
            errors.append(exc)

    thread = threading.Thread(target=_pump, daemon=True)
    thread.start()
    thread.join(timeout)
    assert not thread.is_alive(), "the socket was never closed"
    assert errors, "the socket was closed without an error"


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


# --------------------------------------------------------------------------
# change password
# --------------------------------------------------------------------------


def test_change_password_rejects_a_wrong_current_password(client):
    user = _make_user()
    r = client.post(
        "/api/auth/change-password",
        json={"current_password": "not-my-password", "new_password": "newpass12345"},
        headers=user["headers"],
    )
    assert r.status_code == 400, r.text
    assert r.json()["detail"] == "Current password is incorrect"
    # the old password still works
    login = client.post(
        "/api/auth/login",
        json={"email": user["email"], "password": user["password"]},
    )
    assert login.status_code == 200, login.text


def test_change_password_rejects_the_same_password(client):
    user = _make_user()
    r = client.post(
        "/api/auth/change-password",
        json={"current_password": user["password"], "new_password": user["password"]},
        headers=user["headers"],
    )
    assert r.status_code == 400, r.text
    assert r.json()["detail"] == "New password must be different from the current password"


def test_change_password_rejects_a_short_new_password(client):
    user = _make_user()
    r = client.post(
        "/api/auth/change-password",
        json={"current_password": user["password"], "new_password": "short"},
        headers=user["headers"],
    )
    assert r.status_code == 422, r.text


def test_change_password_needs_a_session(client):
    r = client.post(
        "/api/auth/change-password",
        json={"current_password": "pass123456", "new_password": "newpass12345"},
    )
    assert r.status_code == 401, r.text


def test_change_password_changes_the_password_and_keeps_the_session(client):
    user = _make_user()
    r = client.post(
        "/api/auth/change-password",
        json={"current_password": user["password"], "new_password": "newpass12345"},
        headers=user["headers"],
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["access_token"] and body["refresh_token"]

    # the new password works, the old one does not
    assert (
        client.post(
            "/api/auth/login",
            json={"email": user["email"], "password": "newpass12345"},
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/api/auth/login",
            json={"email": user["email"], "password": user["password"]},
        ).status_code
        == 401
    )

    # the token that was handed out with the change works
    me = client.get(
        "/api/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"}
    )
    assert me.status_code == 200, me.text
    assert me.json()["email"] == user["email"]


def test_change_password_kills_the_old_tokens(client):
    """The token version moves, so every old access token stops working."""
    user = _make_user()
    r = client.post(
        "/api/auth/change-password",
        json={"current_password": user["password"], "new_password": "newpass12345"},
        headers=user["headers"],
    )
    assert r.status_code == 200, r.text

    # the access token the change was made with is dead
    me = client.get("/api/auth/me", headers=user["headers"])
    assert me.status_code == 401, me.text


def test_change_password_leaves_other_accounts_alone(client):
    user = _make_user()
    other = _make_user()
    r = client.post(
        "/api/auth/change-password",
        json={"current_password": user["password"], "new_password": "newpass12345"},
        headers=user["headers"],
    )
    assert r.status_code == 200, r.text

    me = client.get("/api/auth/me", headers=other["headers"])
    assert me.status_code == 200, me.text


# --------------------------------------------------------------------------
# delete account
# --------------------------------------------------------------------------


def test_delete_account_rejects_a_wrong_password(client):
    user = _make_user()
    r = client.post(
        "/api/auth/delete-account",
        json={"password": "not-my-password"},
        headers=user["headers"],
    )
    assert r.status_code == 400, r.text
    assert r.json()["detail"] == "Password is incorrect"
    # the account is still there
    me = client.get("/api/auth/me", headers=user["headers"])
    assert me.status_code == 200, me.text


def test_delete_account_needs_a_session(client):
    r = client.post("/api/auth/delete-account", json={"password": "pass123456"})
    assert r.status_code == 401, r.text


def test_delete_account_refuses_while_owning_a_league_with_other_members(client):
    user = _make_user()
    other = _make_user()
    league_id = _make_league(user["id"])
    _add_member(league_id, other["id"])

    r = client.post(
        "/api/auth/delete-account",
        json={"password": user["password"]},
        headers=user["headers"],
    )
    assert r.status_code == 409, r.text
    assert r.json()["detail"] == (
        "Transfer or delete the leagues you own that have other members first"
    )
    # nothing was deleted
    me = client.get("/api/auth/me", headers=user["headers"])
    assert me.status_code == 200, me.text


def test_delete_account_removes_a_league_with_only_the_owner(client):
    user = _make_user()
    league_id = _make_league(user["id"])

    r = client.post(
        "/api/auth/delete-account",
        json={"password": user["password"]},
        headers=user["headers"],
    )
    assert r.status_code == 200, r.text
    assert r.json() == {"ok": True}

    me = client.get("/api/auth/me", headers=user["headers"])
    assert me.status_code == 401, me.text

    db = SessionLocal()
    try:
        assert db.get(models.League, league_id) is None
    finally:
        db.close()


def test_delete_account_keeps_predictions_and_other_members_points(client):
    """The heart of M25: the prediction and its points survive the creator."""
    creator = _make_user()
    member = _make_user()
    league_id = _make_league(member["id"])
    _add_member(league_id, creator["id"])

    created = client.post(
        f"/api/leagues/{league_id}/predictions",
        json={"question": "Does the prediction outlive its creator?"},
        headers=creator["headers"],
    )
    assert created.status_code == 201, created.text
    prediction_id = created.json()["id"]

    # the member picks yes with 5 points, the creator picks no with 3
    assert (
        client.post(
            f"/api/predictions/{prediction_id}/pick",
            json={"side": "yes", "stake": 5},
            headers=member["headers"],
        ).status_code
        == 201
    )
    assert (
        client.post(
            f"/api/predictions/{prediction_id}/pick",
            json={"side": "no", "stake": 3},
            headers=creator["headers"],
        ).status_code
        == 201
    )
    resolved = client.post(
        f"/api/predictions/{prediction_id}/resolve",
        json={"outcome": "yes"},
        headers=creator["headers"],
    )
    assert resolved.status_code == 200, resolved.text

    before = client.get(
        f"/api/leagues/{league_id}/leaderboard", headers=member["headers"]
    ).json()
    member_before = next(e for e in before if e["user_id"] == member["id"])
    assert member_before["points"] == 5, member_before

    r = client.post(
        "/api/auth/delete-account",
        json={"password": creator["password"]},
        headers=creator["headers"],
    )
    assert r.status_code == 200, r.text

    # the prediction is still there, but nobody owns it any more
    row = _prediction_row(prediction_id)
    assert row is not None, "the prediction was deleted with its creator"
    assert row["creator_id"] is None
    assert row["status"] == "resolved"
    # the member's pick survived
    assert _pick_count(prediction_id) == 1

    # and the points are untouched
    after = client.get(
        f"/api/leagues/{league_id}/leaderboard", headers=member["headers"]
    ).json()
    member_after = next(e for e in after if e["user_id"] == member["id"])
    assert member_after["points"] == 5, member_after
    assert member_after["total"] == 1, member_after


def test_delete_account_voids_open_predictions_they_made(client):
    creator = _make_user()
    member = _make_user()
    league_id = _make_league(member["id"])
    _add_member(league_id, creator["id"])

    created = client.post(
        f"/api/leagues/{league_id}/predictions",
        json={"question": "Will this be voided?"},
        headers=creator["headers"],
    )
    assert created.status_code == 201, created.text
    prediction_id = created.json()["id"]

    r = client.post(
        "/api/auth/delete-account",
        json={"password": creator["password"]},
        headers=creator["headers"],
    )
    assert r.status_code == 200, r.text

    row = _prediction_row(prediction_id)
    assert row is not None
    assert row["status"] == "void", row
    assert row["creator_id"] is None

    # a void prediction cannot be picked on and cannot be resolved
    pick = client.post(
        f"/api/predictions/{prediction_id}/pick",
        json={"side": "yes", "stake": 1},
        headers=member["headers"],
    )
    assert pick.status_code == 409, pick.text


def test_delete_account_keeps_self_resolving_predictions_open(client):
    """A game that settles itself can still settle itself after the creator left."""
    creator = _make_user()
    member = _make_user()
    league_id = _make_league(member["id"])
    _add_member(league_id, creator["id"])

    created = client.post(
        f"/api/leagues/{league_id}/predictions",
        json={"question": "Who wins the game?"},
        headers=creator["headers"],
    )
    assert created.status_code == 201, created.text
    prediction_id = created.json()["id"]

    db = SessionLocal()
    try:
        row = db.get(models.Prediction, prediction_id)
        row.resolution_source = "auto"
        row.external_game_id = "401547417"
        row.sport = "nfl"
        db.commit()
    finally:
        db.close()

    r = client.post(
        "/api/auth/delete-account",
        json={"password": creator["password"]},
        headers=creator["headers"],
    )
    assert r.status_code == 200, r.text

    row = _prediction_row(prediction_id)
    assert row is not None
    assert row["status"] == "open", row
    assert row["creator_id"] is None


def test_delete_account_removes_their_own_picks(client):
    member = _make_user()
    picker = _make_user()
    league_id = _make_league(member["id"])
    _add_member(league_id, picker["id"])

    created = client.post(
        f"/api/leagues/{league_id}/predictions",
        json={"question": "Who is right?"},
        headers=member["headers"],
    )
    prediction_id = created.json()["id"]
    client.post(
        f"/api/predictions/{prediction_id}/pick",
        json={"side": "yes", "stake": 4},
        headers=picker["headers"],
    )
    client.post(
        f"/api/predictions/{prediction_id}/resolve",
        json={"outcome": "yes"},
        headers=member["headers"],
    )

    r = client.post(
        "/api/auth/delete-account",
        json={"password": picker["password"]},
        headers=picker["headers"],
    )
    assert r.status_code == 200, r.text

    board = client.get(
        f"/api/leagues/{league_id}/leaderboard", headers=member["headers"]
    ).json()
    assert all(e["user_id"] != picker["id"] for e in board), board


# --------------------------------------------------------------------------
# websockets
# --------------------------------------------------------------------------


def test_the_websocket_is_closed_when_the_password_changes(client):
    user = _make_user()
    league_id = _make_league(user["id"])

    with client.websocket_connect(
        f"/ws/leagues/{league_id}?token={user['token']}"
    ) as session:
        r = client.post(
            "/api/auth/change-password",
            json={"current_password": user["password"], "new_password": "newpass12345"},
            headers=user["headers"],
        )
        assert r.status_code == 200, r.text
        _expect_disconnect(session)


def test_the_websocket_rejects_a_token_from_before_a_password_change(client):
    user = _make_user()
    league_id = _make_league(user["id"])

    r = client.post(
        "/api/auth/change-password",
        json={"current_password": user["password"], "new_password": "newpass12345"},
        headers=user["headers"],
    )
    assert r.status_code == 200, r.text

    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(
            f"/ws/leagues/{league_id}?token={user['token']}"
        ):
            pass


def test_the_websocket_rejects_a_deleted_account(client):
    user = _make_user()
    league_id = _make_league(user["id"])

    r = client.post(
        "/api/auth/delete-account",
        json={"password": user["password"]},
        headers=user["headers"],
    )
    assert r.status_code == 200, r.text

    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(
            f"/ws/leagues/{league_id}?token={user['token']}"
        ):
            pass


def test_the_database_keeps_the_prediction_of_a_deleted_creator(client):
    """The column is nullable and the foreign key sets it to null."""
    creator = _make_user()
    member = _make_user()
    league_id = _make_league(member["id"])
    _add_member(league_id, creator["id"])
    created = client.post(
        f"/api/leagues/{league_id}/predictions",
        json={"question": "Kept?"},
        headers=creator["headers"],
    )
    prediction_id = created.json()["id"]

    r = client.post(
        "/api/auth/delete-account",
        json={"password": creator["password"]},
        headers=creator["headers"],
    )
    assert r.status_code == 200, r.text

    with engine.connect() as conn:
        value = conn.execute(
            text("SELECT creator_id FROM predictions WHERE id = :id"),
            {"id": prediction_id},
        ).scalar()
    assert value is None
