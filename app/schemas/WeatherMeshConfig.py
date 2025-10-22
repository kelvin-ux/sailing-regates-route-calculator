from dataclasses import dataclass

MAX_WEATHER_POINTS = 50
WEATHER_GRID_KM = 5.0
WEATHER_GRID_M = 5000.0

@dataclass
class WeatherMeshConfig:
    max_points: int = MAX_WEATHER_POINTS
    grid_spacing_m: float = WEATHER_GRID_M
    priority_route_points: int = 20
    cluster_method: str = "kmeans"
    near_zone_m: float = 500.0
    mid_zone_m: float = 1500.0
    fat_zone_m: float = 3000.0
    rdr: float = 0.3 # amount of points in near zone