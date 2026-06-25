"""Rate limiter.

Uses Redis (fixed-window counter via INCR+EXPIRE) so limits are shared across
all gunicorn workers and survive at scale. Falls back to a per-process in-memory
counter if Redis is unavailable, so a cache outage never hard-fails requests.
"""
from fastapi import HTTPException, Request
from typing import Dict
import time
import logging

from .config import settings

logger = logging.getLogger(__name__)


class RateLimiter:
    def __init__(self):
        self._mem: Dict[str, list] = {}
        self._redis = None
        self._redis_init = False

    async def _get_redis(self):
        if self._redis_init:
            return self._redis
        self._redis_init = True
        try:
            import redis.asyncio as aioredis
            self._redis = aioredis.from_url(settings.redis_url, encoding="utf-8", decode_responses=True)
            await self._redis.ping()
        except Exception as e:  # pragma: no cover
            logger.warning(f"Rate limiter falling back to in-memory (no Redis): {e}")
            self._redis = None
        return self._redis

    async def check_rate_limit(self, request: Request, max_requests: int = 60, window: int = 60):
        client_ip = request.client.host if request.client else "unknown"
        endpoint = str(request.url.path)
        now = int(time.time())
        bucket = now // window  # fixed window
        key = f"ratelimit:{client_ip}:{endpoint}:{bucket}"

        redis = await self._get_redis()
        if redis is not None:
            try:
                count = await redis.incr(key)
                if count == 1:
                    await redis.expire(key, window)
                if count > max_requests:
                    raise HTTPException(status_code=429, detail="Rate limit exceeded")
                return
            except HTTPException:
                raise
            except Exception as e:  # pragma: no cover
                logger.debug(f"Redis rate-limit error, falling back to memory: {e}")

        # In-memory fallback (per-process)
        mkey = f"{client_ip}:{endpoint}"
        nowf = time.time()
        self._mem[mkey] = [t for t in self._mem.get(mkey, []) if nowf - t < window]
        if len(self._mem[mkey]) >= max_requests:
            raise HTTPException(status_code=429, detail="Rate limit exceeded")
        self._mem[mkey].append(nowf)


rate_limiter = RateLimiter()
