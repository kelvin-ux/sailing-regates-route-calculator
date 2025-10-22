from __future__ import annotations

import numpy as np
from typing import Tuple
from typing import List
from typing import Dict

from app.schemas.WeatherMeshConfig import WeatherMeshConfig

from shapely.geometry import Point
from shapely.geometry import LineString
from sklearn.cluster import KMeans
from scipy.spatial import KDTree


class ZonalWeatherPointSelector:
    def __init__(self, config: WeatherMeshConfig):
        self.config = config

    def select_points(self, navigation_vertices: np.ndarray, route_line: LineString, water_poly) -> List[
        Tuple[float, float]]:
        """Główna metoda wyboru punktów z uwzględnieniem stref"""

        route_points_count = int(self.config.priority_route_points * (1 - self.config.rdr))
        route_points = self._sample_along_route(route_line, route_points_count)

        vertices_by_zone = self._classify_vertices_by_zone(navigation_vertices, route_line)

        remaining = self.config.max_points - len(route_points)

        # Proporcje: near=1.0, mid=0.25, far=0.125
        near_count = int(remaining * (1.0 / 1.375))
        mid_count = int(remaining * (0.25 / 1.375))
        far_count = remaining - near_count - mid_count

        near_points = self._select_in_zone(
            vertices_by_zone['near'],
            near_count,
            route_line,
            zone_type='near'
        )

        mid_points = self._select_in_zone(
            vertices_by_zone['mid'],
            mid_count,
            route_line,
            zone_type='mid'
        )

        far_points = self._select_in_zone(
            vertices_by_zone['far'],
            far_count,
            route_line,
            zone_type='far'
        )

        all_points = route_points + near_points + mid_points + far_points
        all_points = self._remove_duplicates(all_points, min_distance_m=100.0)

        return all_points[:self.config.max_points]

    def _classify_vertices_by_zone(self, vertices: np.ndarray, route_line: LineString) -> Dict[str, np.ndarray]:
        """Klasyfikuje wierzchołki według odległości od trasy"""
        distances = np.array([route_line.distance(Point(v[0], v[1])) for v in vertices])

        near_mask = distances <= self.config.near_zone_m
        mid_mask = (distances > self.config.near_zone_m) & (distances <= self.config.mid_zone_m)
        far_mask = distances > self.config.mid_zone_m

        return {
            'near': vertices[near_mask],
            'mid': vertices[mid_mask],
            'far': vertices[far_mask]
        }

    def _select_in_zone(self, vertices: np.ndarray, count: int, route_line: LineString, zone_type: str) -> List[
        Tuple[float, float]]:
        """Wybiera punkty w danej strefie z odpowiednią strategią"""

        if len(vertices) == 0 or count <= 0:
            return []

        if zone_type == 'near':
            # Strefa bliska: regularna gęstość, k-means
            return self._select_uniform(vertices, count)

        elif zone_type == 'mid':
            # Strefa średnia: naprzemiennie po obu stronach trasy
            return self._select_alternating(vertices, count, route_line)

        elif zone_type == 'far':
            # Strefa daleka: symetrycznie po obu stronach
            return self._select_symmetric(vertices, count, route_line)

        return []

    def _select_uniform(self, vertices: np.ndarray, count: int) -> List[Tuple[float, float]]:
        """Wybór równomierny (k-means clustering)"""
        if len(vertices) <= count:
            return [(float(v[0]), float(v[1])) for v in vertices]

        kmeans = KMeans(n_clusters=count, random_state=42, n_init=10)
        kmeans.fit(vertices)
        centers = kmeans.cluster_centers_

        return [(float(c[0]), float(c[1])) for c in centers]

    def _select_alternating(self, vertices: np.ndarray, count: int, route_line: LineString) -> List[
        Tuple[float, float]]:
        """Wybór naprzemiennie po obu stronach trasy (zygzak)"""

        if len(vertices) == 0:
            return []

        left_points = []
        right_points = []

        for v in vertices:
            point = Point(v[0], v[1])
            closest_point = route_line.interpolate(route_line.project(point))

            side = self._point_side(point, closest_point, route_line)

            if side > 0:
                left_points.append(v)
            else:
                right_points.append(v)

        left_points = np.array(left_points) if left_points else np.array([]).reshape(0, 2)
        right_points = np.array(right_points) if right_points else np.array([]).reshape(0, 2)

        count_per_side = count // 2

        left_selected = self._select_uniform(left_points, count_per_side) if len(left_points) > 0 else []
        right_selected = self._select_uniform(right_points, count - count_per_side) if len(right_points) > 0 else []

        result = []
        for i in range(max(len(left_selected), len(right_selected))):
            if i < len(left_selected):
                result.append(left_selected[i])
            if i < len(right_selected):
                result.append(right_selected[i])

        return result

    def _select_symmetric(self, vertices: np.ndarray, count: int, route_line: LineString) -> List[Tuple[float, float]]:
        """Wybór symetryczny po obu stronach trasy"""

        if len(vertices) == 0:
            return []

        left_points = []
        right_points = []

        for v in vertices:
            point = Point(v[0], v[1])
            closest_point = route_line.interpolate(route_line.project(point))
            side = self._point_side(point, closest_point, route_line)

            if side > 0:
                left_points.append(v)
            else:
                right_points.append(v)

        left_points = np.array(left_points) if left_points else np.array([]).reshape(0, 2)
        right_points = np.array(right_points) if right_points else np.array([]).reshape(0, 2)

        count_per_side = count // 2

        left_selected = self._select_uniform(left_points, count_per_side) if len(left_points) > 0 else []
        right_selected = self._select_uniform(right_points, count_per_side) if len(right_points) > 0 else []

        left_sorted = self._sort_along_route(left_selected, route_line)
        right_sorted = self._sort_along_route(right_selected, route_line)

        result = []
        for l, r in zip(left_sorted, right_sorted):
            result.append(l)
            result.append(r)

        if len(left_sorted) > len(right_sorted):
            result.extend(left_sorted[len(right_sorted):])
        elif len(right_sorted) > len(left_sorted):
            result.extend(right_sorted[len(left_sorted):])

        return result

    def _point_side(self, point: Point, ref_point: Point, route_line: LineString) -> float:
        """Określa po której stronie trasy jest punkt"""

        distance_along = route_line.project(ref_point)

        segment_start = max(0, distance_along - 10)
        segment_end = min(route_line.length, distance_along + 10)

        start_pt = route_line.interpolate(segment_start)
        end_pt = route_line.interpolate(segment_end)

        dx = end_pt.x - start_pt.x
        dy = end_pt.y - start_pt.y

        px = point.x - ref_point.x
        py = point.y - ref_point.y

        cross = dx * py - dy * px

        return cross

    def _sort_along_route(self, points: List[Tuple[float, float]], route_line: LineString) -> List[Tuple[float, float]]:
        if not points:
            return []

        points_with_distance = []
        for p in points:
            point_geom = Point(p[0], p[1])
            distance_along = route_line.project(point_geom)
            points_with_distance.append((distance_along, p))

        points_with_distance.sort(key=lambda x: x[0])
        return [p for _, p in points_with_distance]

    def _remove_duplicates(self, points: List[Tuple[float, float]], min_distance_m: float) -> List[Tuple[float, float]]:
        if len(points) <= 1:
            return points

        result = [points[0]]
        tree = KDTree([points[0]])

        for p in points[1:]:
            distances, _ = tree.query(p, k=1)
            if distances > min_distance_m:
                result.append(p)
                tree = KDTree(result)

        return result

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