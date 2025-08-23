from __future__ import annotations
from pathlib import Path
import json
from typing import Tuple
from shapely.geometry import LineString
from pyproj import CRS

from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.mesh import CreateRouteAndMeshIn, CreateRouteAndMeshOut
from app.services.db.services import (
    RouteService, RoutePointService, WeatherVectorService, MeshedAreaService
)
from app.schemas.db_create import (
    RouteCreate, WeatherVectorCreate, RoutePointCreate, MeshedAreaCreate
)
from app.services.geodata.corridor import _utm_crs_for, _to_proj
from app.services.geodata.trim_water import water_polygon_in_corridor
from app.services.meshing.triangle_mesher import MeshZones, triangulate_water

async def create_route_and_mesh(session: AsyncSession, payload: CreateRouteAndMeshIn) -> CreateRouteAndMeshOut:
    """
    Tworzy Route + RoutePoints + MeshedArea.
    """
    if len(payload.points) < 2:
        raise ValueError("Provide at least start and finish points")

    route_svc = RouteService(session)
    rpoint_svc = RoutePointService(session)
    wv_svc = WeatherVectorService(session)
    mesh_svc = MeshedAreaService(session)

    ctrl_json = json.dumps([[p.lon, p.lat] for p in payload.points])
    route = await route_svc.create_entity(
        model_data=RouteCreate(user_id=payload.user_id, yacht_id=payload.yacht_id, control_points=ctrl_json),
        user_id=payload.user_id, yacht_id=payload.yacht_id, control_points=ctrl_json
    )

    wv = await wv_svc.create_entity(
        model_data=WeatherVectorCreate(dir=0.0, speed=0.0),
        dir=0.0, speed=0.0
    )

    for i, p in enumerate(payload.points):
        await rpoint_svc.create_entity(
            model_data=RoutePointCreate(
                route_id=route.id, seq_idx=i, x=p.lon, y=p.lat, weather_vector_id=wv.id
            ),
            route_id=route.id, seq_idx=i
        )

    line_ll = LineString([(p.lon, p.lat) for p in payload.points])
    wgs84 = CRS.from_epsg(4326)
    lon0, lat0 = line_ll.centroid.x, line_ll.centroid.y
    local_crs = _utm_crs_for(lon0, lat0)
    route_xy = _to_proj(line_ll, wgs84, local_crs)

    buffer_m = payload.corridor_nm * 1852.0
    corridor_xy = route_xy.buffer(buffer_m, cap_style=2, join_style=2)
    water_xy = water_polygon_in_corridor(corridor_xy, local_crs, Path("data"))

    zones = MeshZones(
        radii_m=[payload.ring1_m, payload.ring2_m, payload.ring3_m],
        max_area_m2=[payload.area1, payload.area2, payload.area3],
    )
    mesh = triangulate_water(water_xy, route_xy, zones)
    nodes = mesh.get("vertices", [])
    tris = mesh.get("triangles", [])
    if nodes is None or tris is None or len(nodes) == 0:
        raise RuntimeError("Triangulation failed or produced empty mesh")

    meshed = await mesh_svc.create_entity(
        model_data=MeshedAreaCreate(
            route_id=route.id,
            crs_epsg=(local_crs.to_epsg() or 0),
            nodes_json=json.dumps(nodes.tolist() if hasattr(nodes, "tolist") else nodes),
            triangles_json=json.dumps(tris.tolist() if hasattr(tris, "tolist") else tris),
            water_wkt=water_xy.wkt,
            route_wkt=route_xy.wkt,
        ),
        route_id=route.id, route_wkt=route_xy.wkt
    )

    return CreateRouteAndMeshOut(route_id=route.id, meshed_area_id=meshed.id, crs_epsg=local_crs.to_epsg() or 0)
