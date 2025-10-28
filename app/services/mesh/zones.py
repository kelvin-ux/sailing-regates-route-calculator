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
        """Główna metoda wyboru punktów z uwzględnieniem stref


        - Strefa near: równomiernie wzdłuż trasy
        - Strefa mid: równomierna siatka punktów, każdy punkt ma swoje pole
        - Strefa far: równomierna siatka punktów, każdy punkt ma swoje pole
        """

        vertices_by_zone = self._classify_vertices_by_zone(navigation_vertices, route_line)

        total_points = self.config.max_points

        near_count = int(total_points * 0.4)
        mid_count = int(total_points * 0.4)
        far_count = total_points - near_count - mid_count  # Reszta idzie do far

        near_points = self._sample_along_route_in_zone(
            route_line,
            near_count,
            max_distance=self.config.near_zone_m
        )

        mid_points = self._select_grid_based(
            vertices_by_zone['mid'],
            mid_count,
            route_line,
            min_distance=self.config.near_zone_m,
            max_distance=self.config.mid_zone_m
        )

        far_points = self._select_grid_based(
            vertices_by_zone['far'],
            far_count,
            route_line,
            min_distance=self.config.mid_zone_m,
            max_distance=self.config.far_zone_m
        )

        all_points = near_points + mid_points + far_points
        all_points = self._remove_duplicates(all_points, min_distance_m=100.0)

        return all_points[:self.config.max_points]

    def _classify_vertices_by_zone(self, vertices: np.ndarray, route_line: LineString) -> Dict[str, np.ndarray]:
        """Klasyfikuje wierzchołki według odległości od trasy

        Strefy:
        - near: <= near_zone_m
        - mid: near_zone_m < d <= mid_zone_m
        - far: > mid_zone_m
        """
        distances = np.array([route_line.distance(Point(v[0], v[1])) for v in vertices])

        near_mask = distances <= self.config.near_zone_m
        mid_mask = (distances > self.config.near_zone_m) & (distances <= self.config.mid_zone_m)
        far_mask = distances > self.config.mid_zone_m

        return {
            'near': vertices[near_mask],
            'mid': vertices[mid_mask],
            'far': vertices[far_mask]
        }

    def _sample_along_route_in_zone(self, route: LineString, count: int, max_distance: float) -> List[
        Tuple[float, float]]:
        """
        Próbkuje punkty równomiernie wzdłuż trasy, z możliwością przesunięcia w bok
        """
        if count <= 0:
            return []

        total_len = route.length
        points = []

        for i in range(count):
            if count == 1:
                dist = total_len / 2
            else:
                dist = (i / (count - 1)) * total_len

            p = route.interpolate(dist)

            if i % 2 == 0:
                offset = min(50.0, max_distance * 0.1)
            else:
                offset = -min(50.0, max_distance * 0.1)

            if dist > 10 and dist < total_len - 10:
                p_before = route.interpolate(dist - 10)
                p_after = route.interpolate(dist + 10)
                dx = p_after.x - p_before.x
                dy = p_after.y - p_before.y
                length = np.sqrt(dx * dx + dy * dy)
                if length > 0:
                    nx = -dy / length * offset
                    ny = dx / length * offset
                    points.append((p.x + nx, p.y + ny))
                else:
                    points.append((p.x, p.y))
            else:
                points.append((p.x, p.y))

        return points

    def _select_grid_based(self, vertices: np.ndarray, count: int, route_line: LineString,
                           min_distance: float, max_distance: float) -> List[Tuple[float, float]]:
        """Wybór punktów na równomiernej siatce w danej strefie

        Tworzy regularną siatkę punktów w strefie między min_distance a max_distance od trasy.
        Każdy punkt ma swoje własne "pole" o podobnej wielkości.
        """
        if len(vertices) == 0 or count <= 0:
            return []

        route_length = route_line.length

        avg_distance = (min_distance + max_distance) / 2.0

        zone_width = max_distance - min_distance
        zone_length = route_length

        zone_area = 2 * zone_width * zone_length

        area_per_point = zone_area / max(count, 1)

        optimal_spacing = np.sqrt(area_per_point)

        points_along = max(1, int(zone_length / optimal_spacing))
        points_across = max(1, int(count / points_along))

        while points_along * points_across * 2 > count:  # *2 bo po obu stronach
            if points_along > points_across:
                points_along -= 1
            else:
                points_across -= 1
            if points_along < 1 or points_across < 1:
                points_along = max(1, points_along)
                points_across = max(1, points_across)
                break

        selected_points = []

        for i in range(points_along):
            if points_along == 1:
                dist_along = route_length / 2
            else:
                dist_along = (i / (points_along - 1)) * route_length

            route_point = route_line.interpolate(dist_along)

            if dist_along > 10 and dist_along < route_length - 10:
                p_before = route_line.interpolate(dist_along - 10)
                p_after = route_line.interpolate(dist_along + 10)
                dx = p_after.x - p_before.x
                dy = p_after.y - p_before.y
                length = np.sqrt(dx * dx + dy * dy)

                if length > 0:
                    nx = -dy / length
                    ny = dx / length
                else:
                    nx, ny = 0, 1
            else:
                nx, ny = 0, 1

            for j in range(points_across):
                if points_across == 1:
                    distance = avg_distance
                else:
                    distance = min_distance + (j + 0.5) * zone_width / points_across

                left_x = route_point.x + nx * distance
                left_y = route_point.y + ny * distance
                selected_points.append((left_x, left_y))

                right_x = route_point.x - nx * distance
                right_y = route_point.y - ny * distance
                selected_points.append((right_x, right_y))

                if len(selected_points) >= count:
                    break

            if len(selected_points) >= count:
                break

        if len(vertices) > 0 and len(selected_points) > 0:
            final_points = []
            vertices_tree = KDTree(vertices)

            for grid_point in selected_points[:count]:
                dist, idx = vertices_tree.query(grid_point, k=1)
                if dist < zone_width:
                    vertex = vertices[idx]
                    vertex_dist = route_line.distance(Point(vertex[0], vertex[1]))
                    if min_distance <= vertex_dist <= max_distance:
                        final_points.append((float(vertex[0]), float(vertex[1])))
                    else:
                        final_points.append(grid_point)
                else:
                    final_points.append(grid_point)

            return final_points[:count]
        else:
            return selected_points[:count]
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
