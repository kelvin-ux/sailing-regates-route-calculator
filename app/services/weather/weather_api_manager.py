from __future__ import annotations

import asyncio
import aiohttp
import redis.asyncio as redis
from datetime import datetime, timezone, timedelta
from typing import List
from typing import Dict
from typing import Optional
from typing import Tuple
import math

from app.schemas.weather import MarineWeatherRequest
from app.services.weather.WeatherCache import WeatherCache
from app.services.weather.RateLimiter import RateLimiter

from app.services.warsawtz import parse_datetime_warsaw, WARSAW_TZ, now_warsaw

class OpenMeteoService:
    def __init__(self,
                 redis_url: Optional[str] = None,
                 max_calls_per_minute: int = 500,
                 cache_ttl: int = 3600):

        self.base_url = "https://api.open-meteo.com/v1"
        self.marine_url = "https://marine-api.open-meteo.com/v1/marine"

        self.rate_limiter = RateLimiter(max_calls=max_calls_per_minute, period=60)

        self.redis_client = None
        if redis_url:
            try:
                self.redis_client = redis.from_url(redis_url)
            except Exception as e:
                print(f"Could not connect to Redis: {e}")

        self.cache = WeatherCache(self.redis_client, ttl=cache_ttl)

        self.stats = {
            'total_requests': 0,
            'cache_hits': 0,
            'api_calls': 0,
            'errors': 0
        }

    async def fetch_marine_weather(self, lat: float, lon: float) -> Dict:
        self.stats['total_requests'] += 1

        request = MarineWeatherRequest(lat=lat, lon=lon, request_id=f"{lat}:{lon}")
        cache_key = request.cache_key()

        cached = await self.cache.get(cache_key)
        if cached:
            self.stats['cache_hits'] += 1
            return cached

        async with self.rate_limiter:
            self.stats['api_calls'] += 1

            try:
                weather_data = await self._fetch_from_api(lat, lon)
                await self.cache.set(cache_key, weather_data)
                return weather_data

            except Exception as e:
                print(f"Open-Meteo API error: {e}")
                self.stats['errors'] += 1
                return self._default_marine_weather()

    async def fetch_marine_weather_at_time(self, lat: float, lon: float, target_time: datetime) -> Dict:        
        self.stats['total_requests'] += 1

        if target_time.tzinfo is None:
            target_time = target_time.replace(tzinfo=WARSAW_TZ)

        now = datetime.now(WARSAW_TZ)
        effective_time = max(target_time, now)
        
        #  Zaokrąglij do najbliższej PRZYSZŁEJ kwarty (ceil, nie floor!)
        minutes_ceil = math.ceil(effective_time.minute / 15) * 15
        
        if minutes_ceil >= 60:
            target_rounded = (effective_time + timedelta(hours=1)).replace(
                minute=0, second=0, microsecond=0
            )
        else:
            target_rounded = effective_time.replace(
                minute=minutes_ceil, second=0, microsecond=0
            )
        
        cache_key = f"marine_forecast:{lat:.2f}:{lon:.2f}:{target_rounded.isoformat()}"

        cached = await self.cache.get(cache_key)
        if cached:
            self.stats['cache_hits'] += 1
            return cached

        async with self.rate_limiter:
            self.stats['api_calls'] += 1

            try:
                weather_data = await self._fetch_forecast_at_time(lat, lon, target_rounded)
                await self.cache.set(cache_key, weather_data)
                return weather_data

            except Exception as e:
                print(f"Open-Meteo Forecast API error: {e}")
                self.stats['errors'] += 1
                return self._default_marine_weather()

    async def _fetch_forecast_at_time(self, lat: float, lon: float, target_time: datetime) -> Dict:
        print(f"[WEATHER] Fetching forecast for {target_time.isoformat()} at ({lat:.2f}, {lon:.2f})")

        async with aiohttp.ClientSession() as session:
            now = datetime.now(WARSAW_TZ)
            days_ahead = max(1, (target_time - now).days + 2)
            days_ahead = min(days_ahead, 7)

            marine_params = {
                'latitude': lat,
                'longitude': lon,
                'hourly': ','.join([
                    'wave_height',
                    'wave_direction',
                    'wave_period',
                    'wind_wave_height',
                    'wind_wave_direction',
                    'wind_wave_period',
                    'swell_wave_height',
                    'swell_wave_direction',
                    'swell_wave_period',
                ]),
                'forecast_days': days_ahead,
                'past_days': 1,
                'timezone': 'auto'
            }

            weather_params = {
                'latitude': lat,
                'longitude': lon,
                'hourly': ','.join([
                    'temperature_2m',
                    'relative_humidity_2m',
                    'pressure_msl',
                    'wind_speed_10m',
                    'wind_direction_10m',
                    'wind_gusts_10m'
                ]),
                'forecast_days': days_ahead,
                'past_days': 1,
                'timezone': 'auto'
            }

            marine_task = session.get(self.marine_url, params=marine_params, timeout=15)
            weather_task = session.get(f"{self.base_url}/forecast", params=weather_params, timeout=15)

            marine_response, weather_response = await asyncio.gather(
                marine_task, weather_task, return_exceptions=True
            )

            marine_hourly = {}
            weather_hourly = {}
            time_index = None

            if isinstance(marine_response, Exception):
                print(f"[WEATHER] Marine API exception: {marine_response}")
            elif isinstance(marine_response, aiohttp.ClientResponse):
                if marine_response.status == 200:
                    marine_json = await marine_response.json()
                    if 'hourly' in marine_json:
                        marine_hourly = marine_json['hourly']
                        times = marine_hourly.get('time', [])
                        time_index = self._find_closest_time_index(times, target_time)
                    elif 'error' in marine_json:
                        print(f"[WEATHER] Marine API error: {marine_json.get('error')} at ({lat:.2f}, {lon:.2f})")
                else:
                    print(f"[WEATHER] Marine API status {marine_response.status} at ({lat:.2f}, {lon:.2f})")

            if isinstance(weather_response, Exception):
                print(f"[WEATHER] Weather API exception: {weather_response}")
            elif isinstance(weather_response, aiohttp.ClientResponse) and weather_response.status == 200:
                weather_json = await weather_response.json()
                if 'hourly' in weather_json:
                    weather_hourly = weather_json['hourly']
                    if time_index is None:
                        times = weather_hourly.get('time', [])
                        time_index = self._find_closest_time_index(times, target_time)

            if time_index is None:
                if weather_hourly and not marine_hourly:
                    print(f"[WEATHER] No marine data at ({lat:.2f}, {lon:.2f}) - using weather only")
                    times = weather_hourly.get('time', [])
                    time_index = self._find_closest_time_index(times, target_time)
                
                if time_index is None:
                    available_times = marine_hourly.get('time', [])[:3] if marine_hourly else []
                    weather_times = weather_hourly.get('time', [])[:3] if weather_hourly else []
                    print(f"Could not find time index for {target_time}. Marine times: {available_times}, Weather times: {weather_times}")
                    return self._default_marine_weather()

            def safe_get(data: dict, key: str, idx: int, default=None):
                arr = data.get(key, [])
                if arr and idx < len(arr):
                    val = arr[idx]
                    return val if val is not None else default
                return default

            return {
                'wind_speed': safe_get(weather_hourly, 'wind_speed_10m', time_index, 5.0),
                'wind_direction': safe_get(weather_hourly, 'wind_direction_10m', time_index, 0.0),
                'wind_gusts': safe_get(weather_hourly, 'wind_gusts_10m', time_index, 7.0),

                'wave_height': safe_get(marine_hourly, 'wave_height', time_index, 0.5),
                'wave_direction': safe_get(marine_hourly, 'wave_direction', time_index, 0.0),
                'wave_period': safe_get(marine_hourly, 'wave_period', time_index, 4.0),

                'wind_wave_height': safe_get(marine_hourly, 'wind_wave_height', time_index, 0.3),
                'wind_wave_direction': safe_get(marine_hourly, 'wind_wave_direction', time_index, 0.0),
                'wind_wave_period': safe_get(marine_hourly, 'wind_wave_period', time_index, 3.0),

                'swell_wave_height': safe_get(marine_hourly, 'swell_wave_height', time_index, 0.2),
                'swell_wave_direction': safe_get(marine_hourly, 'swell_wave_direction', time_index, 0.0),
                'swell_wave_period': safe_get(marine_hourly, 'swell_wave_period', time_index, 6.0),

                'current_velocity': 0.1,
                'current_direction': 0.0,

                'temperature': safe_get(weather_hourly, 'temperature_2m', time_index, 15.0),
                'humidity': safe_get(weather_hourly, 'relative_humidity_2m', time_index, 70.0),
                'pressure': safe_get(weather_hourly, 'pressure_msl', time_index, 1013.0),

                'timestamp': target_time.isoformat(),
                'forecast_time': target_time.isoformat(),
                'coords': {'lat': lat, 'lon': lon},
                'source': 'open-meteo-forecast',
                'is_default': False
            }

    def _find_closest_time_index(self, times: List[str], target_time: datetime) -> Optional[int]:
        if not times:
            return None

        if target_time.tzinfo is None:
            target_time = target_time.replace(tzinfo=WARSAW_TZ)

        min_diff = None
        best_idx = None

        for idx, time_str in enumerate(times):
            try:
                forecast_time = datetime.fromisoformat(time_str)
                if forecast_time.tzinfo is None:
                    forecast_time = forecast_time.replace(tzinfo=WARSAW_TZ)

                diff = abs((forecast_time - target_time).total_seconds())

                if min_diff is None or diff < min_diff:
                    min_diff = diff
                    best_idx = idx
            except Exception:
                continue

        return best_idx

    async def fetch_batch_at_time(self,
                                  points: List[Tuple[float, float]],
                                  target_time: datetime,
                                  priorities: Optional[List[int]] = None) -> Dict[int, Dict]:
        if not priorities:
            priorities = [0] * len(points)

        sorted_points = sorted(
            enumerate(zip(points, priorities)),
            key=lambda x: x[1][1],
            reverse=True
        )

        results = {}

        batch_size = 10
        for i in range(0, len(sorted_points), batch_size):
            batch = sorted_points[i:i + batch_size]

            tasks = []
            for idx, ((lat, lon), priority) in batch:
                task = self.fetch_marine_weather_at_time(lat, lon, target_time)
                tasks.append((idx, task))

            for idx, task in tasks:
                try:
                    result = await task
                    results[idx] = result
                except Exception as e:
                    print(f"Failed to fetch weather for point {idx}: {e}")
                    results[idx] = self._default_marine_weather()

            if i + batch_size < len(sorted_points):
                await asyncio.sleep(0.2)

        return results

    async def _fetch_from_api(self, lat: float, lon: float) -> Dict:
        async with aiohttp.ClientSession() as session:
            marine_params = {
                'latitude': lat,
                'longitude': lon,
                'current': ','.join([
                    'wave_height',
                    'wave_direction',
                    'wave_period',
                    'wind_wave_height',
                    'wind_wave_direction',
                    'wind_wave_period',
                    'swell_wave_height',
                    'swell_wave_direction',
                    'swell_wave_period',
                    'ocean_current_velocity',
                    'ocean_current_direction'
                ]),
                'timezone': 'auto'
            }

            weather_params = {
                'latitude': lat,
                'longitude': lon,
                'current': ','.join([
                    'temperature_2m',
                    'relative_humidity_2m',
                    'pressure_msl',
                    'wind_speed_10m',
                    'wind_direction_10m',
                    'wind_gusts_10m'
                ]),
                'timezone': 'auto'
            }

            marine_task = session.get(self.marine_url, params=marine_params, timeout=10)
            weather_task = session.get(f"{self.base_url}/forecast", params=weather_params, timeout=10)

            marine_response, weather_response = await asyncio.gather(
                marine_task, weather_task, return_exceptions=True
            )

            marine_data = {}
            weather_data = {}

            if isinstance(marine_response, aiohttp.ClientResponse) and marine_response.status == 200:
                marine_json = await marine_response.json()
                if 'current' in marine_json:
                    marine_data = marine_json['current']

            if isinstance(weather_response, aiohttp.ClientResponse) and weather_response.status == 200:
                weather_json = await weather_response.json()
                if 'current' in weather_json:
                    weather_data = weather_json['current']

            return {
                'wind_speed': weather_data.get('wind_speed_10m', 5.0),
                'wind_direction': weather_data.get('wind_direction_10m', 0.0),
                'wind_gusts': weather_data.get('wind_gusts_10m', 7.0),

                'wave_height': marine_data.get('wave_height', 0.5),
                'wave_direction': marine_data.get('wave_direction', 0.0),
                'wave_period': marine_data.get('wave_period', 4.0),

                'wind_wave_height': marine_data.get('wind_wave_height', 0.3),
                'wind_wave_direction': marine_data.get('wind_wave_direction', 0.0),
                'wind_wave_period': marine_data.get('wind_wave_period', 3.0),

                'swell_wave_height': marine_data.get('swell_wave_height', 0.2),
                'swell_wave_direction': marine_data.get('swell_wave_direction', 0.0),
                'swell_wave_period': marine_data.get('swell_wave_period', 6.0),

                'current_velocity': marine_data.get('ocean_current_velocity', 0.1),
                'current_direction': marine_data.get('ocean_current_direction', 0.0),

                'temperature': weather_data.get('temperature_2m', 15.0),
                'humidity': weather_data.get('relative_humidity_2m', 70.0),
                'pressure': weather_data.get('pressure_msl', 1013.0),

                'timestamp': datetime.now().isoformat(),
                'coords': {'lat': lat, 'lon': lon},
                'source': 'open-meteo'
            }

    def _default_marine_weather(self) -> Dict:
        return {
            'wind_speed': 5.0,
            'wind_direction': 0.0,
            'wind_gusts': 7.0,
            'wave_height': 0.5,
            'wave_direction': 0.0,
            'wave_period': 4.0,
            'wind_wave_height': 0.3,
            'wind_wave_direction': 0.0,
            'wind_wave_period': 3.0,
            'swell_wave_height': 0.2,
            'swell_wave_direction': 0.0,
            'swell_wave_period': 6.0,
            'current_velocity': 0.1,
            'current_direction': 0.0,
            'temperature': 15.0,
            'humidity': 70.0,
            'pressure': 1013.0,
            'timestamp': datetime.now().isoformat(),
            'is_default': True,
            'source': 'default'
        }

    async def fetch_batch(self,
                          points: List[Tuple[float, float]],
                          priorities: Optional[List[int]] = None) -> Dict[int, Dict]:
        if not priorities:
            priorities = [0] * len(points)

        sorted_points = sorted(
            enumerate(zip(points, priorities)),
            key=lambda x: x[1][1],
            reverse=True
        )

        results = {}

        batch_size = 10
        for i in range(0, len(sorted_points), batch_size):
            batch = sorted_points[i:i + batch_size]

            tasks = []
            for idx, ((lat, lon), priority) in batch:
                task = self.fetch_marine_weather(lat, lon)
                tasks.append((idx, task))

            for idx, task in tasks:
                try:
                    result = await task
                    results[idx] = result
                except Exception as e:
                    print(f"Failed to fetch weather for point {idx}: {e}")
                    results[idx] = self._default_marine_weather()

            if i + batch_size < len(sorted_points):
                await asyncio.sleep(0.2)

        return results

    async def fetch_forecast(self,
                             lat: float,
                             lon: float,
                             hours: int = 48) -> List[Dict]:
        cache_key = f"forecast:marine:{lat:.2f}:{lon:.2f}:{hours}"

        cached = await self.cache.get(cache_key)
        if cached:
            self.stats['cache_hits'] += 1
            return cached

        async with self.rate_limiter:
            self.stats['api_calls'] += 1

            try:
                async with aiohttp.ClientSession() as session:
                    params = {
                        'latitude': lat,
                        'longitude': lon,
                        'hourly': ','.join([
                            'wave_height',
                            'wave_direction',
                            'wave_period',
                            'wind_speed_10m',
                            'wind_direction_10m',
                            'temperature_2m',
                            'pressure_msl'
                        ]),
                        'forecast_hours': min(hours, 168),
                        'timezone': 'auto'
                    }

                    async with session.get(
                            self.marine_url,
                            params=params,
                            timeout=15
                    ) as response:
                        if response.status == 200:
                            data = await response.json()

                            forecast = []
                            if 'hourly' in data:
                                hourly = data['hourly']
                                times = hourly.get('time', [])

                                for i, timestamp in enumerate(times[:hours]):
                                    forecast.append({
                                        'timestamp': timestamp,
                                        'wave_height': hourly.get('wave_height', [None])[i],
                                        'wave_direction': hourly.get('wave_direction', [None])[i],
                                        'wave_period': hourly.get('wave_period', [None])[i],
                                        'wind_speed': hourly.get('wind_speed_10m', [None])[i],
                                        'wind_direction': hourly.get('wind_direction_10m', [None])[i],
                                        'temperature': hourly.get('temperature_2m', [None])[i],
                                        'pressure': hourly.get('pressure_msl', [None])[i]
                                    })

                            await self.cache.set(cache_key, forecast)
                            return forecast

            except Exception as e:
                print(f"Forecast API error: {e}")
                self.stats['errors'] += 1
                return []

    def get_stats(self) -> Dict:
        total = self.stats['cache_hits'] + self.stats['api_calls']
        cache_ratio = self.stats['cache_hits'] / total if total > 0 else 0

        return {
            **self.stats,
            'cache_hit_ratio': f"{cache_ratio:.1%}",
            'remaining_calls': self.rate_limiter.max_calls - len(self.rate_limiter.calls)
        }

    async def close(self):
        if self.redis_client:
            await self.redis_client.close()