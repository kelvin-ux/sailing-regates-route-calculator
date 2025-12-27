from __future__ import annotations
from typing import List, Dict, Any, Optional
import numpy as np
from shapely import geometry as shp
from shapely.geometry import Polygon, MultiPolygon, LineString, LinearRing, Point
from shapely.validation import make_valid as _make_valid
import triangle as tr
from app.schemas.meshzones import MeshZones

_EPS_AREA = 1e-6


def _valid_geom(g: shp.base.BaseGeometry) -> shp.base.BaseGeometry:
    if g is None or g.is_empty:
        return g
    try:
        gv = _make_valid(g) if _make_valid else g.buffer(0)
        return gv if not gv.is_empty else g
    except Exception:
        try:
            return g.buffer(0)
        except Exception:
            return g


def _ring_indices(coords, vertices, idx_map) -> List[int]:
    coords = list(coords)
    if len(coords) >= 2 and coords[0] == coords[-1]:
        coords = coords[:-1]
    base = []
    seen_local = set()
    for x, y in coords:
        key = (float(x), float(y))
        if key in seen_local: continue
        seen_local.add(key)
        if key in idx_map:
            i = idx_map[key]
        else:
            i = len(vertices)
            vertices.append(key)
            idx_map[key] = i
        base.append(i)
    if len(base) < 3: return []
    return base


def _poly_to_pslg(poly: Polygon, fixed_points: List[tuple] = None) -> Dict[str, Any]:
    if poly.is_empty or abs(poly.area) < _EPS_AREA:
        return {"vertices": np.zeros((0, 2)), "segments": np.zeros((0, 2), dtype=int), "holes": []}

    poly = _valid_geom(poly)
    vertices, segments, idx_map = [], [], {}

    ext = _ring_indices(list(poly.exterior.coords), vertices, idx_map)
    for i in range(len(ext)):
        a, b = ext[i], ext[(i + 1) % len(ext)]
        if a != b: segments.append((a, b))

    holes_xy = []
    for interior in poly.interiors:
        base = _ring_indices(list(interior.coords), vertices, idx_map)
        for i in range(len(base)):
            a, b = base[i], base[(i + 1) % len(base)]
            if a != b: segments.append((a, b))
        try:
            ip = Polygon(interior)
            if abs(ip.area) >= _EPS_AREA:
                rp = ip.representative_point()
                holes_xy.append((float(rp.x), float(rp.y)))
        except:
            pass

    if fixed_points:
        for fx, fy in fixed_points:
            key = (float(fx), float(fy))
            if key not in idx_map:
                vertices.append(key)

    if not segments or len(vertices) < 3:
        return {"vertices": np.zeros((0, 2)), "segments": np.zeros((0, 2), dtype=int), "holes": []}

    return {
        "vertices": np.asarray(vertices, dtype=float),
        "segments": np.asarray(segments, dtype=int),
        "holes": holes_xy,
    }


def _triangulate_single_polygon(poly: Polygon, max_area: float, fixed_points: List[tuple] = None) -> Dict[str, Any]:
    pslg = _poly_to_pslg(poly, fixed_points)
    V, S = pslg["vertices"], pslg["segments"]
    if V.size == 0 or S.size == 0:
        return {"vertices": np.zeros((0, 2)), "triangles": np.zeros((0, 3), dtype=int)}

    data = {"vertices": V, "segments": S}
    if pslg["holes"]: data["holes"] = np.asarray(pslg["holes"], dtype=float)

    try:
        result = tr.triangulate(data, f"pq30a{max_area}")
    except:
        return {"vertices": np.zeros((0, 2)), "triangles": np.zeros((0, 3), dtype=int)}

    V2 = np.asarray(result.get("vertices", np.zeros((0, 2))), dtype=float)
    T2 = np.asarray(result.get("triangles", np.zeros((0, 3))), dtype=int)
    return {"vertices": V2, "triangles": T2}


def _triangulate_geom(geom: shp.base.BaseGeometry, max_area: float, fixed_points: List[tuple] = None) -> Dict[str, Any]:
    g = _valid_geom(geom)
    if g is None or g.is_empty:
        return {"vertices": np.zeros((0, 2)), "triangles": np.zeros((0, 3), dtype=int)}

    polys = [g] if isinstance(g, Polygon) else [p for p in g.geoms if isinstance(p, Polygon)] if isinstance(g,
                                                                                                            MultiPolygon) else []

    all_V, all_T, offset = [], [], 0
    for p in polys:
        if p.is_empty or abs(p.area) < _EPS_AREA: continue
        p_fixed = []
        if fixed_points:
            for fx, fy in fixed_points:
                pt = Point(fx, fy)
                if p.contains(pt) or p.distance(pt) < 1e-3:
                    p_fixed.append((fx, fy))

        mesh = _triangulate_single_polygon(p, max_area=max_area, fixed_points=p_fixed)
        V = np.asarray(mesh["vertices"])
        T = np.asarray(mesh["triangles"], dtype=int)
        if V.size == 0 or T.size == 0: continue
        all_V.append(V)
        all_T.append(T + offset)
        offset += V.shape[0]

    if not all_V: return {"vertices": np.zeros((0, 2)), "triangles": np.zeros((0, 3), dtype=int)}
    return {"vertices": np.vstack(all_V), "triangles": np.vstack(all_T)}


def triangulate_water(water_xy: shp.base.BaseGeometry,
                      route_xy: LineString,
                      zones: MeshZones,
                      coast_clear_m: float = 0.0,
                      coast_simplify_m: float = 0.0,
                      fixed_points: List[tuple] = None) -> Dict[str, Any]:
    g_raw = _valid_geom(water_xy)
    if g_raw is None or g_raw.is_empty:
        return {"vertices": np.zeros((0, 2)), "triangles": np.zeros((0, 3), dtype=int)}

    r1, r2, _ = zones.radii_m
    a1, a2, a3 = zones.max_area_m2

    B1 = route_xy.buffer(r1, cap_style=2, join_style=2)
    B2 = route_xy.buffer(r2, cap_style=2, join_style=2)

    g_ero = g_raw
    if coast_clear_m > 0: g_ero = _valid_geom(g_ero.buffer(-float(coast_clear_m)))
    if coast_simplify_m > 0:
        try:
            g_ero = _valid_geom(g_ero.simplify(float(coast_simplify_m), preserve_topology=True))
        except:
            pass
    if g_ero is None or g_ero.is_empty: g_ero = g_raw

    near = _valid_geom(g_raw.intersection(B1))
    mid = _valid_geom(g_ero.intersection(B2.difference(B1)))
    far = _valid_geom(g_ero.difference(B2))

    parts = []
    for geom, area in ((near, a1), (mid, a2), (far, a3)):
        if geom is None or geom.is_empty: continue

        # Pass fixed points to the triangulation of the specific zone
        mesh = _triangulate_geom(geom, max_area=area, fixed_points=fixed_points)
        V = np.asarray(mesh["vertices"]);
        T = np.asarray(mesh["triangles"], dtype=int)
        if V.size == 0 or T.size == 0: continue
        parts.append((V, T))

    if not parts: return {"vertices": np.zeros((0, 2)), "triangles": np.zeros((0, 3), dtype=int)}

    Vs, Ts, offset = [], [], 0
    for V, T in parts:
        Vs.append(V)
        Ts.append(T + offset)
        offset += V.shape[0]

    return {
        "vertices": np.vstack(Vs) if Vs else np.zeros((0, 2)),
        "triangles": np.vstack(Ts) if Ts else np.zeros((0, 3), dtype=int)
    }