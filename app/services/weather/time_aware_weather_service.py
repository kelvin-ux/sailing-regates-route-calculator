from __future__ import annotations

import asyncio
import math
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass

import numpy as np
from scipy.spatial import KDTree
from shapely.geometry import LineString, Point
from shapely.ops import nearest_points
        
from app.schemas.time_aware_weather import (
    TimeAwareWeatherPoint,
    TimeAwareWeatherRequest,
    RouteETAProfile,
    SegmentETA,
    ETACalculationConfig,
    IterativeRouteResult,
    ETAConfidence,
)
from app.services.weather.weather_api_manager import OpenMeteoService
from app.services.weather.WeatherCache import WeatherCache
from app.services.weather.RateLimiter import RateLimiter
from app.services.warsawtz import WARSAW_TZ, now_warsaw


@dataclass
class WeatherAtTime:
    lat: float
    lon: float
    forecast_time: datetime
    
    wind_speed: float           # km/s
    wind_direction: float       # degrees
    wind_gusts: float           # km/s
    
    wave_height: float          # m
    wave_direction: float       # degrees  
    wave_period: float          # seconds
    
    wind_wave_height: float     # m
    swell_wave_height: float    # m
    
    current_velocity: float     # m/s
    current_direction: float    # degrees
    
    temperature: float          # Celsius
    humidity: float             # %
    pressure: float             # hPa
    
    source: str = "open-meteo"
    is_default: bool = False
    fetched_at: Optional[datetime] = None
    
    def to_heuristics_dict(self) -> Dict[str, Any]:
        return {
            'wind_speed_10m': self.wind_speed * 0.539957,  # km/h -> knots
            'wind_direction_10m': self.wind_direction,
            'wave_height': self.wave_height,
            'wave_direction': self.wave_direction,
            'wave_period': self.wave_period,
            'current_speed': self.current_velocity * 0.539957,  # km/h -> knots
            'current_direction': self.current_direction,
        }


