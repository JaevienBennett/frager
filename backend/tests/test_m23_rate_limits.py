"""Milestone 23 backend tests: the rate limits cannot be walked around.

The limiter used to key on ``request.client.host``. Behind Render that field
is rewritten from the first ``X-Forwarded-For`` entry, which the caller
controls, so anybody could get a fresh bucket with every request by sending a
fresh header.
"""

import uuid

import pytest
from fastapi.testclient import TestClient

from app import models
from app.database import SessionLocal
from app.main import app
from app.security import create_access_token, hash_password


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


def _make_user(email=None, nickname=None):
    tag = uuid.uuid4().hex[:10]
    db = SessionLocal()
    try:
        user = models.User(
            email=email or f"m23-{tag}@example.com",
            nickname=nickname or f"m23-{tag}",
            password_hash=hash_password("pass123456"),
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user.id, user.email, {
            "Authorization": f"Bearer {create_access_token(str(user.id))}"
        }
    finally:
        db.close()


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


# --------------------------------------------------------------------------
# client_ip
# --------------------------------------------------------------------------


def test_client_ip_prefers_the_cloudflare_header():
    from app.rate_limit import client_ip
    from starlette.requests import Request

    scope = {
        "type": "http",
        "headers": [
            (b"cf-connecting-ip", b"203.0.113.9"),
            (b"x-forwarded-for", b"1.2.3.4, 203.0.113.9, 5.6.7.8"),
        ],
        "client": ("1.2.3.4", 1234),
    }
    assert client_ip(Request(scope)) == "203.0.113.9"


def test_client_ip_uses_the_last_forwarded_entry():
    from app.rate_limit import client_ip
    from starlette.requests import Request

    scope = {
        "type": "http",
        "headers": [(b"x-forwarded-for", b"1.2.3.4, 5.6.7.8")],
        "client": ("1.2.3.4", 1234),
    }
    assert client_ip(Request(scope)) == "5.6.7.8"


def test_client_ip_falls_back_to_the_socket_address():
    from app.rate_limit import client_ip
    from starlette.requests import Request

    scope = {"type": "http", "headers": [], "client": ("10.0.0.7", 1234)}
    assert client_ip(Request(scope)) == "10.0.0.7"


# --------------------------------------------------------------------------
# login: the account is what counts
# --------------------------------------------------------------------------


def test_login_limit_holds_when_the_forwarded_header_is_rotated():
    """A fresh X-Forwarded-For per request must not buy a fresh bucket."""
    user_id, email, _ = _make_user()
    client = TestClient(app)

    codes = []
    for i in range(12):
        r = client.post(
            "/api/auth/login",
            json={"email": email, "password": "wrong-password"},
            headers={"X-Forwarded-For": f"10.0.0.{i}, 10.1.1.{i}"},
        )
        codes.append(r.status_code)

    assert 429 in codes, f"the limit never triggered: {codes}"
    # the last request has to be the one that is refused
    assert codes[-1] == 429, codes


def test_login_limit_is_per_account():
    """Two accounts from one address each get their own budget.

    The address is rotated on every request so that the per-address limit
    cannot be the one that fires: the account limit must be the one.
    """
    _, email_a, _ = _make_user()
    _, email_b, _ = _make_user()
    client = TestClient(app)

    def _login(email, index):
        return client.post(
            "/api/auth/login",
            json={"email": email, "password": "wrong-password"},
            headers={"X-Forwarded-For": f"10.0.0.{index}"},
        )

    for i in range(10):
        r = _login(email_a, i)
        assert r.status_code == 401, r.text

    # account A is now used up ...
    r = _login(email_a, 10)
    assert r.status_code == 429, r.text

    # ... but account B is untouched
    r = _login(email_b, 11)
    assert r.status_code == 401, r.text


def test_login_limit_does_not_count_a_correct_password():
    _, email, _ = _make_user()
    client = TestClient(app)

    for _ in range(3):
        r = client.post(
            "/api/auth/login", json={"email": email, "password": "pass123456"}
        )
        assert r.status_code == 200, r.text


# --------------------------------------------------------------------------
# write endpoints: the user is what counts
# --------------------------------------------------------------------------


def test_league_creation_limit_is_per_user():
    _, _, headers = _make_user()
    client = TestClient(app)

    codes = []
    for _ in range(11):
        r = client.post(
            "/api/leagues", json={"name": f"League {uuid.uuid4().hex[:6]}"}, headers=headers
        )
        codes.append(r.status_code)

    assert codes[-1] == 429, codes
    assert codes.count(201) == 10, codes


def test_league_creation_limit_is_not_shared_between_users():
    _, _, headers_a = _make_user()
    _, _, headers_b = _make_user()
    client = TestClient(app)

    for _ in range(10):
        r = client.post(
            "/api/leagues", json={"name": f"League {uuid.uuid4().hex[:6]}"}, headers=headers_a
        )
        assert r.status_code == 201, r.text

    r = client.post(
        "/api/leagues", json={"name": f"League {uuid.uuid4().hex[:6]}"}, headers=headers_b
    )
    assert r.status_code == 201, r.text


def test_a_forged_forwarded_header_does_not_buy_a_new_bucket():
    """The user key ignores the headers completely."""
    _, _, headers = _make_user()
    client = TestClient(app)

    codes = []
    for i in range(11):
        r = client.post(
            "/api/leagues",
            json={"name": f"League {uuid.uuid4().hex[:6]}"},
            headers={**headers, "X-Forwarded-For": f"10.0.0.{i}"},
        )
        codes.append(r.status_code)

    assert codes[-1] == 429, codes


def test_pick_limit_is_per_user():
    owner_id, _, owner_headers = _make_user()
    client = TestClient(app)

    league = client.post("/api/leagues", json={"name": "Pick League"}, headers=owner_headers)
    assert league.status_code == 201, league.text
    league_id = league.json()["id"]
    prediction = client.post(
        f"/api/leagues/{league_id}/predictions",
        json={"question": "How many picks?"},
        headers=owner_headers,
    )
    assert prediction.status_code == 201, prediction.text
    prediction_id = prediction.json()["id"]

    codes = []
    for _ in range(61):
        r = client.post(
            f"/api/predictions/{prediction_id}/pick",
            json={"side": "yes", "stake": 1},
            headers=owner_headers,
        )
        codes.append(r.status_code)

    assert codes[-1] == 429, codes
