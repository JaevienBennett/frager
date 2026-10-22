"""Milestone 21 backend tests: league ownership transfer.

The owner of a league could not hand it over, so an owner who wanted out was
stuck: leaving is refused for owners and the league could only be deleted.
"""

import threading
import time
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


# --------------------------------------------------------------------------
# races and broadcasts
# --------------------------------------------------------------------------


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
        return result["found"]
    if "error" in result:
        raise AssertionError(f"websocket receive failed: {result['error']!r}")
    raise AssertionError(
        f"timed out after {timeout}s waiting for {wanted_type!r}; got {messages!r}"
    )


def test_two_transfers_at_the_same_time_leave_the_league_owned_by_a_member(
    client, owner, member, outsider
):
    """The league must never end up owned by somebody who is not a member.

    Both transfers are sent at the same moment. One of them wins, the other is
    told to reload, and whoever owns the league afterwards is still in it.
    """
    _, owner_headers = owner
    member_id, member_headers = member
    outsider_id, outsider_headers = outsider
    league = _make_league(client, owner_headers)
    _add_member(client, league, member_headers)
    _add_member(client, league, outsider_headers)

    barrier = threading.Barrier(2)
    results = {}

    def _transfer(key, target_id):
        barrier.wait()
        r = client.post(
            f"/api/leagues/{league['id']}/transfer",
            json={"new_owner_id": target_id},
            headers=owner_headers,
        )
        results[key] = r.status_code

    threads = [
        threading.Thread(target=_transfer, args=("a", member_id)),
        threading.Thread(target=_transfer, args=("b", outsider_id)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(15)

    assert len(results) == 2, results
    codes = sorted(results.values())
    assert codes[0] == 200, results
    assert codes[1] in (403, 409), results

    db = SessionLocal()
    try:
        new_owner = db.get(models.League, league["id"]).owner_id
        assert new_owner in (member_id, outsider_id)
        assert (
            db.query(models.Membership)
            .filter(
                models.Membership.league_id == league["id"],
                models.Membership.user_id == new_owner,
            )
            .count()
            == 1
        )
    finally:
        db.close()


def test_a_leave_and_a_transfer_at_the_same_time_keep_the_owner_a_member(
    client, owner, member
):
    """A member who leaves while the league changes hands is not left owning it.

    The loser of the race is either told to reload or is still a member, and
    the league is never owned by somebody who just left it.
    """
    owner_id, owner_headers = owner
    member_id, member_headers = member
    league = _make_league(client, owner_headers)
    _add_member(client, league, member_headers)

    barrier = threading.Barrier(2)
    results = {}

    def _transfer():
        barrier.wait()
        r = client.post(
            f"/api/leagues/{league['id']}/transfer",
            json={"new_owner_id": member_id},
            headers=owner_headers,
        )
        results["transfer"] = r.status_code

    def _leave():
        barrier.wait()
        r = client.post(f"/api/leagues/{league['id']}/leave", headers=member_headers)
        results["leave"] = r.status_code

    threads = [
        threading.Thread(target=_transfer),
        threading.Thread(target=_leave),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(15)

    assert set(results) == {"transfer", "leave"}, results

    db = SessionLocal()
    try:
        new_owner = db.get(models.League, league["id"]).owner_id
        if new_owner == member_id:
            # the transfer won: the member is still a member
            assert (
                db.query(models.Membership)
                .filter(
                    models.Membership.league_id == league["id"],
                    models.Membership.user_id == member_id,
                )
                .count()
                == 1
            )
        else:
            # the leave won: the league is still owned by somebody in it
            assert new_owner == owner_id
    finally:
        db.close()


def test_transfer_broadcasts_the_new_owner(client, owner, member):
    """Everybody in the league has to hear that the owner changed."""
    owner_id, owner_headers = owner
    member_id, member_headers = member
    league = _make_league(client, owner_headers)
    _add_member(client, league, member_headers)
    token = owner_headers["Authorization"].split(" ", 1)[1]

    with TestClient(app) as ws_client:
        with ws_client.websocket_connect(
            f"/ws/leagues/{league['id']}?token={token}"
        ) as session:
            r = ws_client.post(
                f"/api/leagues/{league['id']}/transfer",
                json={"new_owner_id": member_id},
                headers=owner_headers,
            )
            assert r.status_code == 200, r.text

            message = _receive_until(session, "league_updated")
            assert message["league_id"] == league["id"]
            assert message["owner_id"] == member_id


def test_a_leave_waits_for_a_transfer_that_is_in_flight(client, owner, member):
    """The leave endpoint has to wait for the league row.

    A transfer that is on its way locks the league row, so a leave that
    arrives at the same moment cannot slip in between the check "is the
    target still a member?" and the change of owner. Once the transfer has
    committed, the leave sees the new owner and refuses to go through.
    """
    owner_id, owner_headers = owner
    member_id, member_headers = member
    league = _make_league(client, owner_headers)
    _add_member(client, league, member_headers)

    locker = SessionLocal()
    try:
        # the transfer is in flight and holds the league row
        locker.query(models.League).filter(
            models.League.id == league["id"]
        ).with_for_update().first()

        result = {}

        def _leave():
            r = client.post(
                f"/api/leagues/{league['id']}/leave", headers=member_headers
            )
            result["status"] = r.status_code

        thread = threading.Thread(target=_leave)
        thread.start()
        time.sleep(0.5)
        assert thread.is_alive(), "the leave did not wait for the lock"

        # the transfer commits: the member is the new owner now
        locker.query(models.League).filter(
            models.League.id == league["id"]
        ).update({models.League.owner_id: member_id})
        locker.commit()

        thread.join(15)
        assert not thread.is_alive()
        assert result["status"] == 409, result
        assert (
            client.get(
                f"/api/leagues/{league['id']}", headers=owner_headers
            ).json()["owner_id"]
            == member_id
        )
    finally:
        locker.rollback()
        locker.close()
