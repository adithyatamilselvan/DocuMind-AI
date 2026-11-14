"""Fixed-window rate limiter on Redis, for deployments with several API replicas.
The in-process limiter (rate_limit.py) is only correct for a single process."""

from typing import Any

from app.core.errors import too_many_requests


class RedisLimiter:
    def __init__(self, client: Any, prefix: str = "documind:rl:") -> None:
        self.r = client  # redis.asyncio.Redis (or a compatible object)
        self.prefix = prefix

    async def check(self, key: str, limit: int, window_s: int) -> None:
        k = f"{self.prefix}{key}"
        count = await self.r.incr(k)
        if count == 1:
            await self.r.expire(k, window_s)
        if count > limit:
            ttl = await self.r.ttl(k)
            raise too_many_requests(retry_after=max(1, int(ttl) if ttl and ttl > 0 else window_s))
