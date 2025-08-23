from __future__ import annotations
from pydantic import BaseModel, Field, UUID4
from typing import List, Optional

class ControlPointIn(BaseModel):
    lat: float
    lon: float
    timestamp: Optional[str] = None

class CreateRouteAndMeshIn(BaseModel):
    user_id: UUID4
    yacht_id: UUID4
    points: List[ControlPointIn] = Field(..., min_items=2, description="start, ...kontrolne..., meta")
    corridor_nm: float = 3.0
    ring1_m: float = 500.0
    ring2_m: float = 1500.0
    ring3_m: float = 3000.0
    area1: float = 3000.0
    area2: float = 15000.0
    area3: float = 60000.0

class CreateRouteAndMeshOut(BaseModel):
    route_id: UUID4
    meshed_area_id: UUID4
    crs_epsg: int
