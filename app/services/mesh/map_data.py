from __future__ import annotations

import json
import numpy as np

from typing import Dict
from typing import Any
from typing import List
from typing import Tuple

from sqlalchemy.ext.asyncio import AsyncSession
from shapely import wkt
from shapely.ops import transform as shp_transform
from pyproj import Transformer

from app.services.db.services import MeshedAreaService
from app.services.db.services import RoutePointService
from app.services.db.services import RouteService

async def build_map_geojson(session: AsyncSession, meshed_area_id: str) -> Dict[str, Any]:
    mesh_svc = MeshedAreaService(session)
    rpoint_svc = RoutePointService(session)
    route_svc = RouteService(session)

    meshed = await mesh_svc.get_entity_by_id(meshed_area_id, allow_none=False)

    nodes = []
    tris = []
    if getattr(meshed, "nodes_json", None):
        nodes = np.asarray(json.loads(meshed.nodes_json))
    if getattr(meshed, "triangles_json", None):
        tris = np.asarray(json.loads(meshed.triangles_json), dtype=int)

    water = wkt.loads(meshed.water_wkt) if getattr(meshed, "water_wkt", None) else None
    route = wkt.loads(meshed.route_wkt) if getattr(meshed, "route_wkt", None) else None

    src_epsg = int(getattr(meshed, "crs_epsg", 4326) or 4326)
    transformer = Transformer.from_crs(src_epsg, 4326, always_xy=True)

    features: List[Dict[str, Any]] = []

    if isinstance(nodes, np.ndarray) and nodes.size:
        lons, lats = transformer.transform(nodes[:, 0], nodes[:, 1])
        MAX_NODES = 50000
        coords = [[float(lons[i]), float(lats[i])] for i in range(min(len(lons), MAX_NODES))]
        features.append({
            "type": "Feature",
            "properties": {"type": "mesh_nodes", "count": len(coords)},
            "geometry": {"type": "MultiPoint", "coordinates": coords}
        })

    if isinstance(nodes, np.ndarray) and nodes.size and isinstance(tris, np.ndarray) and tris.size:
        lons, lats = transformer.transform(nodes[:, 0], nodes[:, 1])
        edges = set()
        for t in tris:
            if len(t) != 3:
                continue
            i, j, k = int(t[0]), int(t[1]), int(t[2])
            for a, b in ((i, j), (j, k), (k, i)):
                if a == b:
                    continue
                e = (a, b) if a < b else (b, a)
                edges.add(e)
        MAX_EDGES = 30000
        lines = [
            [[float(lons[a]), float(lats[a])], [float(lons[b]), float(lats[b])]]
            for a, b in list(edges)[:MAX_EDGES]
        ]
        features.append({
            "type": "Feature",
            "properties": {"type": "mesh_wire", "edges": len(lines)},
            "geometry": {"type": "MultiLineString", "coordinates": lines},
        })

    if water:
        try:
            water_wgs = shp_transform(transformer.transform, water)
            features.append({
                "type": "Feature",
                "properties": {"type": "water_corridor"},
                "geometry": water_wgs.__geo_interface__,
            })
        except Exception:
            pass

    control_points: List[Tuple[int, float, float]] = []
    pts_raw = await rpoint_svc.get_all_entities(filters={"route_id": meshed.route_id}, page=1, limit=10000)
    if isinstance(pts_raw, dict) and "results" in pts_raw:
        pts_raw = pts_raw["results"]

    for p in (pts_raw or []):
        x = getattr(p, "x", None) if not isinstance(p, dict) else p.get("x")
        y = getattr(p, "y", None) if not isinstance(p, dict) else p.get("y")
        idx = getattr(p, "seq_idx", None) if not isinstance(p, dict) else p.get("seq_idx")
        if x is not None and y is not None:
            control_points.append((int(idx or len(control_points)), float(x), float(y)))

    if not control_points:
        route_obj = await route_svc.get_entity_by_id(meshed.route_id, allow_none=True)
        ctrl_json = None
        if route_obj is not None:
            ctrl_json = getattr(route_obj, "control_points", None) or getattr(route_obj, "control_points_json", None)
        if ctrl_json:
            try:
                coords = json.loads(ctrl_json)
                for i, (lon, lat) in enumerate(coords):
                    control_points.append((i, float(lon), float(lat)))
            except Exception:
                pass

    for idx, lon, lat in sorted(control_points, key=lambda r: r[0]):
        features.append({
            "type": "Feature",
            "properties": {"type": "control_point", "seq_idx": idx},
            "geometry": {"type": "Point", "coordinates": [lon, lat]},
        })

    route_added = False
    if route:
        try:
            route_wgs = shp_transform(transformer.transform, route)
            features.append({
                "type": "Feature",
                "properties": {"type": "route"},
                "geometry": route_wgs.__geo_interface__,
            })
            route_added = True
        except Exception:
            route_added = False

    if not route_added and len(control_points) >= 2:
        coords = [(lon, lat) for idx, lon, lat in sorted(control_points, key=lambda r: r[0])]
        features.append({
            "type": "Feature",
            "properties": {"type": "route", "source": "control_points_fallback"},
            "geometry": {"type": "LineString", "coordinates": coords},
        })

    return {"type": "FeatureCollection", "features": features}
