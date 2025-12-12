from __future__ import annotations

from typing import Tuple
from dataclasses import dataclass

@dataclass
class OptimizedSegment:
    from_point: Tuple[float, float]  # (x, y)
    to_point: Tuple[float, float]
    from_point_wgs84: Tuple[float, float]  # (lon, lat)
    to_point_wgs84: Tuple[float, float]

    avg_bearing: float
    avg_boat_speed_knots: float
    avg_wind_speed_knots: float
    avg_wind_direction: float
    avg_wave_height_m: float
    avg_twa: float

    total_distance_nm: float
    total_time_hours: float

    raw_segments_count: int
    predominant_point_of_sail: str

    has_tack: bool = False
    has_jibe: bool = False