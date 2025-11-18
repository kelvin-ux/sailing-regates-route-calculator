from __future__ import annotations

import numpy as np
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Tuple
from typing import Optional
from typing import List
from typing import Dict
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from pyproj import CRS

from shapely.geometry import Point
from shapely.geometry import LineString
from sklearn.cluster import KMeans
from scipy.spatial import KDTree

from app.schemas.mesh import CreateRouteAndMeshIn
from app.schemas.db_create import RouteCreate
from app.schemas.db_create import RoutePointCreate
from app.schemas.db_create import MeshedAreaCreate
from app.schemas.WeatherMeshConfig import WeatherMeshConfig

from app.models.models import RoutePointType

from app.services.db.services import MeshedAreaService, YachtService
from app.services.db.services import RoutePointService
from app.services.db.services import RouteService
from app.services.geodata.corridor import _to_proj
from app.services.geodata.corridor import _utm_crs_for
from app.services.geodata.trim_water import water_polygon_in_corridor
from app.services.meshing.triangle_mesher import triangulate_water
from app.services.meshing.triangle_mesher import MeshZones
from app.services.routing.qucik_path import safe_polyline
from app.services.geodata.bathymetry import WcsRequest
from app.services.geodata.bathymetry import shallow_mask_from_tif
from app.services.geodata.bathymetry import _bbox_wgs84_from_local_wkt
from app.services.geodata.bathymetry import fetch_wcs_geotiff
from app.services.mesh.zones import ZonalWeatherPointSelector



COAST_CLEAR_M = 500.0
COAST_SIMPLY = 20.0
WEATHER_CACHE_TTL = 3600
DRAFT_M = 2.2
CLEARANCE_M = 0.5
THRESHOLD = DRAFT_M + CLEARANCE_M



@dataclass
class DualMeshResult:
    navi_mesh: Dict[str, Any]
    weather_points: List[Tuple[float, float]]
    weather_to_nav_mapping: Dict[int, List[int]]


class WeatherPointSelector:
    def __init__(self, config: WeatherMeshConfig):
        self.config = config

    def select_points(self, navigation_vertices: np.ndarray, route_line: LineString, water_poly) -> List[Tuple[float, float]]:
        selected = []

        route_points = self._sample_along_route(route_line, self.config.priority_route_points)
        selected.extend(route_points)

        remaining = self.config.max_points - len(route_points)

        if remaining > 0:
            if self.config.cluster_method == "kmeans":
                additional = self._select_by_cluster(navigation_vertices, remaining, exclude_near=route_points)
            else:
                additional = self._select_by_grid(water_poly, remaining, self.config.grid_spacing_m)
            selected.extend(additional)

        return selected[:self.config.max_points]

    def _sample_along_route(self, route: LineString, n: int) -> List[Tuple[float, float]]:
        if n <= 0:
            return []
        total_len = route.length
        pts: List[Tuple[float, float]] = []
        for i in range(n):
            dist = (i / (n - 1)) * total_len if n > 1 else 0
            p = route.interpolate(dist)
            pts.append((p.x, p.y))
        return pts

    def _select_by_cluster(self, vertices: np.ndarray, n: int, exclude_near: List[Tuple[float, float]] = None) -> List[Tuple[float, float]]:
        if len(vertices) < n:
            return [(v[0], v[1]) for v in vertices]

        kmeans = KMeans(n_clusters=n, random_state=42, n_init=10)
        kmeans.fit(vertices)

        centers = kmeans.cluster_centers_

        if exclude_near:
            exclude_tree = KDTree(exclude_near)
            filtered = []
            for center in centers:
                dist, _ = exclude_tree.query(center, k=1)
                if dist > 1000:
                    filtered.append((center[0], center[1]))
            return filtered

        return [(c[0], c[1]) for c in centers]

    def _select_by_grid(self,
                        water_polygon,
                        max_points: int,
                        grid_spacing: float) -> List[Tuple[float, float]]:
        """Wybór przez regularną siatkę"""
        bounds = water_polygon.bounds  # (minx, miny, maxx, maxy)

        width = bounds[2] - bounds[0]
        height = bounds[3] - bounds[1]

        nx = max(2, int(width / grid_spacing))
        ny = max(2, int(height / grid_spacing))

        while nx * ny > max_points:
            nx = max(2, nx - 1)
            ny = max(2, ny - 1)

        points = []
        for i in range(nx):
            for j in range(ny):
                x = bounds[0] + (i + 0.5) * (width / nx)
                y = bounds[1] + (j + 0.5) * (height / ny)
                point = Point(x, y)

                if water_polygon.contains(point):
                    points.append((x, y))

        return points[:max_points]


