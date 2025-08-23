from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple, Dict, Any

import numpy as np
from shapely import geometry as shp
from shapely.geometry import Polygon, MultiPolygon, LineString, LinearRing
from shapely.ops import unary_union
try:
    from shapely.validation import make_valid as _make_valid
except Exception:
    _make_valid = None

import triangle as tr

@dataclass
class MeshZones:
    radii_m: List[float]       # [r1, r2, r3]  (m)
    max_area_m2: List[float]   # [a1, a2, a3]  (m^2)

    def __post_init__(self):
        r = self.radii_m
        a = self.max_area_m2
        if len(r) != 3 or len(a) != 3:
            raise ValueError("MeshZones.radii_m i max_area_m2 muszą mieć długość 3.")
        if not (r[0] > 0 and r[1] > r[0] and r[2] > r[1]):
            raise ValueError("radii_m muszą być rosnące i dodatnie (r1 < r2 < r3).")
        if not (a[0] > 0 and a[1] >= a[0] and a[2] >= a[1]):
            raise ValueError("max_area_m2 muszą być dodatnie i niemalejące (a1 <= a2 <= a3).")



_EPS_AREA = 1e-6  # m^2 – jak coś ma mniejszą powierzchnię, traktujemy jak szum

def _valid_geom(g: shp.base.BaseGeometry) -> shp.base.BaseGeometry:
    if g is None or g.is_empty:
        return g
    try:
        if _make_valid:
            gv = _make_valid(g)
        else:
            gv = g.buffer(0)  # fallback na starsze Shapely
        return gv if not gv.is_empty else g
    except Exception:
        # ostateczny ratunek
        try:
            return g.buffer(0)
        except Exception:
            return g


def _ring_indices(coords: List[Tuple[float, float]],
                  vertices: List[Tuple[float, float]],
                  idx_map: Dict[Tuple[float, float], int]) -> List[int]:
    """Dodaje węzły pierścienia do globalnej listy 'vertices' (z deduplikacją) i zwraca indeksy."""
    if len(coords) >= 2 and coords[0] == coords[-1]:
        coords = coords[:-1]

    base: List[int] = []
    seen_local = set()
    for x, y in coords:
        key = (float(x), float(y))
        if key in seen_local:
            continue
        seen_local.add(key)
        if key in idx_map:
            i = idx_map[key]
        else:
            i = len(vertices)
            vertices.append(key)
            idx_map[key] = i
        base.append(i)

    if len(base) < 3:
        return []

    try:
        lr = LinearRing([vertices[i] for i in base])
        if lr.is_ccw is None:
            poly_area = abs(Polygon([vertices[i] for i in base]).area)
        else:
            poly_area = abs(Polygon([vertices[i] for i in base]).area)
        if not np.isfinite(poly_area) or poly_area < _EPS_AREA:
            return []
    except Exception:
        try:
            if abs(Polygon([vertices[i] for i in base]).area) < _EPS_AREA:
                return []
        except Exception:
            return []

    return base


def _poly_to_pslg(poly: Polygon) -> Dict[str, Any]:
    """Konwersja Polygon (+dziury) do PSLG dla Triangle."""
    if poly.is_empty or abs(poly.area) < _EPS_AREA:
        return {"vertices": np.zeros((0, 2)), "segments": np.zeros((0, 2), dtype=int), "holes": []}

    poly = _valid_geom(poly)
    if poly.is_empty or not isinstance(poly, Polygon):
        return {"vertices": np.zeros((0, 2)), "segments": np.zeros((0, 2), dtype=int), "holes": []}

    vertices: List[Tuple[float, float]] = []
    segments: List[Tuple[int, int]] = []
    idx_map: Dict[Tuple[float, float], int] = {}

    # zewnętrzny ring
    ext = _ring_indices(list(poly.exterior.coords), vertices, idx_map)
    if not ext:
        return {"vertices": np.zeros((0, 2)), "segments": np.zeros((0, 2), dtype=int), "holes": []}
    for i in range(len(ext)):
        a, b = ext[i], ext[(i + 1) % len(ext)]
        if a != b:
            segments.append((a, b))

    # dziury
    holes_xy: List[Tuple[float, float]] = []
    for interior in poly.interiors:
        base = _ring_indices(list(interior.coords), vertices, idx_map)
        if not base:
            continue
        for i in range(len(base)):
            a, b = base[i], base[(i + 1) % len(base)]
            if a != b:
                segments.append((a, b))
        try:
            ip = Polygon(interior)
            if abs(ip.area) >= _EPS_AREA:
                rp = ip.representative_point()
                holes_xy.append((float(rp.x), float(rp.y)))
        except Exception:
            pass

    if not segments or len(vertices) < 3:
        return {"vertices": np.zeros((0, 2)), "segments": np.zeros((0, 2), dtype=int), "holes": []}

    return {
        "vertices": np.asarray(vertices, dtype=float),
        "segments": np.asarray(segments, dtype=int),
        "holes": holes_xy
    }


