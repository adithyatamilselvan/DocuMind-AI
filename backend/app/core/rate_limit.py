import time
from collections import defaultdict, deque
from collections.abc import Awaitable, Callable

from fastapi import Request

from app.core.config import get_settings
from app.core.errors import too_many_requests


def client_ip(request: Request) -> str:
    if get_settings().trust_forwarded_for:
        fwd = request.headers.get("x-forwarded-for")
        if fwd:
            return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


class SlidingWindowLimiter:
    """In-process sliding window. Correct for a single API process; replaced by a
    Redis-backed implementation in Phase 17 when running multiple replicas."""

    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def check(self, key: str, limit: int, window_s: int) -> None:
        if not get_settings().rate_limit_enabled:
            return
        now = time.monotonic()
        q = self._hits[key]
        while q and q[0] <= now - window_s:
            q.popleft()
        if len(q) >= limit:
            raise too_many_requests(retry_after=max(1, int(window_s - (now - q[0]))))
        q.append(now)

    def reset(self) -> None:
        self._hits.clear()


limiter = SlidingWindowLimiter()


def rate_limit(name: str, limit: int, window_s: int) -> Callable[[Request], Awaitable[None]]:
    async def dep(request: Request) -> None:
        if not get_settings().rate_limit_enabled:
            return
        key = f"{name}:{client_ip(request)}"
        shared = getattr(request.app.state, "redis_limiter", None)
        if shared is not None:
            await shared.check(key, limit, window_s)
        else:
            limiter.check(key, limit, window_s)

    return dep
