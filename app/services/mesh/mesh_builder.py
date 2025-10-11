# app/services/mesh/mesh_builder.py
from __future__ import annotations

from pathlib import Path
import json
from typing import Tuple

from sqlalchemy.ext.asyncio import AsyncSession
from shapely.geometry import LineString
from pyproj import CRS

from app.schemas.mesh import CreateRouteAndMeshIn, CreateRouteAndMeshOut
from app.schemas.db_create import (
    RouteCreate, WeatherVectorCreate, RoutePointCreate, MeshedAreaCreate
)
from app.services.db.services import (
    RouteService, RoutePointService, WeatherVectorService, MeshedAreaService
)
from app.services.geodata.corridor import _utm_crs_for, _to_proj
from app.services.geodata.trim_water import water_polygon_in_corridor
from app.services.meshing.triangle_mesher import MeshZones, triangulate_water
from app.services.routing.qucik_path import safe_polyline

from app.services.geodata.bathymetry import (
    WcsRequest,fetch_wcs_geotiff,shallow_mask_from_tif, _bbox_wgs84_from_local_wkt
)

# parametry „wygaszania” brzegu dla mid/far (bezpieczne wartości startowe)
COAST_CLEAR_M = 500.0       # odetnij 0.5 km przy brzegu dla mid/far
COAST_SIMPLIFY_M = 20.0     # uprość granice ~20 m (mniej segmentów PSLG)


async def create_route_and_mesh(session: AsyncSession, payload: CreateRouteAndMeshIn) -> CreateRouteAndMeshOut:
    if len(payload.points) < 2:
        raise ValueError("Provide at least start and finish points")

    route_svc = RouteService(session)
    rpoint_svc = RoutePointService(session)
    wv_svc = WeatherVectorService(session)
    mesh_svc = MeshedAreaService(session)

    # 1) ROUTE
    ctrl_json = json.dumps([[p.lon, p.lat] for p in payload.points])
    route = await route_svc.create_entity(
        model_data=RouteCreate(
            user_id=payload.user_id, yacht_id=payload.yacht_id, control_points=ctrl_json
        ),
        user_id=payload.user_id, yacht_id=payload.yacht_id, control_points=ctrl_json
    )

    # 2) WEATHER (placeholder)
    wv = await wv_svc.create_entity(
        model_data=WeatherVectorCreate(dir=0.0, speed=0.0),
        dir=0.0, speed=0.0
    )

    # 3) ROUTE POINTS
    for i, p in enumerate(payload.points):
        await rpoint_svc.create_entity(
            model_data=RoutePointCreate(
                route_id=route.id, seq_idx=i, x=p.lon, y=p.lat, weather_vector_id=wv.id
            ),
            route_id=route.id, seq_idx=i
        )

    # 4) GEOMETRIA + LOKALNY CRS (UTM)
    line_ll = LineString([(p.lon, p.lat) for p in payload.points])
    wgs84 = CRS.from_epsg(4326)
    lon0, lat0 = line_ll.centroid.x, line_ll.centroid.y
    local_crs = _utm_crs_for(lon0, lat0)
    route_xy = _to_proj(line_ll, wgs84, local_crs)

    # 5) KORYTARZ WOKÓŁ TRASY (na razie bufor z prostej – potrzebny do WCS)
    buffer_m = payload.corridor_nm * 1852.0
    corridor_xy = route_xy.buffer(buffer_m, cap_style=2, join_style=2)

    # 6) WODA = KORYTARZ - LĄD (OSM)
    water_xy = water_polygon_in_corridor(corridor_xy, local_crs, Path("data"))

    # 6.1) BATYMETRIA -> mielizny (no-go)
    DRAFT_M = 2.2  # TODO: przenieść do payloadu
    CLEARANCE_M = 0.5
    THRESHOLD = DRAFT_M + CLEARANCE_M

    bbox_wgs = _bbox_wgs84_from_local_wkt(water_xy.wkt, local_crs.to_epsg() or 4326, pad_m=500.0)
    cache = Path("data/geodata/bathy/cache")
    tif_path = fetch_wcs_geotiff(WcsRequest(bbox_wgs84=bbox_wgs, res_deg=0.001), cache / f"bathy_{route.id}.tif")
    no_go = shallow_mask_from_tif(tif_path, local_crs.to_epsg() or 4326, THRESHOLD)
    if no_go and not no_go.is_empty:
        water_xy = water_xy.difference(no_go)

    # 6.2) Jeśli linia prosta przecina „no-go” (albo wyszła poza 'water_xy'), wyznacz bezpieczną łamaną
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
        # nawigowalny poligon to 'water_xy' (już „oczyszczony” z mielizn)
        safe_line = safe_polyline(water_xy, start_xy, end_xy, coarse_area=250000.0, fairway=None)
        if safe_line is not None:
            route_xy = safe_line  # <- zamieniamy prostą na „bezpieczną łamaną”
            # przelicz korytarz pod nową trasę
            corridor_xy = route_xy.buffer(buffer_m, cap_style=2, join_style=2)

    # 7) MESH (jak wcześniej: gęsto przy trasie, wyciszony brzeg)
    zones = MeshZones(
        radii_m=[payload.ring1_m, payload.ring2_m, payload.ring3_m],
        max_area_m2=[payload.area1, payload.area2, payload.area3],
    )
    mesh = triangulate_water(
        water_xy, route_xy, zones,
        coast_clear_m=COAST_CLEAR_M,
        coast_simplify_m=COAST_SIMPLIFY_M
    )

    nodes = mesh.get("vertices", [])
    tris = mesh.get("triangles", [])
    if nodes is None or tris is None or len(nodes) == 0:
        raise RuntimeError("Triangulation failed or produced empty mesh")

    # 8) ZAPIS MESH
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

    return CreateRouteAndMeshOut(
        route_id=route.id,
        meshed_area_id=meshed.id,
        crs_epsg=local_crs.to_epsg() or 0
    )
