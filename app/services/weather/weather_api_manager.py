import asyncio
import time
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import aiohttp
from collections import deque
import redis.asyncio as redis
import json


# TODO dodac rowniez implementacje openmeteo-requests dla fal etc.. // jezeli mozliwe to calkowicie przerzucic sie na tamto api

@dataclass
class WeatherRequest:
    lat: float
    lon: float
    request_id: str
    priority: int = 0  # 0=normal, 1=high priority (control points)
    timestamp: datetime = field(default_factory=datetime.now)

    def cache_key(self, grid_size: float = 0.01) -> str:
        """Generuje klucz cache na podstawie gridu geograficznego"""
        grid_lat = round(self.lat / grid_size) * grid_size
        grid_lon = round(self.lon / grid_size) * grid_size
        return f"weather:{grid_lat:.2f}:{grid_lon:.2f}"


class RateLimiter:
    def __init__(self, max_calls: int = 60, period: int = 60):
        self.max_calls = max_calls
        self.period = period
        self.calls = deque()
        self._lock = asyncio.Lock()

    async def acquire(self):
        async with self._lock:
            now = time.time()
            while self.calls and self.calls[0] < now - self.period:
                self.calls.popleft()

            if len(self.calls) >= self.max_calls:
                sleep_time = self.period - (now - self.calls[0]) + 0.1
                await asyncio.sleep(sleep_time)
                return await self.acquire()

            self.calls.append(now)

    async def __aenter__(self):
        await self.acquire()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass


class WeatherCache:
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


