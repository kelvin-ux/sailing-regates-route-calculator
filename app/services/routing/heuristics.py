from __future__ import annotations

import numpy as np
import math
import heapq
from typing import Tuple
from typing import Dict
from typing import List
from typing import Optional
from dataclasses import dataclass

from scipy.spatial import KDTree

from app.models.models import Yacht
from app.schemas.SailingConditions import SailingConditions


@dataclass
class AStarResult:
    path: List[Tuple[float, float]]
    path_indices: List[int]
    g_scores: Dict[int, float]  # Koszt dojścia do każdego węzła
    f_scores: Dict[int, float]  # g + heurystyka dla każdego węzła
    total_cost: float


class SailingHeuristics:
    """
    Heuristics engine for sailing route optimization.
    Calculates costs based on sailing physics and yacht performance.
    """

    def __init__(self, yacht: Yacht, weather_mapping: Dict[int, List[int]], weather_data: Dict = None):
        """
        Initialize heuristics with yacht data and weather mapping.

        Args:
            yacht: Yacht object with polar performance data
            weather_mapping: Mapping from weather points to navigation vertices
            weather_data: Current weather data for all weather points
        """
        self.yacht = yacht
        self.weather_mapping = weather_mapping
        self.weather_data = weather_data or {}

        # Reverse mapping: nav_vertex -> weather_point
        self.nav_to_weather = {}
        for weather_idx, nav_indices in weather_mapping.items():
            for nav_idx in nav_indices:
                self.nav_to_weather[nav_idx] = weather_idx

        # Sailing constants - use yacht-specific times if available
        self.TACKING_PENALTY = (yacht.tack_time * 60.0) if yacht.tack_time else 120.0
        self.GYBING_PENALTY = (yacht.jibe_time * 60.0) if yacht.jibe_time else 90.0
        self.DEAD_ANGLE = 30.0
        self.COMFORT_WAVE_HEIGHT = 4.0
        self.MAX_HEEL_ANGLE = 40.0

        # Store yacht dimensions (convert feet to meters)
        self.yacht_length_m = yacht.length * 0.3048
        self.yacht_beam_m = yacht.beam * 0.3048
        self.yacht_draft_m = (yacht.draft * 0.3048) if yacht.draft else 2.0

    def calculate_edge_cost(self,
                            from_vertex: Tuple[float, float],
                            to_vertex: Tuple[float, float],
                            from_idx: int,
                            to_idx: int,
                            previous_heading: Optional[float] = None) -> float:
        """
        Calculate cost of sailing from one vertex to another.
        Returns cost in seconds (estimated time).
        """
        from_conditions = self._get_conditions_at_vertex(from_idx)
        to_conditions = self._get_conditions_at_vertex(to_idx)

        bearing = self._calculate_bearing(from_vertex, to_vertex)
        distance = self._calculate_distance(from_vertex, to_vertex)

        from_twa = self._calculate_twa(
            previous_heading if previous_heading is not None else bearing,
            from_conditions.wind_direction
        )
        to_twa = self._calculate_twa(bearing, to_conditions.wind_direction)

        if abs(to_twa) < self.DEAD_ANGLE:
            return float('inf')

        avg_wind_speed_knots = (from_conditions.wind_speed + to_conditions.wind_speed) / 2.0
        avg_wind_speed_ms = avg_wind_speed_knots * 0.514444
        avg_wave_height = (from_conditions.wave_height + to_conditions.wave_height) / 2.0

        boat_speed = self._get_boat_speed(avg_wind_speed_ms, abs(to_twa))

        current_velocity_ms = to_conditions.current_velocity * 0.514444
        boat_speed = self._apply_current_effect(
            boat_speed,
            bearing,
            current_velocity_ms,
            to_conditions.current_direction
        )

        wave_penalty = self._calculate_wave_penalty(
            avg_wave_height,
            to_conditions.wave_direction,
            bearing
        )
        boat_speed *= (1.0 - wave_penalty)

        boat_speed = max(boat_speed, 0.5)

        time_cost = distance / boat_speed

        if previous_heading is not None:
            maneuver_penalty = self._calculate_maneuver_penalty(
                previous_heading, bearing, from_twa, to_twa
            )
            time_cost += maneuver_penalty

        comfort_penalty = self._calculate_comfort_penalty(to_conditions)
        time_cost *= (1.0 + comfort_penalty)

        if boat_speed <= 0.01:
            return float("inf")

        if distance > 10000:
            fatigue_factor = 1.0 + (distance - 10000) / 50000
            time_cost *= fatigue_factor

        return time_cost

    def calculate_heuristic_cost(self,
                                 current: Tuple[float, float],
                                 goal: Tuple[float, float],
                                 current_idx: int) -> float:
        """
        Heuristic function for A* algorithm.
        Estimates remaining cost to goal.
        """
        distance = self._calculate_distance(current, goal)

        conditions = self._get_conditions_at_vertex(current_idx)

        if self.yacht.max_speed:
            optimistic_speed = self.yacht.max_speed * 0.514444
        else:
            optimistic_speed = 5.0

        if conditions.wind_speed < 5.0:
            optimistic_speed *= 0.5
        elif conditions.wind_speed > 25.0:
            optimistic_speed *= 0.8

        return distance / optimistic_speed

    def _get_conditions_at_vertex(self, vertex_idx: int) -> SailingConditions:
        """Get weather conditions at a navigation vertex."""
        weather_idx = self.nav_to_weather.get(vertex_idx)

        if weather_idx is not None and weather_idx in self.weather_data:
            return SailingConditions.from_weather_data(self.weather_data[weather_idx])

        return SailingConditions(
            wind_speed=10.0,
            wind_direction=0.0,
            wave_height=1.0,
            wave_direction=0.0,
            wave_period=5.0,
            current_velocity=0.5,
            current_direction=0.0
        )

    def _calculate_bearing(self, from_point: Tuple[float, float],
                           to_point: Tuple[float, float]) -> float:
        """Calculate bearing in degrees from one point to another."""
        dx = to_point[0] - from_point[0]
        dy = to_point[1] - from_point[1]

        bearing = math.degrees(math.atan2(dx, dy))
        return (bearing + 360) % 360

    def _calculate_distance(self, from_point: Tuple[float, float],
                            to_point: Tuple[float, float]) -> float:
        """Calculate Euclidean distance in meters."""
        dx = to_point[0] - from_point[0]
        dy = to_point[1] - from_point[1]
        return math.sqrt(dx * dx + dy * dy)

    def _calculate_twa(self, heading: float, wind_direction: float) -> float:
        """
        Calculate True Wind Angle.
        Returns angle between -180 and 180 degrees.
        """
        wind_from = wind_direction
        twa = heading - wind_from

        while twa > 180:
            twa -= 360
        while twa < -180:
            twa += 360

        return twa

    def _get_boat_speed(self, wind_speed_ms: float, twa: float) -> float:
        """
        Get boat speed from polar data for given wind conditions.
        """
        if not self.yacht.polar_data:
            return self._simple_polar_model(wind_speed_ms, twa)

        polar = self.yacht.polar_data
        twa = abs(twa)

        twa_angles = polar.get('twa_angles', [])
        wind_speeds = polar.get('wind_speeds', [])
        boat_speeds = polar.get('boat_speeds', [])

        if not all([twa_angles, wind_speeds, boat_speeds]):
            return self._simple_polar_model(wind_speed_ms, twa)

        wind_speed_knots = wind_speed_ms / 0.514444

        twa_idx_low, twa_idx_high, twa_factor = self._find_interpolation_indices(
            twa, twa_angles
        )
        ws_idx_low, ws_idx_high, ws_factor = self._find_interpolation_indices(
            wind_speed_knots, wind_speeds
        )

        try:
            speed_ll = boat_speeds[twa_idx_low][ws_idx_low]
            speed_lh = boat_speeds[twa_idx_low][ws_idx_high]
            speed_hl = boat_speeds[twa_idx_high][ws_idx_low]
            speed_hh = boat_speeds[twa_idx_high][ws_idx_high]

            speed_l = speed_ll + (speed_lh - speed_ll) * ws_factor
            speed_h = speed_hl + (speed_hh - speed_hl) * ws_factor
            boat_speed_knots = speed_l + (speed_h - speed_l) * twa_factor

            return boat_speed_knots * 0.514444

        except (IndexError, TypeError):
            return self._simple_polar_model(wind_speed_ms, twa)

    def _simple_polar_model(self, wind_speed_ms: float, twa: float) -> float:
        """Simple polar performance model when no data available."""
        twa = abs(twa)

        if twa < 25:
            speed_factor = 0.0
        elif twa < 45:
            speed_factor = 0.3
        elif twa < 60:
            speed_factor = 0.5
        elif twa < 90:
            speed_factor = 0.65
        elif twa < 120:
            speed_factor = 0.7
        elif twa < 150:
            speed_factor = 0.65
        elif twa < 170:
            speed_factor = 0.55
        else:
            speed_factor = 0.5

        wind_knots = wind_speed_ms / 0.514444
        if wind_knots < 5.0:
            speed_factor *= 0.3
        elif wind_knots > 25.0:
            speed_factor *= 0.8

        boat_speed = wind_speed_ms * speed_factor

        if self.yacht.max_speed:
            max_speed_ms = self.yacht.max_speed * 0.514444
            boat_speed = min(boat_speed, max_speed_ms)

        boat_speed = max(boat_speed, 0.5)

        return boat_speed

    def _find_interpolation_indices(self, value: float, array: List[float]) -> Tuple[int, int, float]:
        """Find interpolation indices and factor for a value in an array."""
        if not array:
            return 0, 0, 0.0

        if value <= array[0]:
            return 0, 0, 0.0
        if value >= array[-1]:
            return len(array) - 1, len(array) - 1, 0.0

        for i in range(len(array) - 1):
            if array[i] <= value <= array[i + 1]:
                if array[i + 1] - array[i] > 0:
                    factor = (value - array[i]) / (array[i + 1] - array[i])
                else:
                    factor = 0.0
                return i, i + 1, factor

        return len(array) - 1, len(array) - 1, 0.0

    def _apply_current_effect(self, boat_speed: float, heading: float,
                              current_velocity: float, current_direction: float) -> float:
        """Apply ocean current effect on boat speed."""
        if current_velocity < 0.1:
            return boat_speed

        boat_vx = boat_speed * math.sin(math.radians(heading))
        boat_vy = boat_speed * math.cos(math.radians(heading))

        current_vx = current_velocity * math.sin(math.radians(current_direction))
        current_vy = current_velocity * math.cos(math.radians(current_direction))

        total_vx = boat_vx + current_vx
        total_vy = boat_vy + current_vy

        speed_over_ground = math.sqrt(total_vx ** 2 + total_vy ** 2)

        return speed_over_ground

    def _calculate_wave_penalty(self, wave_height: float, wave_direction: float,
                                heading: float) -> float:
        """Calculate speed reduction due to waves."""
        if wave_height < 0.5:
            return 0.0

        size_factor = 1.0 - min(self.yacht_length_m / 50.0, 0.5)

        wave_angle = abs(heading - wave_direction)
        if wave_angle > 180:
            wave_angle = 360 - wave_angle

        if wave_angle < 30:
            angle_factor = 1.0
        elif wave_angle < 60:
            angle_factor = 0.8
        elif wave_angle < 120:
            angle_factor = 1.2
        elif wave_angle < 150:
            angle_factor = 0.6
        else:
            angle_factor = 0.3

        relative_wave_height = wave_height / self.yacht_length_m
        height_factor = min(relative_wave_height * 3.0, 1.0)

        penalty = height_factor * angle_factor * size_factor * 0.4
        return min(penalty, 0.5)

    def _calculate_maneuver_penalty(self, from_heading: float, to_heading: float,
                                    from_twa: float, to_twa: float) -> float:
        """Calculate time penalty for required maneuvers."""
        heading_change = abs(to_heading - from_heading)
        if heading_change > 180:
            heading_change = 360 - heading_change

        penalty = 0.0

        if abs(from_twa) < 90 and abs(to_twa) < 90:
            if (from_twa * to_twa) < 0:
                penalty = self.TACKING_PENALTY

        elif abs(from_twa) > 120 and abs(to_twa) > 120:
            if (from_twa * to_twa) < 0:
                penalty = self.GYBING_PENALTY

        if heading_change > 60:
            penalty += 10.0

        return penalty

    def _calculate_comfort_penalty(self, conditions: SailingConditions) -> float:
        """Calculate penalty for uncomfortable conditions."""
        penalty = 0.0

        relative_wave_discomfort = conditions.wave_height / self.yacht_length_m
        if relative_wave_discomfort > 0.1:
            wave_penalty = (relative_wave_discomfort - 0.1) * 2.0
            penalty += min(wave_penalty, 0.3)

        if self.yacht.max_wind_speed:
            wind_ms = self.yacht.max_wind_speed
            wind_knots = wind_ms / 0.514444
            if conditions.wind_speed > wind_knots:
                penalty += 0.5
            elif conditions.wind_speed > wind_knots * 0.8:
                wind_penalty = (conditions.wind_speed - wind_knots * 0.8) / (wind_knots * 0.2)
                penalty += min(wind_penalty * 0.3, 0.3)
        else:
            if conditions.wind_speed > 30.0:
                wind_penalty = (conditions.wind_speed - 30.0) / 20.0
                penalty += min(wind_penalty, 0.3)

        if conditions.wind_speed < 5.0:
            light_penalty = (5.0 - conditions.wind_speed) / 5.0
            size_adjustment = min(self.yacht_length_m / 30.0, 1.5)
            penalty += min(light_penalty * size_adjustment * 0.3, 0.2)

        if self.yacht.amount_of_crew:
            crew_factor = 1.0 / max(self.yacht.amount_of_crew, 1)
            penalty *= (1.0 + crew_factor * 0.2)

        return min(penalty, 0.5)