class TimeAwareWeatherService:
    def __init__(
        self,
        config: Optional[ETACalculationConfig] = None,
        base_weather_service: Optional[OpenMeteoService] = None,
        redis_url: Optional[str] = None,
    ):
        self.config = config or ETACalculationConfig()
        
        self.base_service = base_weather_service or OpenMeteoService(
            redis_url=redis_url,
            max_calls_per_minute=500,
            cache_ttl=3600
        )
        
        self.time_cache = WeatherCache(ttl=3600)
        
        self.stats = {
            'total_requests': 0,
            'cache_hits': 0,
            'api_calls': 0,
            'batches_processed': 0,
            'points_processed': 0,
        }
    
    async def fetch_weather_for_profile(
        self,
        profile: RouteETAProfile,
        force_refresh: bool = False
    ) -> Dict[int, WeatherAtTime]:
        if not profile.weather_points:
            return {}
        time_groups = profile.group_points_by_quarter(interval_minutes=15)
        
        group_info = [(t.strftime('%H:%M'), len(pts)) for t, pts in sorted(time_groups.items())]
        print(f"[ITER] Weather time groups: {group_info}")
        
        results: Dict[int, WeatherAtTime] = {}
        
        for quarter, points in sorted(time_groups.items()):
            batch_results = await self._fetch_batch_for_time(
                points=points,
                target_time=quarter,
                force_refresh=force_refresh
            )
            results.update(batch_results)
        
        return results
    
    async def fetch_weather_for_points(
        self,
        points: List[TimeAwareWeatherPoint],
        force_refresh: bool = False
    ) -> Dict[int, WeatherAtTime]:
        if not points:
            return {}
        
        self.stats['total_requests'] += len(points)
        self.stats['points_processed'] += len(points)
        
        time_groups = self._group_points_by_time(points)
        
        results: Dict[int, WeatherAtTime] = {}
        
        for rounded_time, group_points in sorted(time_groups.items()):
            batch_results = await self._fetch_batch_for_time(
                points=group_points,
                target_time=rounded_time,
                force_refresh=force_refresh
            )
            results.update(batch_results)
        
        return results
    
    async def fetch_weather_along_route(
        self,
        waypoints_wgs84: List[Tuple[float, float]],
        departure_time: datetime,
        estimated_speed_knots: float = 5.0,
    ) -> List[WeatherAtTime]:
        if not waypoints_wgs84:
            return []
        
        results: List[WeatherAtTime] = []
        current_time = departure_time
        
        speed_ms = estimated_speed_knots * 0.514444  # knots -> m/s
        
        for i, (lon, lat) in enumerate(waypoints_wgs84):
            weather = await self._fetch_single_point(
                lat=lat,
                lon=lon,
                target_time=current_time,
                point_idx=i
            )
            results.append(weather)
            
            if i < len(waypoints_wgs84) - 1:
                next_lon, next_lat = waypoints_wgs84[i + 1]
                distance_m = self._haversine_distance(lat, lon, next_lat, next_lon)
                travel_time_seconds = distance_m / speed_ms if speed_ms > 0 else 0
                current_time = current_time + timedelta(seconds=travel_time_seconds)
        
        return results
    
    async def update_weather_for_segments(
        self,
        segments: List[SegmentETA],
        weather_points: List[TimeAwareWeatherPoint],
        force_refresh: bool = False
    ) -> Dict[int, WeatherAtTime]:
        if not segments or not weather_points:
            return {}
        
        position_times = self._build_position_time_map(segments)
        
        for wp in weather_points:
            closest_time = self._find_closest_time(
                wp.x, wp.y, 
                position_times,
                fallback=segments[0].start_time
            )
            wp.update_eta(closest_time)
        
        return await self.fetch_weather_for_points(weather_points, force_refresh)
    
    def create_initial_profile(
        self,
        weather_points_data: List[Dict[str, Any]],
        departure_time: datetime,
        route_line_coords: List[Tuple[float, float]],
        meshed_area_id,
        route_id,
        initial_speed_knots: float = 5.0,
    ) -> RouteETAProfile:
        profile = RouteETAProfile(
            meshed_area_id=meshed_area_id,
            route_id=route_id,
            departure_time=departure_time,
        )
        
        if not weather_points_data:
            return profile
        
        route_line = LineString(route_line_coords) if route_line_coords else None
        total_route_length = route_line.length if route_line else 0
        speed_ms = initial_speed_knots * 0.514444
        
        for wp_data in weather_points_data:
            idx = wp_data.get('idx', 0)
            x = wp_data.get('x', 0.0)
            y = wp_data.get('y', 0.0)
            lon = wp_data.get('lon', x)
            lat = wp_data.get('lat', y)
            
            distance_along = 0.0
            if route_line and total_route_length > 0:
                point = Point(x, y)
                
                nearest_on_route = nearest_points(route_line, point)[0]
                distance_along = route_line.project(nearest_on_route)
                distance_along = max(0, min(distance_along, total_route_length))
            
            travel_time_seconds = distance_along / speed_ms if speed_ms > 0 else 0
            eta = departure_time + timedelta(seconds=travel_time_seconds)
            
            weather_point = TimeAwareWeatherPoint(
                idx=idx,
                x=x,
                y=y,
                lon=lon,
                lat=lat,
                eta=eta,
                eta_confidence=ETAConfidence.ESTIMATED,
                elapsed_seconds=travel_time_seconds,
                distance_from_start_m=distance_along,
                route_point_id=wp_data.get('route_point_id'),
            )
            
            profile.weather_points.append(weather_point)
        
        if profile.weather_points:
            sorted_pts = sorted(profile.weather_points, key=lambda p: p.distance_from_start_m)
            eta_times = [wp.eta.strftime('%H:%M:%S') for wp in sorted_pts[:5]]
            distances = [f"{wp.distance_from_start_m:.0f}m" for wp in sorted_pts[:5]]
            eta_times_last = [wp.eta.strftime('%H:%M:%S') for wp in sorted_pts[-3:]]
            distances_last = [f"{wp.distance_from_start_m:.0f}m" for wp in sorted_pts[-3:]]
            print(f"[ITER] Initial ETAs (first 5): {eta_times}, distances: {distances}")
            print(f"[ITER] Initial ETAs (last 3): {eta_times_last}, distances: {distances_last}")
            print(f"[ITER] Route length: {total_route_length:.0f}m, speed: {initial_speed_knots:.1f}kt")
        
        return profile
    
    async def _fetch_batch_for_time(
        self,
        points: List[TimeAwareWeatherPoint],
        target_time: datetime,
        force_refresh: bool = False
    ) -> Dict[int, WeatherAtTime]:
        self.stats['batches_processed'] += 1
        
        results: Dict[int, WeatherAtTime] = {}
        to_fetch: List[TimeAwareWeatherPoint] = []
        
        for point in points:
            if not force_refresh:
                cache_key = point.cache_key(
                    grid_size=self.config.coord_grid_size,
                    time_round_minutes=self.config.time_round_minutes
                )
                cached = await self.time_cache.get(cache_key)
                
                if cached:
                    self.stats['cache_hits'] += 1
                    results[point.idx] = self._dict_to_weather_at_time(
                        cached, point.lat, point.lon, point.eta
                    )
                    continue
            
            to_fetch.append(point)
        
        if to_fetch:
            api_results = await self._fetch_from_api_batch(to_fetch, target_time)
            
            for point in to_fetch:
                if point.idx in api_results:
                    weather = api_results[point.idx]
                    results[point.idx] = weather
                    cache_key = point.cache_key(
                        grid_size=self.config.coord_grid_size,
                        time_round_minutes=self.config.time_round_minutes
                    )
                    await self.time_cache.set(
                        cache_key, 
                        self._weather_to_dict(weather)
                    )
        
        return results
    
    async def _fetch_from_api_batch(
        self,
        points: List[TimeAwareWeatherPoint],
        target_time: datetime
    ) -> Dict[int, WeatherAtTime]:
        self.stats['api_calls'] += len(points)
        
        results: Dict[int, WeatherAtTime] = {}
        
        coords = [(point.lat, point.lon) for point in points]
        
        api_data = await self.base_service.fetch_batch_at_time(
            points=coords,
            target_time=target_time
        )
        
        for i, point in enumerate(points):
            if i in api_data:
                data = api_data[i]
                weather = WeatherAtTime(
                    lat=point.lat,
                    lon=point.lon,
                    forecast_time=point.eta,
                    wind_speed=data.get('wind_speed', 5.0),
                    wind_direction=data.get('wind_direction', 0.0),
                    wind_gusts=data.get('wind_gusts', 7.0),
                    wave_height=data.get('wave_height', 0.5),
                    wave_direction=data.get('wave_direction', 0.0),
                    wave_period=data.get('wave_period', 4.0),
                    wind_wave_height=data.get('wind_wave_height', 0.3),
                    swell_wave_height=data.get('swell_wave_height', 0.2),
                    current_velocity=data.get('current_velocity', 0.1),
                    current_direction=data.get('current_direction', 0.0),
                    temperature=data.get('temperature', 15.0),
                    humidity=data.get('humidity', 70.0),
                    pressure=data.get('pressure', 1013.0),
                    source=data.get('source', 'open-meteo'),
                    is_default=data.get('is_default', False),
                    fetched_at=datetime.utcnow()
                )
                results[point.idx] = weather
            else:
                results[point.idx] = self._default_weather(
                    point.lat, point.lon, point.eta
                )
        
        return results
    
    async def _fetch_single_point(
        self,
        lat: float,
        lon: float,
        target_time: datetime,
        point_idx: int = 0
    ) -> WeatherAtTime:
        cache_key = f"taw:{lat:.2f}:{lon:.2f}:{target_time.replace(minute=0, second=0).isoformat()}"
        cached = await self.time_cache.get(cache_key)
        
        if cached:
            self.stats['cache_hits'] += 1
            return self._dict_to_weather_at_time(cached, lat, lon, target_time)
        self.stats['api_calls'] += 1
        data = await self.base_service.fetch_marine_weather_at_time(lat, lon, target_time)
        
        weather = WeatherAtTime(
            lat=lat,
            lon=lon,
            forecast_time=target_time,
            wind_speed=data.get('wind_speed', 5.0),
            wind_direction=data.get('wind_direction', 0.0),
            wind_gusts=data.get('wind_gusts', 7.0),
            wave_height=data.get('wave_height', 0.5),
            wave_direction=data.get('wave_direction', 0.0),
            wave_period=data.get('wave_period', 4.0),
            wind_wave_height=data.get('wind_wave_height', 0.3),
            swell_wave_height=data.get('swell_wave_height', 0.2),
            current_velocity=data.get('current_velocity', 0.1),
            current_direction=data.get('current_direction', 0.0),
            temperature=data.get('temperature', 15.0),
            humidity=data.get('humidity', 70.0),
            pressure=data.get('pressure', 1013.0),
            source=data.get('source', 'open-meteo'),
            is_default=data.get('is_default', False),
            fetched_at=datetime.utcnow()
        )
        
        await self.time_cache.set(cache_key, self._weather_to_dict(weather))
        
        return weather
    
    def _group_points_by_time(
        self,
        points: List[TimeAwareWeatherPoint]
    ) -> Dict[datetime, List[TimeAwareWeatherPoint]]:
        groups: Dict[datetime, List[TimeAwareWeatherPoint]] = {}
        interval = self.config.time_round_minutes
        
        for point in points:
            minutes_ceil = math.ceil(point.eta.minute / interval) * interval
            
            if minutes_ceil >= 60:
                rounded = (point.eta + timedelta(hours=1)).replace(
                    minute=0, second=0, microsecond=0
                )
            else:
                rounded = point.eta.replace(
                    minute=minutes_ceil, second=0, microsecond=0
                )
            
            if rounded not in groups:
                groups[rounded] = []
            groups[rounded].append(point)
        
        return groups
    
    def _build_position_time_map(
        self,
        segments: List[SegmentETA]
    ) -> Dict[Tuple[float, float], datetime]:
        position_times: Dict[Tuple[float, float], datetime] = {}
        
        for seg in segments:
            position_times[seg.from_point] = seg.start_time
            position_times[seg.to_point] = seg.end_time
        
        return position_times
    
    def _find_closest_time(
        self,
        x: float,
        y: float,
        position_times: Dict[Tuple[float, float], datetime],
        fallback: datetime
    ) -> datetime:
        if not position_times:
            return fallback
        
        min_dist = float('inf')
        closest_time = fallback
        
        for pos, time in position_times.items():
            dist = ((pos[0] - x) ** 2 + (pos[1] - y) ** 2) ** 0.5
            if dist < min_dist:
                min_dist = dist
                closest_time = time
        
        return closest_time
    
    def _haversine_distance(
        self,
        lat1: float, lon1: float,
        lat2: float, lon2: float
    ) -> float:
        R = 6371000
        
        lat1_rad = math.radians(lat1)
        lat2_rad = math.radians(lat2)
        delta_lat = math.radians(lat2 - lat1)
        delta_lon = math.radians(lon2 - lon1)
        
        a = (math.sin(delta_lat / 2) ** 2 +
             math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(delta_lon / 2) ** 2)
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        
        return R * c
    
    def _weather_to_dict(self, weather: WeatherAtTime) -> Dict[str, Any]:
        return {
            'wind_speed': weather.wind_speed,
            'wind_direction': weather.wind_direction,
            'wind_gusts': weather.wind_gusts,
            'wave_height': weather.wave_height,
            'wave_direction': weather.wave_direction,
            'wave_period': weather.wave_period,
            'wind_wave_height': weather.wind_wave_height,
            'swell_wave_height': weather.swell_wave_height,
            'current_velocity': weather.current_velocity,
            'current_direction': weather.current_direction,
            'temperature': weather.temperature,
            'humidity': weather.humidity,
            'pressure': weather.pressure,
            'source': weather.source,
            'is_default': weather.is_default,
        }
    
    def _dict_to_weather_at_time(
        self,
        data: Dict[str, Any],
        lat: float,
        lon: float,
        forecast_time: datetime
    ) -> WeatherAtTime:
        return WeatherAtTime(
            lat=lat,
            lon=lon,
            forecast_time=forecast_time,
            wind_speed=data.get('wind_speed', 5.0),
            wind_direction=data.get('wind_direction', 0.0),
            wind_gusts=data.get('wind_gusts', 7.0),
            wave_height=data.get('wave_height', 0.5),
            wave_direction=data.get('wave_direction', 0.0),
            wave_period=data.get('wave_period', 4.0),
            wind_wave_height=data.get('wind_wave_height', 0.3),
            swell_wave_height=data.get('swell_wave_height', 0.2),
            current_velocity=data.get('current_velocity', 0.1),
            current_direction=data.get('current_direction', 0.0),
            temperature=data.get('temperature', 15.0),
            humidity=data.get('humidity', 70.0),
            pressure=data.get('pressure', 1013.0),
            source=data.get('source', 'open-meteo'),
            is_default=data.get('is_default', False),
            fetched_at=datetime.utcnow()
        )
    
    def _default_weather(
        self,
        lat: float,
        lon: float,
        forecast_time: datetime
    ) -> WeatherAtTime:
        return WeatherAtTime(
            lat=lat,
            lon=lon,
            forecast_time=forecast_time,
            wind_speed=5.0,
            wind_direction=0.0,
            wind_gusts=7.0,
            wave_height=0.5,
            wave_direction=0.0,
            wave_period=4.0,
            wind_wave_height=0.3,
            swell_wave_height=0.2,
            current_velocity=0.1,
            current_direction=0.0,
            temperature=15.0,
            humidity=70.0,
            pressure=1013.0,
            source='default',
            is_default=True,
            fetched_at=datetime.utcnow()
        )
    
    def get_stats(self) -> Dict[str, Any]:
        total = self.stats['cache_hits'] + self.stats['api_calls']
        cache_ratio = self.stats['cache_hits'] / total if total > 0 else 0
        
        return {
            **self.stats,
            'cache_hit_ratio': f"{cache_ratio:.1%}",
        }
    
    async def close(self):
        if self.base_service:
            await self.base_service.close()


def weather_at_time_to_heuristics_format(
    weather_map: Dict[int, WeatherAtTime]
) -> Dict[int, Dict[str, Any]]:
    result: Dict[int, Dict[str, Any]] = {}
    
    for idx, weather in weather_map.items():
        result[idx] = weather.to_heuristics_dict()
    
    return result