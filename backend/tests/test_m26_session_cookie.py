"""Milestone 26 backend tests: the refresh token lives in an httpOnly cookie.

Until M26 the refresh token was handed to the browser in a JSON body and kept
in ``localStorage``, so any script that got into the page could read it and
mint sessions forever. The cookie is ``HttpOnly`` (no script can read it) and
the browser throws it away when the session ends.

A cookie is sent by the browser to every request the page makes, including
one another site made it make, so the cookie has to be defended: the origin
check refuses a request from a page we do not serve, and the CSRF token has
to come back in a header.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import Request, Response
from fastapi.testclient import TestClient

from app import routes_auth
from app.config import REFRESH_COOKIE_ONLY
from app.database import SessionLocal
from app.main import app
from app.models import RefreshToken, User
from app.security import hash_password, hash_refresh_token
from app.session_cookie import (
    COOKIE_PATH,
    CSRF_HEADER,
    REFRESH_COOKIE,
    csrf_token,
    set_refresh_cookie,
)

TEST_HOST = "testserver.local"
OTHER_ORIGIN = "https://evil.example"
PASSWORD = "pass123456"


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


@pytest.fixture(scope="module")
def db_session():
    session = SessionLocal()
    created: list[int] = []
    try:
        yield session, created
    finally:
        for user_id in created:
            session.query(RefreshToken).filter(
                RefreshToken.user_id == user_id
            ).delete()
            session.query(User).filter(User.id == user_id).delete()
        session.commit()
        session.close()


def _make_user(session, created, password=PASSWORD) -> User:
    tag = uuid.uuid4().hex[:10]
    user = User(
        email=f"m26-{tag}@example.com",
        nickname=f"m26-{tag}",
        password_hash=hash_password(password),
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    created.append(user.id)
    return user


def _signup(client, db_session, password=PASSWORD):
    session, created = db_session
    tag = uuid.uuid4().hex[:10]
    email = f"m26-{tag}@example.com"
    nickname = f"m26-{tag}"
    r = client.post(
        "/api/auth/signup",
        json={"email": email, "nickname": nickname, "password": password},
    )
    assert r.status_code == 201, r.text
    user = session.query(User).filter(User.email == email).one()
    created.append(user.id)
    return user, r


def _cookie(client) -> str | None:
    return client.cookies.get(REFRESH_COOKIE, domain=TEST_HOST, path=COOKIE_PATH)


def _set_cookie(client, value: str) -> None:
    client.cookies.clear()
    client.cookies.set(
        REFRESH_COOKIE, value, domain=TEST_HOST, path=COOKIE_PATH
    )


def _csrf(user) -> dict:
    return {CSRF_HEADER: csrf_token(user.id, user.token_version)}


def _access_token(client) -> str:
    """The access token of the session the client currently holds."""
    r = client.post("/api/auth/refresh")
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


# --------------------------------------------------------------------------
# the cookie itself
# --------------------------------------------------------------------------


def test_signup_hands_the_refresh_token_to_the_browser_as_an_http_only_cookie(
    client, db_session
):
    session, created = db_session
    user, r = _signup(client, db_session)

    header = r.headers["set-cookie"]
    assert REFRESH_COOKIE in header
    # JavaScript cannot read it
    assert "HttpOnly" in header
    # and it is only sent to the endpoints that need it
    assert f"Path={COOKIE_PATH}" in header
    # plain http (the test client) cannot carry SameSite=None
    assert "SameSite=lax" in header

    raw = _cookie(client)
    assert raw
    # only the hash is stored
    row = (
        session.query(RefreshToken)
        .filter(RefreshToken.token_hash == hash_refresh_token(raw))
        .one()
    )
    assert row.user_id == user.id


def test_over_https_the_cookie_is_same_site_none_and_secure():
    """The app and the API are on different sites, so the cookie needs both."""
    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "POST",
        "scheme": "https",
        "path": "/api/auth/login",
        "raw_path": b"/api/auth/login",
        "query_string": b"",
        "headers": [],
        "client": ("203.0.113.9", 1234),
        "server": ("frager-backend.onrender.com", 443),
        "root_path": "",
    }
    request = Request(scope)
    response = Response()
    set_refresh_cookie(response, "a-token", request)

    header = response.headers["set-cookie"]
    assert "HttpOnly" in header
    assert "Secure" in header
    assert "SameSite=none" in header
    assert f"Path={COOKIE_PATH}" in header


def test_the_session_responses_are_never_cached(client, db_session):
    """A proxy must not keep a response that carries a session cookie."""
    _, r = _signup(client, db_session)
    assert r.headers["cache-control"] == "no-store"


def test_the_refresh_token_leaves_the_response_body_once_the_cookie_owns_it(
    client, db_session
):
    """The cookie owns the refresh token now, so the body does not carry it."""
    assert REFRESH_COOKIE_ONLY, "the rollout is not finished yet"
    _, r = _signup(client, db_session)
    assert r.json()["refresh_token"] is None


def test_the_body_token_is_still_handed_out_while_the_rollout_is_running(
    client, db_session, monkeypatch
):
    """Step 1 of the rollout: the body token and the cookie are the same token,
    so a client that only knows one of them still works."""
    monkeypatch.setattr(routes_auth, "REFRESH_COOKIE_ONLY", False)
    _, r = _signup(client, db_session)
    body = r.json()
    assert body["refresh_token"] == _cookie(client)


# --------------------------------------------------------------------------
# refreshing from the cookie
# --------------------------------------------------------------------------


def test_a_refresh_from_the_cookie_alone_works(client, db_session):
    user, _ = _signup(client, db_session)
    first = _cookie(client)

    r = client.post("/api/auth/refresh")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["access_token"]

    # the cookie was rotated
    second = _cookie(client)
    assert second and second != first

    # the new access token works
    me = client.get(
        "/api/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"}
    )
    assert me.status_code == 200
    assert me.json()["id"] == user.id


def test_a_refresh_without_a_cookie_and_without_a_body_is_rejected(client):
    r = client.post("/api/auth/refresh")
    assert r.status_code == 401, r.text
    assert r.json()["detail"] == "Invalid refresh token"


def _raw_refresh_token(db_session) -> str:
    """A refresh token that only exists in the database."""
    session, created = db_session
    user = _make_user(session, created)
    raw = f"m26-raw-{uuid.uuid4().hex}"
    session.add(
        RefreshToken(
            user_id=user.id,
            token_hash=hash_refresh_token(raw),
            expires_at=datetime.now(timezone.utc) + timedelta(days=30),
        )
    )
    session.commit()
    return raw


def test_the_body_token_is_refused_once_the_rollout_is_over(
    client, db_session
):
    """The old clients send the token in the body. That door is closed now."""
    raw = _raw_refresh_token(db_session)
    r = client.post("/api/auth/refresh", json={"refresh_token": raw})
    assert r.status_code == 401, r.text
    assert r.json()["detail"] == "Invalid refresh token"


def test_the_body_token_is_accepted_while_the_rollout_is_running(
    client, db_session, monkeypatch
):
    """During the rollout the body token still opens the door."""
    monkeypatch.setattr(routes_auth, "REFRESH_COOKIE_ONLY", False)
    raw = _raw_refresh_token(db_session)
    r = client.post("/api/auth/refresh", json={"refresh_token": raw})
    assert r.status_code == 200, r.text


# --------------------------------------------------------------------------
# cross-site requests
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path,payload",
    [
        (
            "/api/auth/signup",
            {
                "email": "x@example.com",
                "nickname": "xx",
                "password": "pass123456",
            },
        ),
        (
            "/api/auth/login",
            {"email": "x@example.com", "password": "pass123456"},
        ),
        ("/api/auth/refresh", {}),
        ("/api/auth/logout", {}),
    ],
)
def test_a_request_from_another_site_is_refused(client, path, payload):
    r = client.post(path, json=payload, headers={"Origin": OTHER_ORIGIN})
    assert r.status_code == 403, r.text
    assert r.json()["detail"] == "Origin not allowed"


def test_a_request_without_an_origin_is_allowed(client, db_session):
    """curl and the tests do not send one; they are not a browser form."""
    _, r = _signup(client, db_session)
    assert r.status_code == 201, r.text


# --------------------------------------------------------------------------
# the CSRF token
# --------------------------------------------------------------------------


def test_logout_without_the_csrf_token_is_refused(client, db_session):
    user, _ = _signup(client, db_session)
    raw = _cookie(client)

    r = client.post("/api/auth/logout")
    assert r.status_code == 403, r.text
    assert r.json()["detail"] == "CSRF token missing or invalid"

    # the session is untouched
    session, _ = db_session
    row = (
        session.query(RefreshToken)
        .filter(RefreshToken.token_hash == hash_refresh_token(raw))
        .one()
    )
    assert row.revoked_at is None


def test_logout_with_the_csrf_token_ends_the_session_and_clears_the_cookie(
    client, db_session
):
    user, _ = _signup(client, db_session)
    raw = _cookie(client)

    r = client.post("/api/auth/logout", headers=_csrf(user))
    assert r.status_code == 200, r.text
    assert r.json() == {"ok": True}
    assert _cookie(client) is None

    session, _ = db_session
    row = (
        session.query(RefreshToken)
        .filter(RefreshToken.token_hash == hash_refresh_token(raw))
        .one()
    )
    assert row.revoked_at is not None
    assert row.revoked_reason == "logout"


def test_logout_all_without_the_csrf_token_is_refused(client, db_session):
    user, _ = _signup(client, db_session)
    access = _access_token(client)

    r = client.post(
        "/api/auth/logout-all",
        headers={"Authorization": f"Bearer {access}"},
    )
    assert r.status_code == 403, r.text

    # the session survives
    still = client.get(
        "/api/auth/me", headers={"Authorization": f"Bearer {access}"}
    )
    assert still.status_code == 200


def test_logout_all_with_the_csrf_token_ends_every_session(client, db_session):
    user, _ = _signup(client, db_session)
    access = _access_token(client)

    r = client.post(
        "/api/auth/logout-all",
        headers={"Authorization": f"Bearer {access}", **_csrf(user)},
    )
    assert r.status_code == 200, r.text
    assert _cookie(client) is None
    assert (
        client.get("/api/auth/me", headers={"Authorization": f"Bearer {access}"}).status_code
        == 401
    )


def test_the_csrf_token_is_the_same_in_every_tab(client, db_session):
    """It is derived from the account, so a second tab sends the same value."""
    _, signup_response = _signup(client, db_session)
    first = signup_response.json()["csrf_token"]
    assert first

    r = client.post("/api/auth/refresh")
    assert r.status_code == 200, r.text
    assert r.json()["csrf_token"] == first


def test_the_csrf_token_of_another_account_is_refused(client, db_session):
    session, created = db_session
    victim, _ = _signup(client, db_session)
    attacker = _make_user(session, created)

    r = client.post("/api/auth/logout", headers=_csrf(attacker))
    assert r.status_code == 403, r.text
    assert r.json()["detail"] == "CSRF token missing or invalid"


def test_the_csrf_token_changes_when_the_password_changes(client, db_session):
    user, signup_response = _signup(client, db_session)
    before = signup_response.json()["csrf_token"]
    access = _access_token(client)

    r = client.post(
        "/api/auth/change-password",
        json={"current_password": PASSWORD, "new_password": "newpassword1"},
        headers={"Authorization": f"Bearer {access}"},
    )
    assert r.status_code == 200, r.text
    after = r.json()["csrf_token"]
    assert after and after != before
