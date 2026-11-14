import asyncio
import struct

import pytest
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from app.core.config import get_settings
from app.core.errors import AppError
from app.core.redis_limiter import RedisLimiter
from app.middleware.security import BodyLimitMiddleware, SecurityHeadersMiddleware
from app.modules.documents.malware import ClamAVScanner

from .conftest import enable_ai, first_workspace, register
from .test_upload import TXT, files

# ---------- headers and body limits ----------


async def test_security_headers_on_api_and_errors(client):
    for path in ("/health", "/api/v1/auth/me", "/nope"):
        r = await client.get(path)
        assert r.headers["x-content-type-options"] == "nosniff"
        assert (
            r.headers["x-frame-options"] == "DENY"
            and "camera=()" in r.headers["permissions-policy"]
        )
        assert r.headers["referrer-policy"] == "strict-origin-when-cross-origin"
        assert "strict-transport-security" not in r.headers  # only when COOKIE_SECURE (HTTPS)


def test_hsts_only_when_enabled():
    async def ok(_):
        return PlainTextResponse("ok")

    for hsts, present in ((True, True), (False, False)):
        app = Starlette(routes=[Route("/", ok)])
        app.add_middleware(SecurityHeadersMiddleware, hsts=hsts)
        r = TestClient(app).get("/")
        assert ("strict-transport-security" in r.headers) is present


async def test_oversized_json_is_rejected_but_uploads_are_not_affected(client, app):
    await register(client)
    big = {"name": "x" * (2 * 1024 * 1024 + 10)}
    r = await client.post("/api/v1/workspaces", json=big)
    assert r.status_code == 413 and r.json()["error"]["code"] == "payload_too_large"
    ws = await first_workspace(client)
    await enable_ai(client, ws["id"])
    up = await client.post(
        f"/api/v1/workspaces/{ws['id']}/documents/upload", files=files(("a.txt", TXT))
    )
    assert up.status_code == 200 and up.json()["results"][0]["outcome"] == "created"


def test_body_limit_middleware_unit():
    async def echo(request):
        return PlainTextResponse(str(len(await request.body())))

    app = Starlette(routes=[Route("/", echo, methods=["POST"])])
    app.add_middleware(BodyLimitMiddleware, limit=100)
    c = TestClient(app)
    assert c.post("/", content=b"x" * 50).text == "50"
    assert c.post("/", content=b"x" * 500).status_code == 413
    assert c.post("/", files={"f": ("a.txt", b"x" * 500)}).status_code == 200  # multipart exempt


# ---------- Redis rate limiter ----------


class FakeRedis:
    """Implements the three commands the limiter uses, with expiry on a controllable clock."""

    def __init__(self):
        self.now = 0.0
        self.data: dict[str, tuple[int, float | None]] = {}

    def _live(self, k):
        v = self.data.get(k)
        if v and v[1] is not None and v[1] <= self.now:
            del self.data[k]
            return None
        return v

    async def incr(self, k):
        v = self._live(k)
        n = (v[0] if v else 0) + 1
        self.data[k] = (n, v[1] if v else None)
        return n

    async def expire(self, k, s):
        self.data[k] = (self.data[k][0], self.now + s)

    async def ttl(self, k):
        v = self._live(k)
        return -2 if not v else (-1 if v[1] is None else int(v[1] - self.now))


async def test_redis_limiter_fixed_window():
    r = FakeRedis()
    lim = RedisLimiter(r)
    for _ in range(3):
        await lim.check("login:1.2.3.4", 3, 60)
    with pytest.raises(AppError) as e:
        await lim.check("login:1.2.3.4", 3, 60)
    assert e.value.status_code == 429 and 1 <= e.value.details["retry_after"] <= 60
    await lim.check("login:9.9.9.9", 3, 60)  # keys are independent
    r.now += 61  # window passes
    await lim.check("login:1.2.3.4", 3, 60)


async def test_rate_limit_dependency_uses_shared_limiter_when_configured(client, app):
    app.state.redis_limiter = RedisLimiter(FakeRedis())
    try:
        for _ in range(10):
            await client.post(
                "/api/v1/auth/login", json={"email": "x@example.com", "password": "bad-pass-1"}
            )
        r = await client.post(
            "/api/v1/auth/login", json={"email": "x@example.com", "password": "bad-pass-1"}
        )
        assert r.status_code == 429 and "retry-after" in r.headers
    finally:
        app.state.redis_limiter = None


