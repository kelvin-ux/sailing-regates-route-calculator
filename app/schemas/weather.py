from __future__ import annotations

from pydantic import BaseModel
from pydantic import UUID4
from typing import List
from dataclasses import dataclass
from dataclasses import  field
from datetime import datetime


class WeatherPointResponse(BaseModel):
    index: int
    lat: float
    lon: float
    wind_speed: float
    wind_direction: float
    wind_gusts: float
    wave_height: float
    wave_direction: float
    wave_period: float
    wind_wave_height: float
    swell_wave_height: float
    current_velocity: float
    current_direction: float
    temperature: float
    humidity: float
    pressure: float
    timestamp: str
    is_default: bool = False


class WeatherBatchResponse(BaseModel):
    meshed_area_id: UUID4
    total_points: int
    successful: int
    failed: int
    cache_hits: int
    api_calls: int
    points: List[WeatherPointResponse]


class WeatherDataResponse(BaseModel):
    meshed_area_id: str
    has_data: bool
    point_count: int
    data: dict


@dataclass
class MarineWeatherRequest:
    lat: float
    lon: float
    request_id: str
    priority: int = 0  # 0=normal, 1=high priority
    timestamp: datetime = field(default_factory=datetime.now)

    def cache_key(self, grid_size: float = 0.01) -> str:
        grid_lat = round(self.lat / grid_size) * grid_size
        grid_lon = round(self.lon / grid_size) * grid_size
        return f"marine_weather:{grid_lat:.2f}:{grid_lon:.2f}"