class WeatherDataInterpolator:
    @staticmethod
    def create_mapping(weather_points: List[Tuple[float, float]], nav_vertices: np.ndarray) -> Dict[int, List[int]]:
        """
        creates mapping: weather_point_idx -> nav vertex | kazdy punkt dostaje przypisany weather point
        """
        weather_tree = KDTree(weather_points)
        mapping = {i: [] for i in range(len(weather_points))}
        for nav_idx, nav_vertex in enumerate(nav_vertices):
            _, weather_idx = weather_tree.query(nav_vertex, k=1)
            mapping[weather_idx].append(nav_idx)

        return mapping

    @staticmethod
    def interpolate_weather_data(weather_data: Dict[int, Dict], mapping: Dict[int, List[int]], nav_vertices: np.ndarray) -> np.ndarray:
        """
        Interpoluje dane pogodowe na wszystkie punkty nawigacyjne
        Zwraca tablice z danymi pogodowymi dla każdego punktu nawigacyjnego
        """
        nav_weather = np.zeros((len(nav_vertices), 2))  # [wind_speed, wind_dir]

        for weather_idx, nav_indices in mapping.items():
            if weather_idx in weather_data:
                wind_speed = weather_data[weather_idx].get('wind_speed', 0)
                wind_dir = weather_data[weather_idx].get('wind_dir', 0)

                for nav_idx in nav_indices:
                    nav_weather[nav_idx] = [wind_speed, wind_dir]

        return nav_weather


