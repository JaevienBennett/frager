"""Milestone 23 backend tests: the rate limits cannot be walked around.

The limiter used to key on ``request.client.host``. Behind Render that field
is rewritten from the first ``X-Forwarded-For`` entry, which the caller
controls, so anybody could get a fresh bucket with every request by sending a
fresh header.
"""

import uuid

import pytest
from fastapi.testclient import TestClient
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from app import models
from app.database import SessionLocal
from app.main import app
from app.security import create_access_token, hash_password


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


def _proxied_client():
    """A test client that behaves like the production stack.

    In production uvicorn runs its proxy headers middleware, which rewrites
    ``request.client`` with the *first* X-Forwarded-For entry. The plain
    TestClient never does that, so a test that used it could not tell an
    implementation that keys on ``request.client.host`` apart from one that
    does not.
    """
    return TestClient(ProxyHeadersMiddleware(app, trusted_hosts="*"))


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
    """A fresh X-Forwarded-For per request must not buy a fresh bucket.

    The header is written the way the proxy chain writes it: the first entry
    is the address the caller claims, the last one is the address the proxy
    saw. The first entry is rotated here, so an implementation that keys on
    ``request.client.host`` would hand every request its own bucket and never
    hit the limit at all. The limit has to key on the last entry instead.
    """
    user_id, email, _ = _make_user()
    client = _proxied_client()

    codes = []
    for i in range(12):
        r = client.post(
            "/api/auth/login",
            json={"email": email, "password": "wrong-password"},
            headers={"X-Forwarded-For": f"10.0.0.{i}, 203.0.113.7"},
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
    client = _proxied_client()

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
    """A correct password never spends the account's budget.

    The address is rotated on every request, so the per-address limit cannot
    be the one that fires: only the account budget could, and it must not be
    charged for a password that was right.
    """
    _, email, _ = _make_user()
    client = _proxied_client()

    for i in range(12):
        r = client.post(
            "/api/auth/login",
            json={"email": email, "password": "pass123456"},
            headers={"X-Forwarded-For": f"198.51.100.{i}"},
        )
        assert r.status_code == 200, r.text


def test_a_correct_login_is_never_blocked_by_failed_attempts():
    """Nobody can lock a known account out of signing in.

    The account budget only counts wrong passwords, so a correct one is
    always let through - no matter how many guesses came before it.
    """
    _, email, _ = _make_user()
    client = _proxied_client()

    for i in range(12):
        r = client.post(
            "/api/auth/login",
            json={"email": email, "password": "wrong-password"},
            headers={"X-Forwarded-For": f"198.51.100.{i}"},
        )
        assert r.status_code in (401, 429), r.text

    r = client.post(
        "/api/auth/login",
        json={"email": email, "password": "pass123456"},
        headers={"X-Forwarded-For": "198.51.100.250"},
    )
    assert r.status_code == 200, r.text


def test_the_failure_budget_does_not_reveal_whether_an_account_exists():
    """A made-up address is spent exactly like a real one."""
    _, email, _ = _make_user()
    client = _proxied_client()

    def _fail(address, index):
        return client.post(
            "/api/auth/login",
            json={"email": address, "password": "wrong-password"},
            headers={"X-Forwarded-For": f"198.51.100.{index}"},
        )

    for i in range(11):
        _fail(email, i)
    for i in range(11):
        _fail("nobody-here@example.com", 100 + i)

    real = client.post(
        "/api/auth/login",
        json={"email": email, "password": "wrong-password"},
        headers={"X-Forwarded-For": "198.51.100.250"},
    )
    made_up = client.post(
        "/api/auth/login",
        json={"email": "nobody-here@example.com", "password": "wrong-password"},
        headers={"X-Forwarded-For": "198.51.100.251"},
    )
    assert real.status_code == made_up.status_code == 429, (real.text, made_up.text)


def test_one_address_cannot_hammer_many_accounts():
    """The address budget caps failures even when the target keeps changing.

    This is the credential-stuffing shape: one machine, many accounts. The
    account budget cannot see it (every account is fresh), so the address
    budget has to.
    """
    client = _proxied_client()

    codes = []
    for i in range(12):
        r = client.post(
            "/api/auth/login",
            json={"email": f"nobody-{i}@example.com", "password": "wrong-password"},
            headers={"X-Forwarded-For": f"10.0.0.{i}, 203.0.113.7"},
        )
        codes.append(r.status_code)

    assert codes[:10] == [401] * 10, codes
    assert codes[10] == 429, codes


def test_a_correct_login_is_never_blocked_by_failures_from_the_same_address():
    """The production shape: one address, eleven wrong passwords, then a right one.

    The proxy chain appends the address it saw to ``X-Forwarded-For``, so
    every request from one machine lands in the same address bucket whatever
    the caller writes in the header. A shared address (an office, a school, a
    phone carrier) must still be able to log in.
    """
    _, email, _ = _make_user()
    client = _proxied_client()

    for i in range(12):
        r = client.post(
            "/api/auth/login",
            json={"email": email, "password": "wrong-password"},
            headers={"X-Forwarded-For": f"10.0.0.{i}, 203.0.113.7"},
        )
        assert r.status_code in (401, 429), r.text

    r = client.post(
        "/api/auth/login",
        json={"email": email, "password": "pass123456"},
        headers={"X-Forwarded-For": "10.0.0.99, 203.0.113.7"},
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
