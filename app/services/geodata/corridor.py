from __future__ import annotations
from dataclasses import dataclass
from typing import Tuple

import geopandas as gpd
from shapely.geometry import LineString
from shapely.geometry import Polygon
from pyproj import CRS

NM_TO_M : float = 1852.00

@dataclass
class PointLL:
    lat: float
    lon: float

def _utm_crs_for(lon: float, lat: float) -> CRS:
    zone = int((lon + 180) // 6) + 1
    epsg = 32600 + zone if lat >= 0 else 32700 + zone
    return CRS.from_epsg(epsg)

def _to_proj(geometry, crs_from: CRS, crs_to: CRS):
    return gpd.GeoSeries([geometry], crs = crs_from).to_crs(crs_to).iloc[0]


def build_corridor(a: PointLL, c: PointLL, b: PointLL, width_nm: float = 3.0) -> Tuple[Polygon, CRS]:
    wgs84 = CRS.from_epsg(4326)
    route_ll = LineString([(a.lon, a.lat), (c.lon, c.lat), (b.lon, b.lat)])

    lon0, lat0 = route_ll.centroid.x, route_ll.centroid.y
    local_crs = _utm_crs_for(lon0, lat0)

    route_xy = _to_proj(route_ll, wgs84, local_crs)
    buffer_m = width_nm * NM_TO_M
    corridor_xy: Polygon = route_xy.buffer(buffer_m, cap_style=2, join_style=2)  # cap=flat, join=miter
    return corridor_xy, local_crs

def corridor_bbox_wgs84(corridor_xy: Polygon, local_crs: CRS, pad_m: float = 5000) -> Tuple[float,float,float,float]:
    wgs84 = CRS.from_epsg(4326)
    expanded = corridor_xy.buffer(pad_m)
    poly_wgs = _to_proj(expanded, local_crs, wgs84)
    minx, miny, maxx, maxy = poly_wgs.bounds
    return (miny, minx, maxy, maxx)