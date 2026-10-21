from fastapi.testclient import TestClient

from app.main import app


def test_health():
    client = TestClient(app)
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_signup_login_me_flow():
    client = TestClient(app)
    import uuid
    email = f"s{uuid.uuid4().hex[:8]}@example.com"
    nick = f"n{uuid.uuid4().hex[:8]}"
    r = client.post("/api/auth/signup", json={"email": email, "nickname": nick, "password": "pass123456"})
    assert r.status_code in (200, 201)
    token = r.json()["access_token"]
    r2 = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r2.status_code == 200
    assert r2.json()["nickname"] == nick
    assert "email" in r2.json()
    # login
    r3 = client.post("/api/auth/login", json={"email": email, "password": "pass123456"})
    assert r3.status_code == 200
    assert "access_token" in r3.json()
