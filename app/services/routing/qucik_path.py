from __future__ import annotations

import math
import heapq
import numpy as np
from typing import List
from typing import Tuple
from typing import Dict
from typing import Optional
from typing import TypeAlias

from shapely.geometry import LineString, Point
from shapely.ops import nearest_points
from app.services.meshing.triangle_mesher import _triangulate_geom

Point2D: TypeAlias = Tuple[float, float]
AdjacencyGraph: TypeAlias = Dict[int, List[Tuple[int, float]]]


def _is_edge_valid(p1: Point2D, p2: Point2D, navigable_area) -> bool:
    segment = LineString([p1, p2])
    try:
        return segment.within(navigable_area)
    except Exception:
        return segment.buffer(0).within(navigable_area.buffer(0))


def _get_knn_indices(vertices: np.ndarray, point: Point2D, k: int = 8) -> List[int]:
    dx = vertices[:, 0] - point[0]
    dy = vertices[:, 1] - point[1]
    dist_sq = dx * dx + dy * dy

    k = min(k, len(vertices))
    if k == 0:
        return []

    indices = np.argpartition(dist_sq, k - 1)[:k]
    return indices[np.argsort(dist_sq[indices])].tolist()


def _build_adjacency_graph(vertices: np.ndarray, triangles: np.ndarray,
        navigable_area, fairway: Optional[LineString] = None) -> AdjacencyGraph:
    graph: AdjacencyGraph = {i: [] for i in range(vertices.shape[0])}
    seen_edges = set()

    for a, b, c in triangles:
        triangle_edges = [(a, b), (b, c), (c, a)]
        for u, v in triangle_edges:
            if u == v:
                continue

            edge_key = (min(u, v), max(u, v))
            if edge_key in seen_edges:
                continue
            seen_edges.add(edge_key)

            p_u = (float(vertices[u, 0]), float(vertices[u, 1]))
            p_v = (float(vertices[v, 0]), float(vertices[v, 1]))

            if not _is_edge_valid(p_u, p_v, navigable_area):
                continue

            weight = math.dist(p_u, p_v)

            if fairway is not None:
                try:
                    if LineString([p_u, p_v]).distance(fairway) < 80.0:
                        weight *= 0.75
                except Exception:
                    pass

            graph[u].append((v, weight))
            graph[v].append((u, weight))

    return graph


def _dijkstra_search(graph: AdjacencyGraph, start_node: int, target_node: int) -> List[int]:
    inf_dist = 1e100
    distances = {node: inf_dist for node in graph}
    previous_nodes = {node: -1 for node in graph}

    distances[start_node] = 0.0
    priority_queue = [(0.0, start_node)]

    found = False

    while priority_queue:
        current_dist, current_node = heapq.heappop(priority_queue)

        if current_dist > distances[current_node]:
            continue

        if current_node == target_node:
            found = True
            break

        for neighbor, weight in graph[current_node]:
            new_dist = current_dist + weight
            if new_dist < distances[neighbor]:
                distances[neighbor] = new_dist
                previous_nodes[neighbor] = current_node
                heapq.heappush(priority_queue, (new_dist, neighbor))

    if not found or previous_nodes[target_node] == -1:
        return []

    path = []
    current = target_node
    while current != -1:
        path.append(current)
        current = previous_nodes[current]

    return path[::-1]


def safe_polyline(navigable_area, waypoints: List[Point2D],
        coarse_area: float = 5000.0, fairway: Optional[LineString] = None) -> Optional[LineString]:
    if not waypoints or len(waypoints) < 2:
        return None

    valid_waypoints = []
    for wp in waypoints:
        point = Point(wp)
        if not point.within(navigable_area):
            try:
                p_snapped, _ = nearest_points(navigable_area, point)
                valid_waypoints.append((p_snapped.x, p_snapped.y))
            except Exception:
                valid_waypoints.append(wp)
        else:
            valid_waypoints.append(wp)

    mesh = _triangulate_geom(navigable_area, max_area=coarse_area)
    vertices = np.asarray(mesh["vertices"])
    triangles = np.asarray(mesh["triangles"], dtype=int)

    if vertices.size == 0 or triangles.size == 0:
        return None

    adjacency_graph = _build_adjacency_graph(vertices, triangles, navigable_area, fairway)

    full_path_coords = []
    virtual_start_idx = vertices.shape[0]
    virtual_target_idx = vertices.shape[0] + 1

    adjacency_graph[virtual_start_idx] = []
    adjacency_graph[virtual_target_idx] = []

    for i in range(len(valid_waypoints) - 1):
        start_point = valid_waypoints[i]
        end_point = valid_waypoints[i + 1]

        adjacency_graph[virtual_start_idx].clear()
        adjacency_graph[virtual_target_idx].clear()

        for k_idx in _get_knn_indices(vertices, start_point, k=20):
            vertex_point = (float(vertices[k_idx, 0]), float(vertices[k_idx, 1]))
            if _is_edge_valid(vertex_point, start_point, navigable_area):
                weight = math.dist(vertex_point, start_point)
                adjacency_graph[virtual_start_idx].append((k_idx, weight))
                adjacency_graph[k_idx].append((virtual_start_idx, weight))

        for k_idx in _get_knn_indices(vertices, end_point, k=20):
            vertex_point = (float(vertices[k_idx, 0]), float(vertices[k_idx, 1]))
            if _is_edge_valid(vertex_point, end_point, navigable_area):
                weight = math.dist(vertex_point, end_point)
                adjacency_graph[virtual_target_idx].append((k_idx, weight))
                adjacency_graph[k_idx].append((virtual_target_idx, weight))

        path_indices = _dijkstra_search(adjacency_graph, virtual_start_idx, virtual_target_idx)

        for u, _ in adjacency_graph[virtual_start_idx]:
            adjacency_graph[u] = [edge for edge in adjacency_graph[u] if edge[0] != virtual_start_idx]
        for u, _ in adjacency_graph[virtual_target_idx]:
            adjacency_graph[u] = [edge for edge in adjacency_graph[u] if edge[0] != virtual_target_idx]

        if not path_indices:
            segment_coords = [start_point, end_point]
        else:
            segment_coords = []
            for idx in path_indices:
                if idx == virtual_start_idx:
                    segment_coords.append(start_point)
                elif idx == virtual_target_idx:
                    segment_coords.append(end_point)
                else:
                    segment_coords.append((float(vertices[idx, 0]), float(vertices[idx, 1])))

        if i == 0:
            full_path_coords.extend(segment_coords)
        else:
            full_path_coords.extend(segment_coords[1:])

    if len(full_path_coords) < 2:
        return None

    polyline = LineString(full_path_coords)
    try:
        return polyline.simplify(5.0, preserve_topology=False)
    except Exception:
        return polyline