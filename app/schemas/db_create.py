from pydantic import BaseModel, UUID4
from typing import Optional

class RouteCreate(BaseModel):
    user_id: UUID4
    yacht_id: UUID4
    control_points: Optional[str] = None
    description: Optional[str] = None

class WeatherVectorCreate(BaseModel):
    dir: float
    speed: float

class RoutePointCreate(BaseModel):
    route_id: UUID4
    seq_idx: int
    x: float            # lon
    y: float            # lat
    weather_vector_id: UUID4

class MeshedAreaCreate(BaseModel):
    route_id: UUID4
    crs_epsg: int
    nodes_json: str
    triangles_json: str
    water_wkt: str
    route_wkt: str
