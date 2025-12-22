from __future__ import annotations
from pydantic import BaseModel, Field, UUID4, field_validator
from typing import List, Optional
from datetime import datetime


class ControlPointIn(BaseModel):
    lat: float
    lon: float
    timestamp: Optional[datetime] = None
    name: Optional[str] = None

    @field_validator('timestamp', mode='before')
    @classmethod
    def parse_timestamp(cls, v):
        if v is None:
            return None
        if isinstance(v, datetime):
            return v
        if isinstance(v, str):
            try:
                return datetime.fromisoformat(v.replace('Z', '+00:00'))
            except ValueError:
                return None
        return None


class CreateRouteAndMeshIn(BaseModel):
    user_id: UUID4
    yacht_id: UUID4
    points: List[ControlPointIn] = Field(..., min_length=2, description="start, ...kontrolne..., meta")
    corridor_nm: float = 3.0
    ring1_m: float = 500.0
    ring2_m: float = 1500.0
    ring3_m: float = 3000.0
    area1: float = 3000.0
    area2: float = 15000.0
    area3: float = 60000.0
    shoreline_avoid_m: float = 300.0
    enable_weather_optimization: bool = True
    max_weather_points: int = 40
    weather_grid_km: float = 5.0
    weather_clustering_method: str = "kmeans"


class CreateRouteAndMeshOut(BaseModel):
    route_id: UUID4
    meshed_area_id: UUID4
    crs_epsg: int