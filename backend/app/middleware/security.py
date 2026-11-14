from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

MAX_JSON_BYTES = 2 * 1024 * 1024  # non-upload request bodies


class SecurityHeadersMiddleware:
    """Adds baseline security headers to every response (pure ASGI; safe for streaming)."""

    def __init__(self, app: ASGIApp, hsts: bool) -> None:
        self.app = app
        self.hsts = hsts

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_wrapped(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = message.setdefault("headers", [])
                existing = {k.lower() for k, _ in headers}
                add = {
                    b"x-content-type-options": b"nosniff",
                    b"x-frame-options": b"DENY",
                    b"referrer-policy": b"strict-origin-when-cross-origin",
                    b"permissions-policy": b"camera=(), microphone=(), geolocation=()",
                    b"cross-origin-opener-policy": b"same-origin",
                }
                if self.hsts:
                    add[b"strict-transport-security"] = b"max-age=31536000; includeSubDomains"
                for k, v in add.items():
                    if k not in existing:
                        headers.append((k, v))
            await send(message)

        await self.app(scope, receive, send_wrapped)


class BodyLimitMiddleware:
    """Rejects oversized request bodies early based on Content-Length. Multipart uploads are
    exempt here: the upload endpoints enforce their own (per-file) limits."""

    def __init__(self, app: ASGIApp, limit: int = MAX_JSON_BYTES) -> None:
        self.app = app
        self.limit = limit

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope["method"] in {"POST", "PUT", "PATCH", "DELETE"}:
            headers = {k.lower(): v for k, v in scope["headers"]}
            ctype = headers.get(b"content-type", b"")
            length = headers.get(b"content-length", b"")
            if (
                not ctype.startswith(b"multipart/")
                and length.isdigit()
                and int(length) > self.limit
            ):
                resp = JSONResponse(
                    {
                        "error": {
                            "code": "payload_too_large",
                            "message": "Request body is too large",
                            "details": None,
                            "request_id": None,
                        }
                    },
                    status_code=413,
                )
                await resp(scope, receive, send)
                return
        await self.app(scope, receive, send)
