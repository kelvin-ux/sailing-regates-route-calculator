from pydantic import BaseModel
from pydantic import UUID4
from typing import Optional
from datetime import datetime
from enum import Enum


class RoutePointType(str, Enum):
    NAVIGATION = "navigation"
    WEATHER = "weather"
    CONTROL = "control"


class RouteCreate(BaseModel):
    user_id: UUID4
    yacht_id: UUID4
    control_points: Optional[str] = None
    description: Optional[str] = None


class RoutePointCreate(BaseModel):
    route_id: UUID4
    meshed_area_id: Optional[UUID4] = None
    point_type: RoutePointType = RoutePointType.NAVIGATION
    seq_idx: int
    x: float  # lon
    y: float  # lat


class WeatherForecastCreate(BaseModel):
    route_point_id: UUID4
    forecast_timestamp: datetime

    temperature: Optional[float] = None
    humidity: Optional[float] = None
    pressure: Optional[float] = None
    wind_speed: float
    wind_direction: float
    wind_gusts: Optional[float] = None
    wave_height: Optional[float] = None
    wave_direction: Optional[float] = None
    wave_period: Optional[float] = None
    wind_wave_height: Optional[float] = None
    swell_wave_height: Optional[float] = None
    current_velocity: Optional[float] = None
    current_direction: Optional[float] = None
    source: Optional[str] = "open-meteo"
    is_default: bool = False


class MeshedAreaCreate(BaseModel):
    route_id: UUID4
    crs_epsg: int
    nodes_json: str
    triangles_json: str
    water_wkt: str
    route_wkt: str
    weather_points_json: Optional[str] = None