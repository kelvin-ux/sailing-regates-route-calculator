from __future__ import annotations
import math
import heapq
import numpy as np

from typing import Dict, List, Tuple, Optional
from shapely.geometry import LineString, Point
from shapely.ops import nearest_points
from app.services.meshing.triangle_mesher import _triangulate_geom


def _edge_ok(p: Tuple[float, float], q: Tuple[float, float], navigable) -> bool:
    """Sprawdza czy krawędź mieści się w obszarze żeglownym"""
    seg = LineString([p, q])
    try:
        return seg.within(navigable)
    except Exception:
        return seg.buffer(0).within(navigable.buffer(0))


def _knn_indices(V: np.ndarray, pt: Tuple[float, float], k: int = 8) -> List[int]:
    dx = V[:, 0] - pt[0]
    dy = V[:, 1] - pt[1]
    d2 = dx * dx + dy * dy
    # Zabezpieczenie, gdy k jest większe niż liczba wierzchołków
    k = min(k, len(V))
    if k == 0: return []

    idx = np.argpartition(d2, k - 1)[:k]
    return idx[np.argsort(d2[idx])].tolist()


def _build_graph(V: np.ndarray, T: np.ndarray, navigable, fairway=None) -> Dict[int, List[Tuple[int, float]]]:
    """
    Buduje graf sąsiedztwa.
    """
    adj: Dict[int, List[Tuple[int, float]]] = {i: [] for i in range(V.shape[0])}
    seen = set()
    for a, b, c in T:
        tri_e = [(a, b), (b, c), (c, a)]
        for u, v in tri_e:
            if u == v: continue
            e = (min(u, v), max(u, v))
            if e in seen: continue
            seen.add(e)
            pu = (float(V[u, 0]), float(V[u, 1]))
            pv = (float(V[v, 0]), float(V[v, 1]))

            if not _edge_ok(pu, pv, navigable):
                continue

            w = math.hypot(pu[0] - pv[0], pu[1] - pv[1])

            if fairway is not None:
                try:
                    if LineString([pu, pv]).distance(fairway) < 80.0:
                        w *= 0.75
                except Exception:
                    pass
            adj[u].append((v, w))
            adj[v].append((u, w))
    return adj


def _dijkstra(adj: Dict[int, List[Tuple[int, float]]], s: int, t: int) -> List[int]:
    INF = 1e100
    dist = {i: INF for i in adj.keys()}
    prev = {i: -1 for i in adj.keys()}
    dist[s] = 0.0
    pq = [(0.0, s)]

    found_target = False

    while pq:
        d, u = heapq.heappop(pq)
        if d > dist[u]: continue
        if u == t:
            found_target = True
            break
        for v, w in adj[u]:
            nd = d + w
            if nd < dist[v]:
                dist[v] = nd
                prev[v] = u
                heapq.heappush(pq, (nd, v))

    if not found_target or prev[t] == -1:
        return []

    path = []
    cur = t
    while cur != -1:
        path.append(cur)
        cur = prev[cur]
    path.reverse()
    return path


# Zmieniono domyślną wartość coarse_area z 250000.0 na 5000.0
def safe_polyline(navigable, waypoints: List[Tuple[float, float]],
                  coarse_area: float = 5000.0, fairway=None) -> Optional[LineString]:
    """
    Generuje bezpieczną linię 'detour'.
    Zmniejszone coarse_area pozwala znaleźć drogę w wąskich przejściach.
    """
    if not waypoints or len(waypoints) < 2:
        return None

    # 1. Snapowanie punktów do wody
    valid_waypoints = []
    for wp in waypoints:
        p = Point(wp)
        if not p.within(navigable):
            try:
                # Szukamy najbliższego punktu wewnątrz poligonu navigable
                # Jeśli navigable ma dziury (mielizny), to nearest_points może zwrócić punkt na brzegu dziury - to OK.
                p_in, p_near = nearest_points(navigable, p)
                # nearest_points(poly, point) zwraca (punkt_na_poly, punkt_zrodlowy)
                # Ale uwaga: w shapely ops.nearest_points argumenty są (geom1, geom2) -> (p1, p2)
                # p1 to punkt na geom1 najbliższy do geom2.

                valid_waypoints.append((p_in.x, p_in.y))
            except Exception:
                valid_waypoints.append(wp)
        else:
            valid_waypoints.append(wp)

    # 2. Triangulacja - teraz gęstsza (5000.0)
    mesh = _triangulate_geom(navigable, max_area=coarse_area)
    V = np.asarray(mesh["vertices"])
    T = np.asarray(mesh["triangles"], dtype=int)

    if V.size == 0 or T.size == 0:
        return None

    adj_base = _build_graph(V, T, navigable, fairway=fairway)

    full_path_coords = []
    s_idx_virt = V.shape[0]
    t_idx_virt = V.shape[0] + 1

    for i in range(len(valid_waypoints) - 1):
        start_seg = valid_waypoints[i]
        end_seg = valid_waypoints[i + 1]

        # Reset wirtualnych węzłów
        adj_base[s_idx_virt] = []
        adj_base[t_idx_virt] = []

        # Podłączamy start i stop do sieci
        # Zwiększamy k=20 dla pewności przy gęstszej siatce
        for k_idx in _knn_indices(V, start_seg, k=20):
            pu = (float(V[k_idx, 0]), float(V[k_idx, 1]))
            if _edge_ok(pu, start_seg, navigable):
                w = math.hypot(pu[0] - start_seg[0], pu[1] - start_seg[1])
                adj_base[s_idx_virt].append((k_idx, w))
                adj_base[k_idx].append((s_idx_virt, w))

        for k_idx in _knn_indices(V, end_seg, k=20):
            pu = (float(V[k_idx, 0]), float(V[k_idx, 1]))
            if _edge_ok(pu, end_seg, navigable):
                w = math.hypot(pu[0] - end_seg[0], pu[1] - end_seg[1])
                adj_base[t_idx_virt].append((k_idx, w))
                adj_base[k_idx].append((t_idx_virt, w))

        path_indices = _dijkstra(adj_base, s_idx_virt, t_idx_virt)

        # Sprzątanie grafu po tej iteracji
        for u, _ in adj_base[s_idx_virt]:
            adj_base[u] = [x for x in adj_base[u] if x[0] != s_idx_virt]
        for u, _ in adj_base[t_idx_virt]:
            adj_base[u] = [x for x in adj_base[u] if x[0] != t_idx_virt]

        if not path_indices:
            segment_coords = [start_seg, end_seg]
        else:
            segment_coords = []
            for idx in path_indices:
                if idx == s_idx_virt:
                    segment_coords.append(start_seg)
                elif idx == t_idx_virt:
                    segment_coords.append(end_seg)
                else:
                    segment_coords.append((float(V[idx, 0]), float(V[idx, 1])))

        if i == 0:
            full_path_coords.extend(segment_coords)
        else:
            full_path_coords.extend(segment_coords[1:])

    if len(full_path_coords) < 2:
        return None

    ls = LineString(full_path_coords)
    try:
        # Uproszczenie geometrii, żeby nie zwracać tysięcy punktów
        ls = ls.simplify(5.0, preserve_topology=False)
    except Exception:
        pass
    return ls