async def create_route_and_mesh(session: AsyncSession, payload: CreateRouteAndMeshIn, weather_config: Optional[WeatherMeshConfig] = None) -> Dict[str, Any]:
    """
    Zwraca dict z route_id, mesh_id, weather_points, navigation_mesh
    """
    if not weather_config:
        weather_config = WeatherMeshConfig()

    if len(payload.points) < 2:
        raise ValueError("Provide at least start and finish points")

    route_svc = RouteService(session)
    rpoint_svc = RoutePointService(session)
    mesh_svc = MeshedAreaService(session)
    yacht_svc = YachtService(session)

    if await yacht_svc.get_entity_by_id(payload.yacht_id) is None:
        raise ValueError("Provide valid yacht id")

    ctrl_json = json.dumps([[p.lon, p.lat] for p in payload.points])
    route = await route_svc.create_entity(
        model_data=RouteCreate(
            user_id=payload.user_id,
            yacht_id=payload.yacht_id,
            control_points=ctrl_json
        )
    )
    last_idx = len(payload.points) - 1
    for i, p in enumerate(payload.points):
        if i == 0:
            pt = RoutePointType.START
        elif i == last_idx:
            pt = RoutePointType.STOP
        else:
            pt = RoutePointType.CONTROL

        await rpoint_svc.create_entity(
            model_data=RoutePointCreate(
                route_id=route.id,
                point_type=pt,
                seq_idx=i,
                x=p.lon,
                y=p.lat
            )
        )

    line_ll = LineString([(p.lon, p.lat) for p in payload.points])
    wgs84 = CRS.from_epsg(4326)
    lon0, lat0 = line_ll.centroid.x, line_ll.centroid.y
    local_crs = _utm_crs_for(lon0, lat0)
    route_xy = _to_proj(line_ll, wgs84, local_crs)

    buffer_m = payload.corridor_nm * 1852.0
    corridor_xy = route_xy.buffer(buffer_m, cap_style=2, join_style=2)
    water_xy = water_polygon_in_corridor(corridor_xy, local_crs, Path("data"))

    bbox_wgs = _bbox_wgs84_from_local_wkt(water_xy.wkt, local_crs.to_epsg() or 4326, pad_m=500.0)
    cache = Path("data/geodata/bathy/cache")
    cache.mkdir(parents=True, exist_ok=True)
    tif_path = fetch_wcs_geotiff(
        WcsRequest(bbox_wgs84=bbox_wgs, res_deg=0.001),
        cache / f"bathy_{route.id}.tif"
    )
    no_go = shallow_mask_from_tif(tif_path, local_crs.to_epsg() or 4326, THRESHOLD)

    if no_go and not no_go.is_empty:
        water_xy = water_xy.difference(no_go)

    needs_detour = False
    try:
        if no_go and not no_go.is_empty and route_xy.intersects(no_go):
            needs_detour = True
        if not route_xy.within(water_xy):
            needs_detour = True
    except Exception:
        pass

    if needs_detour:
        start_xy = (route_xy.coords[0][0], route_xy.coords[0][1])
        end_xy = (route_xy.coords[-1][0], route_xy.coords[-1][1])
        safe_line = safe_polyline(water_xy, start_xy, end_xy, coarse_area=250000.0, fairway=None)
        if safe_line is not None:
            route_xy = safe_line
            corridor_xy = route_xy.buffer(buffer_m, cap_style=2, join_style=2)

    route_ll = _to_proj(route_xy, local_crs, CRS.from_epsg(4326))
    coords_ll = list(route_ll.coords)

    base = len(payload.points)
    seq = base

    for j in range(1, max(0, len(coords_ll) - 1)):
        lon, lat = coords_ll[j][0], coords_ll[j][1]
        await rpoint_svc.create_entity(
            model_data=RoutePointCreate(
                route_id=route.id,
                point_type=RoutePointType.NAVIGATION,
                seq_idx=seq,
                x=lon,
                y=lat
            )
        )
        seq += 1


    STEP_M = 300.0
    L = float(route_xy.length)

    d = STEP_M
    while d < L - STEP_M * 0.5:
        pt_xy = route_xy.interpolate(d)
        pt_ll = _to_proj(Point(pt_xy.x, pt_xy.y),
                         local_crs, CRS.from_epsg(4326))
        await rpoint_svc.create_entity(
            model_data=RoutePointCreate(
                route_id=route.id,
                point_type=RoutePointType.NAVIGATION,
                seq_idx=seq,
                x=float(pt_ll.x),  # lon
                y=float(pt_ll.y)  # lat
            )
        )
        seq += 1
        d += STEP_M

    nav_zones = MeshZones(
        radii_m=[payload.ring1_m, payload.ring2_m, payload.ring3_m],
        max_area_m2=[payload.area1, payload.area2, payload.area3],
    )

    nav_mesh = triangulate_water(
        water_xy, route_xy, nav_zones,
        coast_clear_m=COAST_CLEAR_M,
        coast_simplify_m=COAST_SIMPLY
    )

    nav_vertices = nav_mesh.get("vertices", [])
    nav_triangles = nav_mesh.get("triangles", [])

    if nav_vertices is None or nav_triangles is None or len(nav_vertices) == 0:
        raise RuntimeError("Navigation mesh triangulation failed")

    selector = ZonalWeatherPointSelector(weather_config)
    weather_points = selector.select_points(
        nav_vertices,
        route_xy,
        water_xy
    )

    weather_nav_mapping = WeatherDataInterpolator.create_mapping(
        weather_points,
        nav_vertices
    )

    mesh_data = {
        "navigation": {
            "vertices": nav_vertices.tolist() if hasattr(nav_vertices, "tolist") else nav_vertices,
            "triangles": nav_triangles.tolist() if hasattr(nav_triangles, "tolist") else nav_triangles
        },
        "weather": {
            "points": weather_points,
            "mapping": {str(k): v for k, v in weather_nav_mapping.items()}
        }
    }

    weather_points_metadata = {
        "points": [
            {"idx": idx, "x": p[0], "y": p[1]}
            for idx, p in enumerate(weather_points)
        ],
        "mapping": mesh_data["weather"]["mapping"]
    }

    meshed = await mesh_svc.create_entity(
        model_data=MeshedAreaCreate(
            route_id=route.id,
            crs_epsg=(local_crs.to_epsg() or 0),
            nodes_json=json.dumps(mesh_data["navigation"]["vertices"]),
            triangles_json=json.dumps(mesh_data["navigation"]["triangles"]),
            water_wkt=water_xy.wkt,
            route_wkt=route_xy.wkt,
            weather_points_json=json.dumps(weather_points_metadata)
        )
    )

    return {
        "route_id": route.id,
        "meshed_area_id": meshed.id,
        "crs_epsg": local_crs.to_epsg() or 0,
        "navigation_vertices_count": len(nav_vertices),
        "weather_points_count": len(weather_points),
        "weather_points": weather_points
    }