# ---------- ClamAV (clamd INSTREAM protocol) ----------


class FakeClamd:
    """A tiny clamd: parses zINSTREAM framing and answers by content."""

    def __init__(self, reply=None):
        self.reply, self.received, self.server = reply, b"", None

    async def handle(self, reader, writer):
        cmd = await reader.readuntil(b"\0")
        assert cmd == b"zINSTREAM\0"
        data = b""
        while True:
            (n,) = struct.unpack("!I", await reader.readexactly(4))
            if n == 0:
                break
            data += await reader.readexactly(n)
        self.received = data
        reply = self.reply or (
            "stream: Eicar-Test-Signature FOUND" if b"EICAR" in data else "stream: OK"
        )
        writer.write(reply.encode() + b"\0")
        await writer.drain()
        writer.close()

    async def __aenter__(self):
        self.server = await asyncio.start_server(self.handle, "127.0.0.1", 0)
        self.port = self.server.sockets[0].getsockname()[1]
        return self

    async def __aexit__(self, *a):
        self.server.close()
        await self.server.wait_closed()


async def test_clamav_scanner_protocol_clean_infected_and_errors(tmp_path):
    clean = tmp_path / "c.txt"
    clean.write_bytes(b"hello" * 50_000)  # > one 64 KiB frame
    bad = tmp_path / "b.txt"
    bad.write_bytes(b"X5O!P%@AP EICAR-TEST")
    async with FakeClamd() as srv:
        s = ClamAVScanner("127.0.0.1", srv.port)
        await s.scan_file(str(clean))
        assert srv.received == b"hello" * 50_000  # framing reassembled byte-for-byte
        with pytest.raises(AppError) as e:
            await s.scan_file(str(bad))
        assert e.value.status_code == 422 and e.value.code == "malware_detected"
    async with FakeClamd(reply="stream: INSTREAM size limit exceeded. ERROR") as srv:
        with pytest.raises(AppError) as e:
            await ClamAVScanner("127.0.0.1", srv.port).scan_file(str(clean))
        assert e.value.status_code == 503  # unknown reply -> fail closed
    with pytest.raises(AppError) as e:  # nothing listening
        await ClamAVScanner("127.0.0.1", 1, timeout_s=2).scan_file(str(clean))
    assert e.value.code == "malware_scan_unavailable"


async def test_upload_rejects_infected_files_and_fails_closed(client, app, monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "embedding_provider", "hashing")
    monkeypatch.setattr(s, "llm_provider", "fake")
    monkeypatch.setattr(s, "malware_scan", "clamav")
    await register(client)
    ws = await first_workspace(client)
    base = f"/api/v1/workspaces/{ws['id']}"
    async with FakeClamd() as srv:
        monkeypatch.setattr(s, "clamav_port", srv.port)
        r = await client.post(
            f"{base}/documents/upload",
            files=files(("evil.txt", b"X5O!P%@AP EICAR test string"), ("fine.txt", TXT)),
        )
        out = {x["filename"]: x for x in r.json()["results"]}
        assert (
            out["evil.txt"]["outcome"] == "rejected"
            and out["evil.txt"]["error_code"] == "malware_detected"
        )
        assert out["fine.txt"]["outcome"] == "created"
    monkeypatch.setattr(s, "clamav_port", 1)  # scanner down
    r = await client.post(f"{base}/documents/upload", files=files(("other.txt", TXT + b"more")))
    assert r.json()["results"][0]["error_code"] == "malware_scan_unavailable"
    assert await app.state.db.documents.count_documents({}) == 1  # only the clean file exists


# ---------- auditing and readiness ----------


async def test_failed_logins_are_audited_without_the_email(client, app):
    await client.post(
        "/api/v1/auth/login", json={"email": "victim@example.com", "password": "bad-pass-1"}
    )
    log = await app.state.db.audit_logs.find_one({"action": "auth.login_failed"})
    assert log and log["ip"] and len(log["target"]["email_hash"]) == 12
    assert "victim" not in str(log)


async def test_readiness_reports_search_and_redis_status(client):
    r = await client.get("/health/ready")
    assert (
        r.status_code == 200
        and r.json()["search"]["backend"] == "local"
        and r.json()["redis"] is None
    )


def test_secrets_never_appear_in_settings_repr():
    text = repr(get_settings())
    assert "test-secret-key" not in text and "SecretStr" in text
