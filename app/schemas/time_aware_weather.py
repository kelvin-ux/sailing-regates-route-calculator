from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any
from enum import Enum
from uuid import UUID
import math

class ETAConfidence(str, Enum):
    HIGH = "high"          # < 1h od startu, mała niepewność
    MEDIUM = "medium"      # 1-6h od startu
    LOW = "low"            # > 6h od startu, duża niepewność
    ESTIMATED = "estimated"  # Wstępna estymacja przed pierwszym przeliczeniem


@dataclass
class TimeAwareWeatherPoint:
    idx: int
    x: float
    y: float
    lon: float
    lat: float
    eta: datetime
    eta_confidence: ETAConfidence = ETAConfidence.ESTIMATED
    elapsed_seconds: float = 0.0
    distance_from_start_m: float = 0.0
    route_point_id: Optional[UUID] = None
    weather_data: Optional[Dict[str, Any]] = None
    weather_fetched_at: Optional[datetime] = None
    
    def cache_key(self, grid_size: float = 0.01, time_round_minutes: int = 15) -> str:
        grid_lat = round(self.lat / grid_size) * grid_size
        grid_lon = round(self.lon / grid_size) * grid_size
        
        minutes_ceil = math.ceil(self.eta.minute / time_round_minutes) * time_round_minutes
        
        if minutes_ceil >= 60:
            rounded_eta = (self.eta + timedelta(hours=1)).replace(
                minute=0, second=0, microsecond=0
            )
        else:
            rounded_eta = self.eta.replace(
                minute=minutes_ceil, second=0, microsecond=0
            )
        
        return f"taw:{grid_lat:.2f}:{grid_lon:.2f}:{rounded_eta.isoformat()}"
    
    def update_eta(self, new_eta: datetime, confidence: ETAConfidence = None):
        self.eta = new_eta
        if confidence:
            self.eta_confidence = confidence
        else:
            hours_ahead = (new_eta - datetime.utcnow()).total_seconds() / 3600
            if hours_ahead < 1:
                self.eta_confidence = ETAConfidence.HIGH
            elif hours_ahead < 6:
                self.eta_confidence = ETAConfidence.MEDIUM
            else:
                self.eta_confidence = ETAConfidence.LOW


@dataclass
class SegmentETA:
    from_idx: int
    to_idx: int
    from_point: Tuple[float, float]
    to_point: Tuple[float, float]
    from_point_wgs84: Tuple[float, float]  # (lon, lat)
    to_point_wgs84: Tuple[float, float]    # (lon, lat)
    start_time: datetime      # Kiedy jacht zaczyna ten segment
    end_time: datetime        # Kiedy jacht kończy ten segment
    duration_seconds: float   # Czas przepłynięcia
    distance_m: float
    distance_nm: float
    boat_speed_ms: float
    boat_speed_knots: float
    weather_at_start: Optional[Dict[str, Any]] = None
    weather_at_end: Optional[Dict[str, Any]] = None
    bearing: float = 0.0
    twa: float = 0.0                    # True Wind Angle
    wind_speed_knots: float = 0.0
    wind_direction: float = 0.0
    wave_height_m: float = 0.0
    requires_tack: bool = False
    requires_jibe: bool = False
    
    @property
    def mid_time(self) -> datetime:
        return self.start_time + timedelta(seconds=self.duration_seconds / 2)