class SailingRouter:
    """
    Main routing class that uses heuristics to find optimal sailing routes.
    """

    def __init__(self,
                 navigation_mesh: Dict,
                 weather_data: Dict,
                 yacht: Yacht,
                 heuristics_cls=SailingHeuristics):
        """Initialize router with mesh, weather, and yacht data."""
        self.vertices = np.array(navigation_mesh['vertices'])
        self.triangles = np.array(navigation_mesh['triangles'])
        self.weather_data = weather_data
        self.yacht = yacht
        self.heuristics_cls = heuristics_cls

        self.graph = self._build_navigation_graph()
        self.vertex_tree = KDTree(self.vertices)

        # Przechowuj ostatnie wyniki A*
        self.last_result: Optional[AStarResult] = None

    def _build_navigation_graph(self) -> Dict[int, List[int]]:
        """Build adjacency graph from triangle mesh."""
        graph = {i: set() for i in range(len(self.vertices))}

        for triangle in self.triangles:
            for i in range(3):
                for j in range(3):
                    if i != j:
                        graph[triangle[i]].add(triangle[j])

        return {k: list(v) for k, v in graph.items()}

    def find_nearest_vertex(self, point: Tuple[float, float]) -> int:
        """Find nearest vertex index to a given point."""
        _, idx = self.vertex_tree.query(point)
        return idx

    def find_optimal_route(self,
                           start: Tuple[float, float],
                           goal: Tuple[float, float],
                           weather_mapping: Dict[int, List[int]]) -> List[Tuple[float, float]]:
        """
        Find optimal sailing route using A* with sailing heuristics.
        Returns list of (x, y) waypoints.
        """
        heuristics = self.heuristics_cls(self.yacht, weather_mapping, self.weather_data)

        start_idx = self.find_nearest_vertex(start)
        goal_idx = self.find_nearest_vertex(goal)

        result = self._astar_with_scores(start_idx, goal_idx, heuristics)

        if result is None:
            self.last_result = None
            return []

        self.last_result = result

        path = [tuple(self.vertices[idx]) for idx in result.path_indices]

        if self._calculate_distance(start, path[0]) > 10:
            path.insert(0, start)
        if self._calculate_distance(goal, path[-1]) > 10:
            path.append(goal)

        return path

    def find_optimal_route_with_scores(self,
                                       start: Tuple[float, float],
                                       goal: Tuple[float, float],
                                       weather_mapping: Dict[int, List[int]]) -> Optional[AStarResult]:
        """
        Find optimal route and return full result with scores.
        Use this when you need heuristic scores for storage.
        """
        path = self.find_optimal_route(start, goal, weather_mapping)

        if not path:
            return None

        if self.last_result:
            return AStarResult(
                path=path,
                path_indices=self.last_result.path_indices,
                g_scores=self.last_result.g_scores,
                f_scores=self.last_result.f_scores,
                total_cost=self.last_result.total_cost
            )

        return None

    def _astar_with_scores(self, start_idx: int, goal_idx: int,
                           heuristics: SailingHeuristics) -> Optional[AStarResult]:
        """
        A* pathfinding that returns scores along with path.
        """
        open_set = [(0, start_idx)]

        came_from = {}
        g_score = {start_idx: 0}
        f_score = {start_idx: heuristics.calculate_heuristic_cost(
            tuple(self.vertices[start_idx]),
            tuple(self.vertices[goal_idx]),
            start_idx
        )}

        closed_set = set()

        while open_set:
            current_f, current = heapq.heappop(open_set)

            if current == goal_idx:
                # Reconstruct path
                path_indices = []
                node = current
                while node in came_from:
                    path_indices.append(node)
                    node = came_from[node]
                path_indices.append(start_idx)
                path_indices = list(reversed(path_indices))

                path = [tuple(self.vertices[idx]) for idx in path_indices]

                return AStarResult(
                    path=path,
                    path_indices=path_indices,
                    g_scores=dict(g_score),
                    f_scores=dict(f_score),
                    total_cost=g_score[goal_idx]
                )

            if current in closed_set:
                continue

            closed_set.add(current)

            for neighbor in self.graph.get(current, []):
                if neighbor in closed_set:
                    continue

                previous_heading = None
                if current in came_from:
                    prev_idx = came_from[current]
                    previous_heading = heuristics._calculate_bearing(
                        tuple(self.vertices[prev_idx]),
                        tuple(self.vertices[current])
                    )

                edge_cost = heuristics.calculate_edge_cost(
                    tuple(self.vertices[current]),
                    tuple(self.vertices[neighbor]),
                    current,
                    neighbor,
                    previous_heading
                )

                if edge_cost == float('inf'):
                    continue

                tentative_g = g_score[current] + edge_cost

                if neighbor not in g_score or tentative_g < g_score[neighbor]:
                    came_from[neighbor] = current
                    g_score[neighbor] = tentative_g

                    h_score = heuristics.calculate_heuristic_cost(
                        tuple(self.vertices[neighbor]),
                        tuple(self.vertices[goal_idx]),
                        neighbor
                    )

                    f_score[neighbor] = tentative_g + h_score
                    heapq.heappush(open_set, (f_score[neighbor], neighbor))

        return None

    def _astar(self, start_idx: int, goal_idx: int,
               heuristics: SailingHeuristics) -> List[int]:
        """Legacy method for backward compatibility."""
        result = self._astar_with_scores(start_idx, goal_idx, heuristics)
        return result.path_indices if result else []

    def _calculate_distance(self, p1: Tuple[float, float],
                            p2: Tuple[float, float]) -> float:
        """Calculate Euclidean distance."""
        return math.sqrt((p2[0] - p1[0]) ** 2 + (p2[1] - p1[1]) ** 2)


class SafeHeuristics(SailingHeuristics):
    def __init__(self, yacht, weather_mapping, weather_data, non_navigable):
        super().__init__(yacht, weather_mapping, weather_data)
        self.non_navigable = set(non_navigable)

    def calculate_edge_cost(self, from_vertex, to_vertex, from_idx, to_idx, previous_heading=None):
        if from_idx in self.non_navigable or to_idx in self.non_navigable:
            return float('inf')
        return super().calculate_edge_cost(from_vertex, to_vertex, from_idx, to_idx, previous_heading)