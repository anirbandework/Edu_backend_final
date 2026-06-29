# app/core/cache.py
"""Async cache management using Redis."""
import json
import logging
from typing import Any, Optional
from redis.asyncio import Redis
from .config import settings

logger = logging.getLogger(__name__)

class CacheService:
    def __init__(self):
        self.client = None

    async def initialize(self):
        self.client = Redis.from_url(settings.redis_url)
        logger.info("Redis cache connected")

    async def close(self):
        if self.client:
            await self.client.close()
            logger.info("Redis cache disconnected")
    
    async def get(self, key: str) -> Optional[Any]:
        try:
            if not self.client:
                await self.initialize()
            value = await self.client.get(key)
            return json.loads(value) if value else None
        except Exception as e:
            logger.error(f"Cache get error: {e}")
            return None
    
    async def set(self, key: str, value: Any, ttl: int = 300) -> bool:
        try:
            if not self.client:
                await self.initialize()
            await self.client.setex(key, ttl, json.dumps(value))
            return True
        except Exception as e:
            logger.error(f"Cache set error: {e}")
            return False
    
    async def delete(self, key: str) -> bool:
        try:
            if not self.client:
                await self.initialize()
            await self.client.delete(key)
            return True
        except Exception as e:
            logger.error(f"Cache delete error: {e}")
            return False

cache_service = CacheService()
