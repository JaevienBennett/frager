"""Milestone 19 backend tests: league management (rename / delete / leave)."""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app import models
from app.database import SessionLocal
from app.main import app
from app.security import create_access_token, hash_password


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


def _make_user():
    """Create a user directly and mint a token for it.

    Signing up over HTTP is rate limited (5/minute per IP), which would make
    these tests flaky, so users are created straight in the database.
    """
    tag = uuid.uuid4().hex[:10]
    db = SessionLocal()
    try:
        user = models.User(
            email=f"m19-{tag}@example.com",
            nickname=f"m19-{tag}",
            password_hash=hash_password("pass123456"),
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user.id, {"Authorization": f"Bearer {create_access_token(str(user.id))}"}
    finally:
        db.close()


def _make_league(client, owner_headers, name=None):
    if name is None:
        name = f"M19 League {uuid.uuid4().hex[:8]}"
    r = client.post("/api/leagues", json={"name": name}, headers=owner_headers)
    assert r.status_code == 201, r.text
    return r.json()


def _add_member(client, league, headers):
    r = client.post(
        "/api/leagues/join", json={"invite_code": league["invite_code"]}, headers=headers
    )
    assert r.status_code == 200, r.text
    return r.json()


def _counts(db, league_id):
    return {
        "memberships": db.query(models.Membership)
        .filter(models.Membership.league_id == league_id)
        .count(),
        "predictions": db.query(models.Prediction)
        .filter(models.Prediction.league_id == league_id)
        .count(),
        "picks": db.query(models.Pick)
        .join(models.Prediction, models.Prediction.id == models.Pick.prediction_id)
        .filter(models.Prediction.league_id == league_id)
        .count(),
    }


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


@pytest.fixture
def owner():
    return _make_user()


@pytest.fixture
def member():
    return _make_user()


@pytest.fixture
def outsider():
    return _make_user()


# --------------------------------------------------------------------------
# PATCH /api/leagues/{league_id}
# --------------------------------------------------------------------------


def test_owner_can_rename_league(client, owner):
    _, owner_headers = owner
    league = _make_league(client, owner_headers)

    r = client.patch(
        f"/api/leagues/{league['id']}",
        json={"name": "  Renamed League  "},
        headers=owner_headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["name"] == "Renamed League"
    assert body["id"] == league["id"]
    assert body["owner_id"] == league["owner_id"]

    db = SessionLocal()
    try:
        assert db.get(models.League, league["id"]).name == "Renamed League"
    finally:
        db.close()


@pytest.mark.parametrize("name", ["", "   ", "\t\n "])
def test_rename_rejects_blank_name(client, owner, name):
    _, owner_headers = owner
    league = _make_league(client, owner_headers)

    r = client.patch(
        f"/api/leagues/{league['id']}", json={"name": name}, headers=owner_headers
    )
    assert r.status_code == 422, r.text


def test_rename_rejects_name_over_100_chars(client, owner):
    _, owner_headers = owner
    league = _make_league(client, owner_headers)

    r = client.patch(
        f"/api/leagues/{league['id']}",
        json={"name": "x" * 101},
        headers=owner_headers,
    )
    assert r.status_code == 422, r.text


def test_rename_accepts_name_of_exactly_100_chars(client, owner):
    _, owner_headers = owner
    league = _make_league(client, owner_headers)

    r = client.patch(
        f"/api/leagues/{league['id']}",
        json={"name": "y" * 100},
        headers=owner_headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["name"] == "y" * 100


def test_rename_by_non_owner_member_is_forbidden(client, owner, member):
    _, owner_headers = owner
    _, member_headers = member
    league = _make_league(client, owner_headers)
    _add_member(client, league, member_headers)

    r = client.patch(
        f"/api/leagues/{league['id']}",
        json={"name": "Hijacked"},
        headers=member_headers,
    )
    assert r.status_code == 403, r.text
    assert r.json()["detail"] == "Only the league owner can rename it"

    db = SessionLocal()
    try:
        assert db.get(models.League, league["id"]).name == league["name"]
    finally:
        db.close()


def test_rename_by_non_member_is_not_found(client, owner, outsider):
    _, owner_headers = owner
    _, outsider_headers = outsider
    league = _make_league(client, owner_headers)

    r = client.patch(
        f"/api/leagues/{league['id']}",
        json={"name": "Nope"},
        headers=outsider_headers,
    )
    assert r.status_code == 404, r.text
    assert r.json()["detail"] == "League not found"


def test_rename_missing_league_is_not_found(client, owner):
    _, owner_headers = owner

    r = client.patch(
        "/api/leagues/99999999", json={"name": "Nope"}, headers=owner_headers
    )
    assert r.status_code == 404, r.text
    assert r.json()["detail"] == "League not found"


# --------------------------------------------------------------------------
# DELETE /api/leagues/{league_id}
# --------------------------------------------------------------------------


def test_owner_can_delete_league_and_rows_cascade(client, owner, member):
    _, owner_headers = owner
    _, member_headers = member
    league = _make_league(client, owner_headers)
    _add_member(client, league, member_headers)

    pred = client.post(
        f"/api/leagues/{league['id']}/predictions",
        json={"question": "Will it cascade?"},
        headers=owner_headers,
    )
    assert pred.status_code == 201, pred.text
    prediction_id = pred.json()["id"]
    pick = client.post(
        f"/api/predictions/{prediction_id}/pick",
        json={"side": "yes", "stake": 10},
        headers=member_headers,
    )
    assert pick.status_code == 201, pick.text

    db = SessionLocal()
    try:
        before = _counts(db, league["id"])
        assert before == {"memberships": 2, "predictions": 1, "picks": 1}
    finally:
        db.close()

    r = client.delete(f"/api/leagues/{league['id']}", headers=owner_headers)
    assert r.status_code == 200, r.text
    assert r.json() == {"ok": True}

    db = SessionLocal()
    try:
        assert db.get(models.League, league["id"]) is None
        assert _counts(db, league["id"]) == {
            "memberships": 0,
            "predictions": 0,
            "picks": 0,
        }
        assert db.get(models.Pick, pick.json()["id"]) is None
    finally:
        db.close()


def test_delete_by_non_owner_member_is_forbidden(client, owner, member):
    _, owner_headers = owner
    _, member_headers = member
    league = _make_league(client, owner_headers)
    _add_member(client, league, member_headers)

    r = client.delete(f"/api/leagues/{league['id']}", headers=member_headers)
    assert r.status_code == 403, r.text
    assert r.json()["detail"] == "Only the league owner can delete it"

    db = SessionLocal()
    try:
        assert db.get(models.League, league["id"]) is not None
    finally:
        db.close()


def test_delete_by_non_member_is_not_found(client, owner, outsider):
    _, owner_headers = owner
    _, outsider_headers = outsider
    league = _make_league(client, owner_headers)

    r = client.delete(f"/api/leagues/{league['id']}", headers=outsider_headers)
    assert r.status_code == 404, r.text
    assert r.json()["detail"] == "League not found"


def test_delete_missing_league_is_not_found(client, owner):
    _, owner_headers = owner

    r = client.delete("/api/leagues/99999999", headers=owner_headers)
    assert r.status_code == 404, r.text
    assert r.json()["detail"] == "League not found"


# --------------------------------------------------------------------------
# POST /api/leagues/{league_id}/leave
# --------------------------------------------------------------------------


def test_member_can_leave_league(client, owner, member):
    _, owner_headers = owner
    _, member_headers = member
    league = _make_league(client, owner_headers)
    _add_member(client, league, member_headers)

    pred = client.post(
        f"/api/leagues/{league['id']}/predictions",
        json={"question": "Will the league survive?"},
        headers=member_headers,
    )
    assert pred.status_code == 201, pred.text
    prediction_id = pred.json()["id"]
    pick = client.post(
        f"/api/predictions/{prediction_id}/pick",
        json={"side": "no", "stake": 5},
        headers=member_headers,
    )
    assert pick.status_code == 201, pick.text

    r = client.post(f"/api/leagues/{league['id']}/leave", headers=member_headers)
    assert r.status_code == 200, r.text
    assert r.json() == {"ok": True}

    db = SessionLocal()
    try:
        # the member's membership is gone ...
        assert (
            db.query(models.Membership)
            .filter(
                models.Membership.league_id == league["id"],
                models.Membership.user_id == member[0],
            )
            .count()
            == 0
        )
        # ... but the league, the prediction and the pick are untouched
        assert db.get(models.League, league["id"]) is not None
        assert db.get(models.Prediction, prediction_id) is not None
        assert db.get(models.Pick, pick.json()["id"]) is not None
    finally:
        db.close()


def test_owner_cannot_leave_league(client, owner):
    _, owner_headers = owner
    league = _make_league(client, owner_headers)

    r = client.post(f"/api/leagues/{league['id']}/leave", headers=owner_headers)
    assert r.status_code == 409, r.text
    assert r.json()["detail"] == "Owner cannot leave; delete the league instead"

    db = SessionLocal()
    try:
        assert db.get(models.League, league["id"]) is not None
        assert (
            db.query(models.Membership)
            .filter(
                models.Membership.league_id == league["id"],
                models.Membership.user_id == owner[0],
            )
            .count()
            == 1
        )
    finally:
        db.close()


def test_leave_by_non_member_is_not_found(client, owner, outsider):
    _, owner_headers = owner
    _, outsider_headers = outsider
    league = _make_league(client, owner_headers)

    r = client.post(f"/api/leagues/{league['id']}/leave", headers=outsider_headers)
    assert r.status_code == 404, r.text
    assert r.json()["detail"] == "League not found"


def test_leave_missing_league_is_not_found(client, owner):
    _, owner_headers = owner

    r = client.post("/api/leagues/99999999/leave", headers=owner_headers)
    assert r.status_code == 404, r.text
    assert r.json()["detail"] == "League not found"


def test_leave_requires_authentication(client, owner):
    _, owner_headers = owner
    league = _make_league(client, owner_headers)

    r = client.post(f"/api/leagues/{league['id']}/leave")
    assert r.status_code in (401, 403), r.text
