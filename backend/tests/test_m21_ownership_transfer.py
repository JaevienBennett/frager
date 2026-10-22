"""Milestone 21 backend tests: league ownership transfer.

The owner of a league could not hand it over, so an owner who wanted out was
stuck: leaving is refused for owners and the league could only be deleted.
"""

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

    Signing up over HTTP is rate limited, so users are created straight in the
    database the way the other milestone suites do it.
    """
    tag = uuid.uuid4().hex[:10]
    db = SessionLocal()
    try:
        user = models.User(
            email=f"m21-{tag}@example.com",
            nickname=f"m21-{tag}",
            password_hash=hash_password("pass123456"),
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user.id, {"Authorization": f"Bearer {create_access_token(str(user.id))}"}
    finally:
        db.close()


def _make_league(client, owner_headers):
    name = f"M21 League {uuid.uuid4().hex[:8]}"
    r = client.post("/api/leagues", json={"name": name}, headers=owner_headers)
    assert r.status_code == 201, r.text
    return r.json()


def _add_member(client, league, headers):
    r = client.post(
        "/api/leagues/join", json={"invite_code": league["invite_code"]}, headers=headers
    )
    assert r.status_code == 200, r.text
    return r.json()


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
# GET /api/leagues/{league_id}/members
# --------------------------------------------------------------------------


def test_members_list_contains_owner_and_member(client, owner, member):
    _, owner_headers = owner
    _, member_headers = member
    league = _make_league(client, owner_headers)
    _add_member(client, league, member_headers)

    r = client.get(f"/api/leagues/{league['id']}/members", headers=owner_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    by_id = {m["user_id"]: m for m in body}
    assert set(by_id) == {owner[0], member[0]}
    assert by_id[owner[0]]["is_owner"] is True
    assert by_id[member[0]]["is_owner"] is False
    assert all("email" not in m for m in body)


def test_members_requires_membership(client, owner, outsider):
    _, owner_headers = owner
    _, outsider_headers = outsider
    league = _make_league(client, owner_headers)

    r = client.get(f"/api/leagues/{league['id']}/members", headers=outsider_headers)
    assert r.status_code == 404, r.text
    assert r.json()["detail"] == "League not found"


def test_members_requires_authentication(client, owner):
    _, owner_headers = owner
    league = _make_league(client, owner_headers)

    r = client.get(f"/api/leagues/{league['id']}/members")
    assert r.status_code in (401, 403), r.text


# --------------------------------------------------------------------------
# POST /api/leagues/{league_id}/transfer
# --------------------------------------------------------------------------


def test_owner_can_transfer_ownership(client, owner, member):
    _, owner_headers = owner
    _, member_headers = member
    league = _make_league(client, owner_headers)
    _add_member(client, league, member_headers)

    r = client.post(
        f"/api/leagues/{league['id']}/transfer",
        json={"new_owner_id": member[0]},
        headers=owner_headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["owner_id"] == member[0]

    db = SessionLocal()
    try:
        assert db.get(models.League, league["id"]).owner_id == member[0]
        # both users are still members
        assert (
            db.query(models.Membership)
            .filter(models.Membership.league_id == league["id"])
            .count()
            == 2
        )
    finally:
        db.close()


def test_new_owner_can_manage_league(client, owner, member):
    _, owner_headers = owner
    _, member_headers = member
    league = _make_league(client, owner_headers)
    _add_member(client, league, member_headers)
    client.post(
        f"/api/leagues/{league['id']}/transfer",
        json={"new_owner_id": member[0]},
        headers=owner_headers,
    )

    r = client.patch(
        f"/api/leagues/{league['id']}", json={"name": "New Owners League"}, headers=member_headers
    )
    assert r.status_code == 200, r.text
    assert r.json()["name"] == "New Owners League"


def test_old_owner_can_leave_after_transfer(client, owner, member):
    _, owner_headers = owner
    _, member_headers = member
    league = _make_league(client, owner_headers)
    _add_member(client, league, member_headers)
    client.post(
        f"/api/leagues/{league['id']}/transfer",
        json={"new_owner_id": member[0]},
        headers=owner_headers,
    )

    r = client.post(f"/api/leagues/{league['id']}/leave", headers=owner_headers)
    assert r.status_code == 200, r.text
    assert r.json() == {"ok": True}


def test_new_owner_cannot_leave(client, owner, member):
    _, owner_headers = owner
    _, member_headers = member
    league = _make_league(client, owner_headers)
    _add_member(client, league, member_headers)
    client.post(
        f"/api/leagues/{league['id']}/transfer",
        json={"new_owner_id": member[0]},
        headers=owner_headers,
    )

    r = client.post(f"/api/leagues/{league['id']}/leave", headers=member_headers)
    assert r.status_code == 409, r.text
    assert (
        r.json()["detail"]
        == "Owner cannot leave; transfer ownership or delete the league instead"
    )


def test_transfer_by_non_owner_is_forbidden(client, owner, member):
    _, owner_headers = owner
    _, member_headers = member
    league = _make_league(client, owner_headers)
    _add_member(client, league, member_headers)

    r = client.post(
        f"/api/leagues/{league['id']}/transfer",
        json={"new_owner_id": owner[0]},
        headers=member_headers,
    )
    assert r.status_code == 403, r.text
    assert r.json()["detail"] == "Only the league owner can transfer ownership"

    db = SessionLocal()
    try:
        assert db.get(models.League, league["id"]).owner_id == owner[0]
    finally:
        db.close()


def test_transfer_to_non_member_is_not_found(client, owner, outsider):
    _, owner_headers = owner
    league = _make_league(client, owner_headers)

    r = client.post(
        f"/api/leagues/{league['id']}/transfer",
        json={"new_owner_id": outsider[0]},
        headers=owner_headers,
    )
    assert r.status_code == 404, r.text
    assert r.json()["detail"] == "User is not a member of this league"


def test_transfer_to_self_is_bad_request(client, owner):
    _, owner_headers = owner
    league = _make_league(client, owner_headers)

    r = client.post(
        f"/api/leagues/{league['id']}/transfer",
        json={"new_owner_id": owner[0]},
        headers=owner_headers,
    )
    assert r.status_code == 400, r.text
    assert r.json()["detail"] == "You already own this league"


def test_transfer_missing_league_is_not_found(client, owner):
    _, owner_headers = owner

    r = client.post(
        "/api/leagues/99999999/transfer",
        json={"new_owner_id": owner[0]},
        headers=owner_headers,
    )
    assert r.status_code == 404, r.text
    assert r.json()["detail"] == "League not found"


def test_transfer_by_outsider_is_not_found(client, owner, outsider):
    _, owner_headers = owner
    _, outsider_headers = outsider
    league = _make_league(client, owner_headers)

    r = client.post(
        f"/api/leagues/{league['id']}/transfer",
        json={"new_owner_id": outsider[0]},
        headers=outsider_headers,
    )
    assert r.status_code == 404, r.text
    assert r.json()["detail"] == "League not found"


def test_transfer_requires_authentication(client, owner):
    _, owner_headers = owner
    league = _make_league(client, owner_headers)

    r = client.post(
        f"/api/leagues/{league['id']}/transfer", json={"new_owner_id": owner[0]}
    )
    assert r.status_code in (401, 403), r.text


def test_transfer_rejects_invalid_body(client, owner):
    _, owner_headers = owner
    league = _make_league(client, owner_headers)

    r = client.post(
        f"/api/leagues/{league['id']}/transfer",
        json={"new_owner_id": "not-a-number"},
        headers=owner_headers,
    )
    assert r.status_code == 422, r.text


def test_transfer_updates_league_list_for_new_owner(client, owner, member):
    _, owner_headers = owner
    _, member_headers = member
    league = _make_league(client, owner_headers)
    _add_member(client, league, member_headers)
    client.post(
        f"/api/leagues/{league['id']}/transfer",
        json={"new_owner_id": member[0]},
        headers=owner_headers,
    )

    r = client.get("/api/leagues", headers=member_headers)
    assert r.status_code == 200, r.text
    found = [lg for lg in r.json() if lg["id"] == league["id"]]
    assert len(found) == 1
    assert found[0]["owner_id"] == member[0]
