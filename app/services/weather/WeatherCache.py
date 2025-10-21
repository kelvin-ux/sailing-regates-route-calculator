from __future__ import annotations

import json
import redis.asyncio as redis

from typing import Dict
from typing import Optional
from datetime import datetime
from datetime import timedelta


class WeatherCache:
    """Cache for weather data with Redis and in-memory fallback"""
    def __init__(self, redis_client: Optional[redis.Redis] = None, ttl: int = 3600):
        self.redis = redis_client
        self.ttl = ttl
        self.memory_cache = {}

    async def get(self, key: str) -> Optional[Dict]:
        if self.redis:
            try:
                data = await self.redis.get(key)
                if data:
                    return json.loads(data)
            except Exception as e:
                print(f"Redis error: {e}")

        if key in self.memory_cache:
            cached = self.memory_cache[key]
            if cached['expires'] > datetime.now():
                return cached['data']
            else:
                del self.memory_cache[key]

        return None

    async def set(self, key: str, data: Dict):
        if self.redis:
            try:
                await self.redis.setex(
                    key,
                    self.ttl,
                    json.dumps(data)
                )
            except Exception as e:
                print(f"Redis error: {e}")

        self.memory_cache[key] = {
            'data': data,
            'expires': datetime.now() + timedelta(seconds=self.ttl)
        }

        if len(self.memory_cache) > 1000:
            now = datetime.now()
            self.memory_cache = {
                k: v for k, v in self.memory_cache.items()
                if v['expires'] > now
            }