@dataclass
class RouteETAProfile:
    meshed_area_id: UUID
    route_id: UUID
    departure_time: datetime
    weather_points: List[TimeAwareWeatherPoint] = field(default_factory=list)
    segments: List[SegmentETA] = field(default_factory=list)
    total_distance_nm: float = 0.0
    total_time_hours: float = 0.0
    estimated_arrival: Optional[datetime] = None
    iteration: int = 0                    # Numer iteracji (0 = wstępna estymacja)
    is_converged: bool = False            # Czy trasa się ustabilizowała
    max_eta_change_seconds: float = 0.0   # Maksymalna zmiana ETA między iteracjami
    
    def get_weather_point_by_idx(self, idx: int) -> Optional[TimeAwareWeatherPoint]:
        for wp in self.weather_points:
            if wp.idx == idx:
                return wp
        return None
    
    def get_points_for_time_range(
        self, 
        start: datetime, 
        end: datetime
    ) -> List[TimeAwareWeatherPoint]:
        return [
            wp for wp in self.weather_points 
            if start <= wp.eta <= end
        ]
    
    def group_points_by_quarter(self, interval_minutes: int = 15) -> Dict[datetime, List[TimeAwareWeatherPoint]]:
        groups: Dict[datetime, List[TimeAwareWeatherPoint]] = {}
        
        for wp in self.weather_points:
            minutes_ceil = math.ceil(wp.eta.minute / interval_minutes) * interval_minutes
            
            if minutes_ceil >= 60:
                quarter_key = (wp.eta + timedelta(hours=1)).replace(
                    minute=0, second=0, microsecond=0
                )
            else:
                quarter_key = wp.eta.replace(
                    minute=minutes_ceil, second=0, microsecond=0
                )
            
            if quarter_key not in groups:
                groups[quarter_key] = []
            groups[quarter_key].append(wp)
        
        return groups
    
    def group_points_by_hour(self) -> Dict[datetime, List[TimeAwareWeatherPoint]]:
        return self.group_points_by_quarter(interval_minutes=60)
    
    def update_from_segments(self, segments: List[SegmentETA]):
        self.segments = segments
        
        if not segments:
            return
        self.total_distance_nm = sum(s.distance_nm for s in segments)
        self.total_time_hours = sum(s.duration_seconds for s in segments) / 3600.0
        self.estimated_arrival = segments[-1].end_time
        self._update_weather_points_eta()
    
    def _update_weather_points_eta(self):
        if not self.segments:
            return
        
        position_times: Dict[Tuple[float, float], datetime] = {}
        
        for seg in self.segments:
            position_times[seg.from_point] = seg.start_time
            position_times[seg.to_point] = seg.end_time
        
        for wp in self.weather_points:
            wp_pos = (wp.x, wp.y)
            min_dist = float('inf')
            closest_time = self.departure_time
            
            for pos, time in position_times.items():
                dist = ((pos[0] - wp.x) ** 2 + (pos[1] - wp.y) ** 2) ** 0.5
                if dist < min_dist:
                    min_dist = dist
                    closest_time = time
            
            old_eta = wp.eta
            wp.update_eta(closest_time)
            if old_eta:
                change = abs((wp.eta - old_eta).total_seconds())
                self.max_eta_change_seconds = max(self.max_eta_change_seconds, change)


@dataclass
class TimeAwareWeatherRequest:
    lat: float
    lon: float
    forecast_time: datetime
    point_idx: int
    request_id: str = ""
    priority: int = 0
    is_route_point: bool = False
    
    def __post_init__(self):
        if not self.request_id:
            self.request_id = f"{self.lat:.4f}:{self.lon:.4f}:{self.forecast_time.isoformat()}"
    
    def cache_key(self, grid_size: float = 0.01, time_round_minutes: int = 15) -> str:
        
        
        grid_lat = round(self.lat / grid_size) * grid_size
        grid_lon = round(self.lon / grid_size) * grid_size
        
        minutes_ceil = math.ceil(self.forecast_time.minute / time_round_minutes) * time_round_minutes
        
        if minutes_ceil >= 60:
            rounded_time = (self.forecast_time + timedelta(hours=1)).replace(
                minute=0, second=0, microsecond=0
            )
        else:
            rounded_time = self.forecast_time.replace(
                minute=minutes_ceil, second=0, microsecond=0
            )
        
        return f"taw_req:{grid_lat:.2f}:{grid_lon:.2f}:{rounded_time.isoformat()}"


@dataclass
class WeatherTimelineEntry:
    point_idx: int
    forecast_for: datetime       # Na jaki czas jest prognoza
    fetched_at: datetime         # Kiedy pobrano
    wind_speed: float
    wind_direction: float
    wave_height: float
    wave_direction: float
    wave_period: float
    
    source: str = "open-meteo"
    is_interpolated: bool = False


@dataclass 
class ETACalculationConfig:
    max_iterations: int = 3
    convergence_threshold_seconds: float = 300.0
    time_round_minutes: int = 15
    coord_grid_size: float = 0.01  # ~1km
    use_initial_speed_estimate: bool = True
    initial_speed_knots: float = 6.0
    forecast_buffer_minutes: int = 30
    batch_weather_requests: bool = True
    batch_time_window_minutes: int = 15 ## !!!


@dataclass
class IterativeRouteResult:
    profile: RouteETAProfile
    iterations: List[Dict[str, Any]] = field(default_factory=list)
    total_weather_requests: int = 0
    cache_hits: int = 0
    api_calls: int = 0
    converged: bool = False
    convergence_iteration: int = 0
    calculation_started: Optional[datetime] = None
    calculation_finished: Optional[datetime] = None
    
    @property
    def calculation_time_seconds(self) -> float:
        if self.calculation_started and self.calculation_finished:
            return (self.calculation_finished - self.calculation_started).total_seconds()
        return 0.0
    
    def add_iteration(
        self,
        iteration_num: int,
        max_eta_change: float,
        weather_requests: int,
        route_time_hours: float
    ):
        self.iterations.append({
            "iteration": iteration_num,
            "max_eta_change_seconds": max_eta_change,
            "weather_requests": weather_requests,
            "route_time_hours": route_time_hours,
            "timestamp": datetime.utcnow().isoformat()
        })