def _triangulate_single_polygon(poly: Polygon, max_area: float) -> Dict[str, Any]:
    """Triangulacja jednego Polygonu z maks. powierzchnią trójkąta."""
    pslg = _poly_to_pslg(poly)
    V = pslg["vertices"]; S = pslg["segments"]

    if V.size == 0 or S.size == 0:
        return {"vertices": np.zeros((0, 2)), "triangles": np.zeros((0, 3), dtype=int)}

    if S.max(initial=-1) >= V.shape[0] or S.min(initial=0) < 0:
        return {"vertices": np.zeros((0, 2)), "triangles": np.zeros((0, 3), dtype=int)}

    opts = f"pq30a{max_area}"
    data = {"vertices": V, "segments": S}
    if pslg["holes"]:
        data["holes"] = np.asarray(pslg["holes"], dtype=float)

    try:
        result = tr.triangulate(data, opts)
    except Exception:
        return {"vertices": np.zeros((0, 2)), "triangles": np.zeros((0, 3), dtype=int)}

    V2 = np.asarray(result.get("vertices", np.zeros((0, 2))), dtype=float)
    T2 = np.asarray(result.get("triangles", np.zeros((0, 3))), dtype=int)
    if V2.ndim != 2 or V2.shape[0] == 0 or T2.ndim != 2 or T2.shape[0] == 0:
        return {"vertices": np.zeros((0, 2)), "triangles": np.zeros((0, 3), dtype=int)}
    return {"vertices": V2, "triangles": T2}


def _triangulate_geom(geom: shp.base.BaseGeometry, max_area: float) -> Dict[str, Any]:
    """Trianguluje Polygon z daną gęstością"""
    g = _valid_geom(geom)
    if g is None or g.is_empty:
        return {"vertices": np.zeros((0, 2)), "triangles": np.zeros((0, 3), dtype=int)}

    polys: List[Polygon] = []
    if isinstance(g, Polygon):
        polys = [g]
    elif isinstance(g, MultiPolygon):
        polys = [p for p in g.geoms if isinstance(p, Polygon)]
    else:
        try:
            polys = [p for p in g if isinstance(p, Polygon)]
        except Exception:
            polys = []

    all_V: List[np.ndarray] = []
    all_T: List[np.ndarray] = []
    offset = 0
    for p in polys:
        if p.is_empty or abs(p.area) < _EPS_AREA:
            continue
        mesh = _triangulate_single_polygon(p, max_area=max_area)
        V = np.asarray(mesh["vertices"])
        T = np.asarray(mesh["triangles"], dtype=int)
        if V.size == 0 or T.size == 0:
            continue
        all_V.append(V)
        all_T.append(T + offset)
        offset += V.shape[0]

    if not all_V:
        return {"vertices": np.zeros((0, 2)), "triangles": np.zeros((0, 3), dtype=int)}

    Vout = np.vstack(all_V)
    Tout = np.vstack(all_T) if all_T else np.zeros((0, 3), dtype=int)
    return {"vertices": Vout, "triangles": Tout}



def triangulate_water(water_xy: shp.base.BaseGeometry,
                      route_xy: LineString,
                      zones: MeshZones) -> Dict[str, Any]:
    """
    Trianguluje akwen (Polygon/MultiPolygon) z gęstością zależną od odległości od trasy.
    Strefy: near (<=r1), mid (r1..r2), far (>r2). Zwraca {"vertices": Nx2, "triangles": Mx3}.
    """
    g = _valid_geom(water_xy)
    if g is None or g.is_empty:
        return {"vertices": np.zeros((0, 2)), "triangles": np.zeros((0, 3), dtype=int)}

    r1, r2, _ = zones.radii_m
    a1, a2, a3 = zones.max_area_m2

    B1 = route_xy.buffer(r1, cap_style=2, join_style=2)
    B2 = route_xy.buffer(r2, cap_style=2, join_style=2)

    near = _valid_geom(g.intersection(B1))
    mid = _valid_geom(g.intersection(B2.difference(B1)))
    far = _valid_geom(g.difference(B2))

    parts: List[Tuple[np.ndarray, np.ndarray]] = []

    for geom, area in ((near, a1), (mid, a2), (far, a3)):
        if geom is None or geom.is_empty:
            continue
        mesh = _triangulate_geom(geom, max_area=area)
        V = np.asarray(mesh["vertices"]); T = np.asarray(mesh["triangles"], dtype=int)
        if V.size == 0 or T.size == 0:
            continue
        parts.append((V, T))

    if not parts:
        return {"vertices": np.zeros((0, 2)), "triangles": np.zeros((0, 3), dtype=int)}

    Vs: List[np.ndarray] = []
    Ts: List[np.ndarray] = []
    offset = 0
    for V, T in parts:
        Vs.append(V)
        Ts.append(T + offset)
        offset += V.shape[0]

    Vout = np.vstack(Vs) if Vs else np.zeros((0, 2))
    Tout = np.vstack(Ts) if Ts else np.zeros((0, 3), dtype=int)
    return {"vertices": Vout, "triangles": Tout}