class WeatherAPIManager:
    def __init__(self,
                 api_key: str,
                 redis_url: Optional[str] = None,
                 max_calls_per_minute: int = 55,
                 cache_ttl: int = 3600):

        self.api_key = api_key
        self.base_url = "https://api.openweathermap.org/data/2.5"
        self.rate_limiter = RateLimiter(max_calls=max_calls_per_minute, period=60)

        self.redis_client = None
        if redis_url:
            try:
                self.redis_client = redis.from_url(redis_url)
            except Exception as e:
                print(f"Could not connect to Redis: {e}")

        self.cache = WeatherCache(self.redis_client, ttl=cache_ttl)

        self.request_queue: asyncio.Queue = asyncio.Queue()
        self.results: Dict[str, Dict] = {}

        self.stats = {
            'total_requests': 0,
            'cache_hits': 0,
            'api_calls': 0,
            'errors': 0
        }

    async def fetch_weather(self, lat: float, lon: float) -> Dict:
        request = WeatherRequest(lat=lat, lon=lon, request_id=f"{lat}:{lon}")
        cache_key = request.cache_key()

        cached = await self.cache.get(cache_key)
        if cached:
            self.stats['cache_hits'] += 1
            return cached

        async with self.rate_limiter:
            self.stats['api_calls'] += 1

            async with aiohttp.ClientSession() as session:
                params = {
                    'lat': lat,
                    'lon': lon,
                    'appid': self.api_key,
                    'units': 'metric'
                }

                try:
                    async with session.get(
                            f"{self.base_url}/weather",
                            params=params,
                            timeout=10
                    ) as response:
                        if response.status == 200:
                            data = await response.json()
                            weather_data = {
                                'wind_speed': data['wind']['speed'],
                                'wind_dir': data['wind']['deg'],
                                'temp': data['main']['temp'],
                                'pressure': data['main']['pressure'],
                                'humidity': data['main']['humidity'],
                                'description': data['weather'][0]['description'],
                                'timestamp': datetime.now().isoformat()
                            }

                            await self.cache.set(cache_key, weather_data)
                            return weather_data
                        else:
                            self.stats['errors'] += 1
                            return self._default_weather()

                except asyncio.TimeoutError:
                    self.stats['errors'] += 1
                    return self._default_weather()
                except Exception as e:
                    print(f"Weather API error: {e}")
                    self.stats['errors'] += 1
                    return self._default_weather()

    def _default_weather(self) -> Dict:
        return {
            'wind_speed': 5.0,
            'wind_dir': 0.0,
            'temp': 15.0,
            'pressure': 1013.0,
            'humidity': 70.0,
            'description': 'failed to get data, standard data applied',
            'timestamp': datetime.now().isoformat(),
            'is_default': True
        }

    async def fetch_batch(self,
                          points: List[Tuple[float, float]],
                          priorities: Optional[List[int]] = None) -> Dict[Tuple[float, float], Dict]:
        if not priorities:
            priorities = [0] * len(points)

        sorted_points = sorted(
            zip(points, priorities),
            key=lambda x: x[1],
            reverse=True
        )

        results = {}
        tasks = []

        batch_size = 10
        for i in range(0, len(sorted_points), batch_size):
            batch = sorted_points[i:i + batch_size]

            for (lat, lon), _ in batch:
                task = self.fetch_weather(lat, lon)
                tasks.append((lat, lon, task))

            for lat, lon, task in tasks:
                try:
                    result = await task
                    results[(lat, lon)] = result
                except Exception as e:
                    print(f"Failed to fetch weather for ({lat}, {lon}): {e}")
                    results[(lat, lon)] = self._default_weather()

            tasks.clear()

            if i + batch_size < len(sorted_points):
                await asyncio.sleep(0.5)

        return results

    async def fetch_forecast(self,
                             lat: float,
                             lon: float,
                             hours: int = 48) -> List[Dict]:
        cache_key = f"forecast:{lat:.2f}:{lon:.2f}:{hours}"

        cached = await self.cache.get(cache_key)
        if cached:
            self.stats['cache_hits'] += 1
            return cached

        async with self.rate_limiter:
            self.stats['api_calls'] += 1

            async with aiohttp.ClientSession() as session:
                params = {
                    'lat': lat,
                    'lon': lon,
                    'appid': self.api_key,
                    'units': 'metric',
                    'cnt': hours // 3
                }

                try:
                    async with session.get(
                            f"{self.base_url}/forecast",
                            params=params,
                            timeout=10
                    ) as response:
                        if response.status == 200:
                            data = await response.json()

                            forecast = []
                            for item in data['list']:
                                forecast.append({
                                    'timestamp': item['dt_txt'],
                                    'wind_speed': item['wind']['speed'],
                                    'wind_dir': item['wind']['deg'],
                                    'temp': item['main']['temp'],
                                    'pressure': item['main']['pressure'],
                                    'humidity': item['main']['humidity'],
                                    'description': item['weather'][0]['description']
                                })

                            await self.cache.set(cache_key, forecast)
                            return forecast

                except Exception as e:
                    print(f"Forecast API error: {e}")
                    return []

    def get_stats(self) -> Dict:
        total = self.stats['cache_hits'] + self.stats['api_calls']
        cache_ratio = self.stats['cache_hits'] / total if total > 0 else 0

        return {
            **self.stats,
            'cache_hit_ratio': f"{cache_ratio:.1%}",
            'remaining_calls': self.rate_limiter.max_calls - len(self.rate_limiter.calls)
        }


class WeatherBatchProcessor:
    def __init__(self, api_manager: WeatherAPIManager):
        self.api_manager = api_manager
        self.processing = False

    async def process_mesh_points(self,weather_points: List[Tuple[float, float]],) -> Dict[int, Dict]:
        print(f"Processing {len(weather_points)} weather points...")

        priorities = [max(0, len(weather_points) - i) for i in range(len(weather_points))]

        weather_data = await self.api_manager.fetch_batch(weather_points, priorities)

        indexed_data = {}
        for idx, (lat, lon) in enumerate(weather_points):
            if (lat, lon) in weather_data:
                indexed_data[idx] = weather_data[(lat, lon)]
            else:
                indexed_data[idx] = self.api_manager._default_weather()

        print(f"Weather fetch complete. Stats: {self.api_manager.get_stats()}")

        return indexed_data

