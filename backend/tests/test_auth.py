import re

from app.core.security import hash_token

from .conftest import register


async def test_health(client):
    r = await client.get("/health")
    assert r.status_code == 200 and r.json() == {"status": "ok"}
    assert "x-request-id" in r.headers


async def test_register_creates_user_workspace_and_session(client, app):
    user = await register(client)
    assert user["email"] == "a@example.com" and "password" not in str(user)
    db_user = await app.state.db.users.find_one({"email": "a@example.com"})
    assert db_user["password_hash"].startswith("$argon2id$")
    me = await client.get("/api/v1/auth/me")
    assert me.status_code == 200
    ws = (await client.get("/api/v1/workspaces")).json()
    assert len(ws) == 1 and ws[0]["role"] == "owner"


async def test_session_cookie_is_httponly_and_hashed(client, app):
    r = await client.post(
        "/api/v1/auth/register",
        json={"email": "b@example.com", "password": "correct-horse-9", "name": "B"},
    )
    set_cookie = [h for h in r.headers.get_list("set-cookie") if h.startswith("documind_session")]
    assert "HttpOnly" in set_cookie[0] and "SameSite=lax" in set_cookie[0]
    raw = client.cookies.get("documind_session")
    assert await app.state.db.sessions.find_one({"token_hash": hash_token(raw)})
    assert not await app.state.db.sessions.find_one({"token_hash": raw})


async def test_duplicate_email_and_weak_password(client):
    await register(client)
    dup = await client.post(
        "/api/v1/auth/register",
        json={"email": "A@example.com", "password": "correct-horse-9", "name": "X"},
    )
    assert dup.status_code == 409 and dup.json()["error"]["code"] == "email_taken"
    weak = await client.post(
        "/api/v1/auth/register", json={"email": "c@example.com", "password": "short", "name": "C"}
    )
    assert weak.status_code == 422 and weak.json()["error"]["code"] == "validation_error"


async def test_login_logout_and_wrong_password(client, new_client):
    await register(client)
    async with new_client() as c2:
        bad = await c2.post(
            "/api/v1/auth/login", json={"email": "a@example.com", "password": "nope-nope-1"}
        )
        assert bad.status_code == 401 and bad.json()["error"]["code"] == "invalid_credentials"
        unknown = await c2.post(
            "/api/v1/auth/login", json={"email": "z@example.com", "password": "nope-nope-1"}
        )
        assert unknown.json()["error"] == {
            **bad.json()["error"],
            "request_id": unknown.json()["error"]["request_id"],
        }
        ok = await c2.post(
            "/api/v1/auth/login", json={"email": "a@example.com", "password": "correct-horse-9"}
        )
        assert ok.status_code == 200
        c2.headers["X-CSRF-Token"] = c2.cookies.get("documind_csrf")
        assert (await c2.post("/api/v1/auth/logout")).status_code == 204
        assert (await c2.get("/api/v1/auth/me")).status_code == 401


async def test_protected_routes_require_auth(client):
    assert (await client.get("/api/v1/auth/me")).status_code == 401
    assert (await client.get("/api/v1/workspaces")).status_code == 401


async def test_csrf_required_for_unsafe_authenticated_requests(client):
    await register(client)
    del client.headers["X-CSRF-Token"]
    r = await client.post("/api/v1/workspaces", json={"name": "W"})
    assert r.status_code == 403
    client.headers["X-CSRF-Token"] = "wrong"
    assert (await client.post("/api/v1/workspaces", json={"name": "W"})).status_code == 403


async def test_foreign_origin_blocked(client):
    await register(client)
    r = await client.post(
        "/api/v1/workspaces", json={"name": "W"}, headers={"Origin": "https://evil.example"}
    )
    assert r.status_code == 403


async def test_login_rate_limited(client):
    for _ in range(10):
        await client.post(
            "/api/v1/auth/login", json={"email": "x@example.com", "password": "bad-pass-1"}
        )
    r = await client.post(
        "/api/v1/auth/login", json={"email": "x@example.com", "password": "bad-pass-1"}
    )
    assert r.status_code == 429 and "retry-after" in r.headers


async def test_password_reset_flow(client, new_client, caplog):
    await register(client)
    caplog.set_level("INFO", logger="documind.email")
    async with new_client() as c2:
        r = await c2.post("/api/v1/auth/forgot-password", json={"email": "a@example.com"})
        assert r.status_code == 202
        unknown = await c2.post(
            "/api/v1/auth/forgot-password", json={"email": "nobody@example.com"}
        )
        assert unknown.status_code == 202
        token = re.search(r"reset-password\?token=(\S+)", caplog.text).group(1)
        done = await c2.post(
            "/api/v1/auth/reset-password", json={"token": token, "password": "new-password-77"}
        )
        assert done.status_code == 204
        reuse = await c2.post(
            "/api/v1/auth/reset-password", json={"token": token, "password": "another-pass-88"}
        )
        assert reuse.status_code == 400
        # old sessions are revoked, new password works
        assert (await client.get("/api/v1/auth/me")).status_code == 401
        ok = await c2.post(
            "/api/v1/auth/login", json={"email": "a@example.com", "password": "new-password-77"}
        )
        assert ok.status_code == 200


async def test_email_verification(client, caplog, app):
    caplog.set_level("INFO", logger="documind.email")
    await register(client)
    token = re.search(r"verify-email\?token=(\S+)", caplog.text).group(1)
    assert (
        await client.post("/api/v1/auth/verify-email", json={"token": token})
    ).status_code == 204
    assert (await client.get("/api/v1/auth/me")).json()["email_verified"] is True


async def test_change_password_revokes_other_sessions(client, new_client):
    await register(client)
    async with new_client() as other:
        await other.post(
            "/api/v1/auth/login", json={"email": "a@example.com", "password": "correct-horse-9"}
        )
        assert (await other.get("/api/v1/auth/me")).status_code == 200
        r = await client.post(
            "/api/v1/users/me/password",
            json={"current_password": "correct-horse-9", "new_password": "brand-new-pass-1"},
        )
        assert r.status_code == 204
        assert (await other.get("/api/v1/auth/me")).status_code == 401
        assert (await client.get("/api/v1/auth/me")).status_code == 200


async def test_client_config_requires_auth_and_exposes_no_secrets(client):
    assert (await client.get("/api/v1/system/config")).status_code == 401
    await register(client)
    body = (await client.get("/api/v1/system/config")).json()
    assert set(body) == {
        "max_upload_mb", "max_files_per_upload", "allowed_extensions", "external_ai_processing",
    }  # fmt: skip
