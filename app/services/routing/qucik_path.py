from __future__ import annotations
from typing import Dict, List, Tuple, Optional
import math, heapq
import numpy as np

from shapely.geometry import Point, LineString, Polygon, MultiPolygon
from shapely.ops import nearest_points
from app.services.meshing.triangle_mesher import _triangulate_geom

def _edge_ok(p: Tuple[float, float], q: Tuple[float, float], navigable) -> bool:
    seg = LineString([p,q])
    try:
        return seg.within(navigable)
    except Exception:
        return seg.buffer(0).within(navigable.buffer(0))

def _knn_indices(V: np.ndarray, pt: Tuple[float,float], k: int = 8) -> List[int]:
    dx = V[:,0] - pt[0]
    dy = V[:,1] - pt[1]
    d2 = dx * dx + dy * dy
    idx = np.argpartition(d2, min(k, len(V-1)))[:k]
    return idx[np.argsort(d2[idx])].tolist()


def _build_graph(V: np.ndarray, T: np.ndarray, navigable, fairway=None) -> Dict[int, List[Tuple[int,float]]]:
    """
    Graf sąsiedztwa po krawędziach trójkątów.
    Jeśli fairway (LineString/MultiLineString) jest podany – krawędzie w jego pobliżu dostają
    mniejszą wagę (preferencja „idź torem wodnym”).
    """
    adj: Dict[int, List[Tuple[int,float]]] = {i: [] for i in range(V.shape[0])}
    seen = set()
    for a,b,c in T:
        tri_e = [(a,b), (b,c), (c,a)]
        for u,v in tri_e:
            if u==v: continue
            e = (min(u,v), max(u,v))
            if e in seen: continue
            seen.add(e)
            pu = (float(V[u,0]), float(V[u,1]))
            pv = (float(V[v,0]), float(V[v,1]))
            if not _edge_ok(pu, pv, navigable):  # sanity
                continue
            w = math.hypot(pu[0]-pv[0], pu[1]-pv[1])
            # bonus za bliskość fairway (jeśli podany)
            if fairway is not None:
                try:
                    if LineString([pu,pv]).distance(fairway) < 80.0:  # ~80 m
                        w *= 0.75
                except Exception:
                    pass
            adj[u].append((v,w))
            adj[v].append((u,w))
    return adj

def _dijkstra(adj: Dict[int, List[Tuple[int,float]]], s: int, t: int) -> List[int]:
    INF = 1e100
    dist = {i: INF for i in adj.keys()}
    prev = {i: -1 for i in adj.keys()}
    dist[s] = 0.0
    pq = [(0.0, s)]
    while pq:
        d,u = heapq.heappop(pq)
        if d!=dist[u]: continue
        if u==t: break
        for v,w in adj[u]:
            nd = d + w
            if nd < dist[v]:
                dist[v] = nd
                prev[v] = u
                heapq.heappush(pq, (nd, v))
    if prev[t] == -1:
        return []
    path = []
    cur = t
    while cur != -1:
        path.append(cur)
        cur = prev[cur]
    path.reverse()
    return path

def safe_polyline(navigable, start_xy: Tuple[float,float], end_xy: Tuple[float,float],
                  coarse_area: float = 250000.0, fairway=None) -> Optional[LineString]:
    """
    Zwraca LineString „bezpiecznej łamanej” od start do meta, w CAŁOŚCI wewnątrz 'navigable'.
    - trianguluje szybko 'navigable' (duże trójkąty),
    - buduje graf po krawędziach,
    - łączy start/meta z najbliższymi węzłami,
    - liczy najkrótszą ścieżkę.
    """
    # triangulacja
    mesh = _triangulate_geom(navigable, max_area=coarse_area)
    V = np.asarray(mesh["vertices"]); T = np.asarray(mesh["triangles"], dtype=int)
    if V.size == 0 or T.size == 0:
        return None

    # graf
    adj = _build_graph(V, T, navigable, fairway=fairway)

    # węzły start/meta – dołącz do grafu
    s_idx = V.shape[0]; t_idx = V.shape[0] + 1
    Vext = np.vstack([V, [[start_xy[0], start_xy[1]], [end_xy[0], end_xy[1]]]])
    adj[s_idx] = []; adj[t_idx] = []

    for i in _knn_indices(V, start_xy, k=12):
        pu = (float(V[i,0]), float(V[i,1]))
        if _edge_ok(pu, start_xy, navigable):
            w = math.hypot(pu[0]-start_xy[0], pu[1]-start_xy[1])
            adj[s_idx].append((i, w)); adj[i].append((s_idx, w))

    for i in _knn_indices(V, end_xy, k=12):
        pu = (float(V[i,0]), float(V[i,1]))
        if _edge_ok(pu, end_xy, navigable):
            w = math.hypot(pu[0]-end_xy[0], pu[1]-end_xy[1])
            adj[t_idx].append((i, w)); adj[i].append((t_idx, w))

    # Dijkstra
    path_idx = _dijkstra(adj, s_idx, t_idx)
    if not path_idx:
        return None

    coords = [(float(Vext[i,0]), float(Vext[i,1])) for i in path_idx]
    ls = LineString(coords)
    # lekkie uproszczenie łamanej (w metrach)
    try:
        ls = ls.simplify(10.0, preserve_topology=False)
    except Exception:
        pass
    return ls