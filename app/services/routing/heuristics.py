from __future__ import annotations

import numpy as np
import math
from typing import Tuple
from typing import Dict
from typing import List
from typing import Optional

from scipy.spatial import KDTree

from app.models.models import Yacht
from app.schemas.SailingConditions import SailingConditions
from app.services.logger import (
    log_edge,
    log_impassable,
    log_weather,
    log_debug,
    log_error
)

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
        self.DEAD_ANGLE = 30.0  # Reduced from 30 to be less restrictive
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
        # Get weather conditions at both vertices
        from_conditions = self._get_conditions_at_vertex(from_idx)
        to_conditions = self._get_conditions_at_vertex(to_idx)

        # Calculate bearing and distance
        bearing = self._calculate_bearing(from_vertex, to_vertex)
        distance = self._calculate_distance(from_vertex, to_vertex)

        # Calculate True Wind Angles
        from_twa = self._calculate_twa(
            previous_heading if previous_heading is not None else bearing,
            from_conditions.wind_direction
        )
        to_twa = self._calculate_twa(bearing, to_conditions.wind_direction)

        # Check if we're trying to sail into no-go zone (upwind)
        if abs(to_twa) < self.DEAD_ANGLE:
            return float('inf')  # Can't sail directly upwind

        # Average conditions for the segment
        # IMPORTANT: Convert wind speed from knots to m/s for boat speed calculation
        avg_wind_speed_knots = (from_conditions.wind_speed + to_conditions.wind_speed) / 2.0
        avg_wind_speed_ms = avg_wind_speed_knots * 0.514444  # knots to m/s
        avg_wave_height = (from_conditions.wave_height + to_conditions.wave_height) / 2.0

        # Get boat speed from polar data (expects wind in m/s)
        boat_speed = self._get_boat_speed(avg_wind_speed_ms, abs(to_twa))

        # Apply current effect (convert current from knots to m/s)
        current_velocity_ms = to_conditions.current_velocity * 0.514444
        boat_speed = self._apply_current_effect(
            boat_speed,
            bearing,
            current_velocity_ms,
            to_conditions.current_direction
        )

        # Apply wave penalty
        wave_penalty = self._calculate_wave_penalty(
            avg_wave_height,
            to_conditions.wave_direction,
            bearing
        )
        boat_speed *= (1.0 - wave_penalty)

        # Ensure minimum speed for numerical stability
        boat_speed = max(boat_speed, 0.5)  # Minimum 0.5 m/s

        # Calculate base time
        time_cost = distance / boat_speed

        # Add maneuver penalties if we have previous heading
        if previous_heading is not None:
            maneuver_penalty = self._calculate_maneuver_penalty(
                previous_heading, bearing, from_twa, to_twa
            )
            time_cost += maneuver_penalty

        # Add comfort penalty for rough conditions
        comfort_penalty = self._calculate_comfort_penalty(to_conditions)
        time_cost *= (1.0 + comfort_penalty)

        log_edge(from_idx, to_idx, to_twa, boat_speed, avg_wind_speed_ms, time_cost)

        if boat_speed <= 0.01:
            log_impassable(from_idx, to_idx, "boat_speed=0")
            return float("inf")
        # Add crew fatigue factor for very long segments
        if distance > 10000:  # More than 10km
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

        # Get average conditions
        conditions = self._get_conditions_at_vertex(current_idx)

        # Optimistic estimate based on conditions
        if self.yacht.max_speed:
            optimistic_speed = self.yacht.max_speed * 0.514444  # knots to m/s
        else:
            optimistic_speed = 5.0  # Default 5 m/s

        # Adjust for wind conditions (wind is in knots)
        if conditions.wind_speed < 5.0:  # Light wind (knots)
            optimistic_speed *= 0.5
        elif conditions.wind_speed > 25.0:  # Strong wind (knots)
            optimistic_speed *= 0.8

        return distance / optimistic_speed

    def _get_conditions_at_vertex(self, vertex_idx: int) -> SailingConditions:
        """Get weather conditions at a navigation vertex."""
        weather_idx = self.nav_to_weather.get(vertex_idx)

        if weather_idx is None:
            log_weather(vertex_idx, None, "NO weather mapping")

        if weather_idx not in self.weather_data:
            log_weather(vertex_idx, weather_idx, "Missing weather data")

        log_weather(vertex_idx, weather_idx, "OK")

        if weather_idx is not None and weather_idx in self.weather_data:
            return SailingConditions.from_weather_data(self.weather_data[weather_idx])

        # Default conditions if no weather data
        return SailingConditions(
            wind_speed=10.0,  # knots
            wind_direction=0.0,
            wave_height=1.0,
            wave_direction=0.0,
            wave_period=5.0,
            current_velocity=0.5,  # knots
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

        # Normalize to -180 to 180
        while twa > 180:
            twa -= 360
        while twa < -180:
            twa += 360

        return twa

    def _get_boat_speed(self, wind_speed_ms: float, twa: float) -> float:
        """
        Get boat speed from polar data for given wind conditions.
        Args:
            wind_speed_ms: Wind speed in m/s
            twa: True Wind Angle in degrees
        Returns:
            Boat speed in m/s
        """
        if not self.yacht.polar_data:
            return self._simple_polar_model(wind_speed_ms, twa)

        # Use actual polar data interpolation
        polar = self.yacht.polar_data

        # Ensure TWA is positive (0-180)
        twa = abs(twa)

        # Get polar arrays
        twa_angles = polar.get('twa_angles', [])
        wind_speeds = polar.get('wind_speeds', [])
        boat_speeds = polar.get('boat_speeds', [])

        if not all([twa_angles, wind_speeds, boat_speeds]):
            return self._simple_polar_model(wind_speed_ms, twa)

        # Convert wind speed to knots for polar lookup
        wind_speed_knots = wind_speed_ms / 0.514444

        # Find interpolation indices
        twa_idx_low, twa_idx_high, twa_factor = self._find_interpolation_indices(
            twa, twa_angles
        )
        ws_idx_low, ws_idx_high, ws_factor = self._find_interpolation_indices(
            wind_speed_knots, wind_speeds
        )

        try:
            # Bilinear interpolation
            speed_ll = boat_speeds[twa_idx_low][ws_idx_low]
            speed_lh = boat_speeds[twa_idx_low][ws_idx_high]
            speed_hl = boat_speeds[twa_idx_high][ws_idx_low]
            speed_hh = boat_speeds[twa_idx_high][ws_idx_high]

            speed_l = speed_ll + (speed_lh - speed_ll) * ws_factor
            speed_h = speed_hl + (speed_hh - speed_hl) * ws_factor
            boat_speed_knots = speed_l + (speed_h - speed_l) * twa_factor

            # Convert knots to m/s
            return boat_speed_knots * 0.514444

        except (IndexError, TypeError):
            return self._simple_polar_model(wind_speed_ms, twa)

    def _simple_polar_model(self, wind_speed_ms: float, twa: float) -> float:
        """
        Simple polar performance model when no data available.
        Args:
            wind_speed_ms: Wind speed in m/s
            twa: True Wind Angle in degrees
        Returns:
            Boat speed in m/s
        """
        twa = abs(twa)

        # Base speed as fraction of wind speed
        if twa < 25:
            speed_factor = 0.0  # Can't sail too close to wind
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
            speed_factor = 0.55  # Slower downwind
        else:
            speed_factor = 0.5  # Dead downwind

        # Apply wind speed limits
        wind_knots = wind_speed_ms / 0.514444
        if wind_knots < 5.0:  # Very light wind
            speed_factor *= 0.3
        elif wind_knots > 25.0:  # Strong wind
            speed_factor *= 0.8

        boat_speed = wind_speed_ms * speed_factor

        # Cap at max speed if available
        if self.yacht.max_speed:
            max_speed_ms = self.yacht.max_speed * 0.514444
            boat_speed = min(boat_speed, max_speed_ms)

        # Ensure minimum speed
        boat_speed = max(boat_speed, 0.5)  # At least 0.5 m/s

        return boat_speed

    def _find_interpolation_indices(self, value: float, array: List[float]) -> Tuple[int, int, float]:
        """
        Find interpolation indices and factor for a value in an array.
        Returns (low_idx, high_idx, interpolation_factor)
        """
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
        """
        Apply ocean current effect on boat speed.
        Returns adjusted speed over ground.
        """
        if current_velocity < 0.1:
            return boat_speed

        # Convert to vectors
        boat_vx = boat_speed * math.sin(math.radians(heading))
        boat_vy = boat_speed * math.cos(math.radians(heading))

        current_vx = current_velocity * math.sin(math.radians(current_direction))
        current_vy = current_velocity * math.cos(math.radians(current_direction))

        # Add vectors
        total_vx = boat_vx + current_vx
        total_vy = boat_vy + current_vy

        # Calculate resultant speed
        speed_over_ground = math.sqrt(total_vx ** 2 + total_vy ** 2)

        return speed_over_ground

    def _calculate_wave_penalty(self, wave_height: float, wave_direction: float,
                                heading: float) -> float:
        """
        Calculate speed reduction due to waves.
        Returns penalty factor (0.0 to 0.5).
        """
        if wave_height < 0.5:
            return 0.0

        # Size factor - larger yachts are less affected by waves
        size_factor = 1.0 - min(self.yacht_length_m / 50.0, 0.5)

        # Wave angle relative to boat
        wave_angle = abs(heading - wave_direction)
        if wave_angle > 180:
            wave_angle = 360 - wave_angle

        # Angle factor
        if wave_angle < 30:  # Head seas
            angle_factor = 1.0
        elif wave_angle < 60:
            angle_factor = 0.8
        elif wave_angle < 120:  # Beam seas
            angle_factor = 1.2
        elif wave_angle < 150:
            angle_factor = 0.6
        else:  # Following seas
            angle_factor = 0.3

        # Height factor
        relative_wave_height = wave_height / self.yacht_length_m
        height_factor = min(relative_wave_height * 3.0, 1.0)

        penalty = height_factor * angle_factor * size_factor * 0.4
        return min(penalty, 0.5)  # Max 50% speed reduction

    def _calculate_maneuver_penalty(self, from_heading: float, to_heading: float,
                                    from_twa: float, to_twa: float) -> float:
        """
        Calculate time penalty for required maneuvers.
        Returns penalty in seconds.
        """
        # Calculate heading change
        heading_change = abs(to_heading - from_heading)
        if heading_change > 180:
            heading_change = 360 - heading_change

        penalty = 0.0

        # Tacking: going through the wind (upwind, TWA < 90)
        if abs(from_twa) < 90 and abs(to_twa) < 90:
            # Check if we're changing sides relative to wind
            if (from_twa * to_twa) < 0:  # Different signs = crossing through wind
                penalty = self.TACKING_PENALTY

        # Gybing: going through downwind (TWA > 120)
        elif abs(from_twa) > 120 and abs(to_twa) > 120:
            # Check if we're changing sides downwind
            if (from_twa * to_twa) < 0:  # Different signs = gybing
                penalty = self.GYBING_PENALTY

        # Additional penalty for large heading changes
        if heading_change > 60:
            penalty += 10.0  # 10 seconds for major course change

        return penalty

    def _calculate_comfort_penalty(self, conditions: SailingConditions) -> float:
        """
        Calculate penalty for uncomfortable conditions.
        Returns penalty factor (0.0 to 0.5).
        """
        penalty = 0.0

        # Wave height discomfort
        relative_wave_discomfort = conditions.wave_height / self.yacht_length_m
        if relative_wave_discomfort > 0.1:
            wave_penalty = (relative_wave_discomfort - 0.1) * 2.0
            penalty += min(wave_penalty, 0.3)

        # Strong wind discomfort (wind is in knots)
        if self.yacht.max_wind_speed:
            wind_ms = self.yacht.max_wind_speed  # Already in m/s
            wind_knots = wind_ms / 0.514444
            if conditions.wind_speed > wind_knots:
                penalty += 0.5
            elif conditions.wind_speed > wind_knots * 0.8:
                wind_penalty = (conditions.wind_speed - wind_knots * 0.8) / (wind_knots * 0.2)
                penalty += min(wind_penalty * 0.3, 0.3)
        else:
            # Default wind limits if not specified
            if conditions.wind_speed > 30.0:  # Over 30 knots
                wind_penalty = (conditions.wind_speed - 30.0) / 20.0
                penalty += min(wind_penalty, 0.3)

        # Light wind frustration
        if conditions.wind_speed < 5.0:  # Less than 5 knots
            light_penalty = (5.0 - conditions.wind_speed) / 5.0
            size_adjustment = min(self.yacht_length_m / 30.0, 1.5)
            penalty += min(light_penalty * size_adjustment * 0.3, 0.2)

        # Crew fatigue factor
        if self.yacht.amount_of_crew:
            crew_factor = 1.0 / max(self.yacht.amount_of_crew, 1)
            penalty *= (1.0 + crew_factor * 0.2)

        return min(penalty, 0.5)  # Max 50% penalty


class SailingRouter:
    """
    Main routing class that uses heuristics to find optimal sailing routes.
    """

    def __init__(self,
                 navigation_mesh: Dict,
                 weather_data: Dict,
                 yacht: Yacht,
                 heuristics_cls = SailingHeuristics):
        """
        Initialize router with mesh, weather, and yacht data.
        """
        self.vertices = np.array(navigation_mesh['vertices'])
        self.triangles = np.array(navigation_mesh['triangles'])
        self.weather_data = weather_data
        self.yacht = yacht
        self.heuristics_cls = heuristics_cls

        # Build navigation graph from triangles
        self.graph = self._build_navigation_graph()

        # Create KDTree for nearest vertex queries
        self.vertex_tree = KDTree(self.vertices)

    def _build_navigation_graph(self) -> Dict[int, List[int]]:
        """
        Build adjacency graph from triangle mesh.
        Returns dict: vertex_idx -> list of connected vertex indices
        """
        graph = {i: set() for i in range(len(self.vertices))}

        for triangle in self.triangles:
            # Connect all vertices in triangle
            for i in range(3):
                for j in range(3):
                    if i != j:
                        graph[triangle[i]].add(triangle[j])

        # Convert sets to lists
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
        # Initialize heuristics
        heuristics = self.heuristics_cls(self.yacht, weather_mapping, self.weather_data)

        # Find nearest vertices
        start_idx = self.find_nearest_vertex(start)
        goal_idx = self.find_nearest_vertex(goal)

        # Run A* algorithm
        path_indices = self._astar(start_idx, goal_idx, heuristics)

        if not path_indices:
            return []

        # Convert to coordinates
        path = [tuple(self.vertices[idx]) for idx in path_indices]

        # Add original start and goal if different from nearest vertices
        if self._calculate_distance(start, path[0]) > 10:
            path.insert(0, start)
        if self._calculate_distance(goal, path[-1]) > 10:
            path.append(goal)

        return path

    def _astar(self, start_idx: int, goal_idx: int,
               heuristics: SailingHeuristics) -> List[int]:
        """
        A* pathfinding with sailing-specific heuristics.
        Returns list of vertex indices forming the path.
        """
        import heapq

        # Priority queue: (f_score, vertex_idx)
        open_set = [(0, start_idx)]

        # Maps for tracking
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
            log_debug(f"Checking edges for vertex {current}")
            if current == goal_idx:
                # Reconstruct path
                path = []
                while current in came_from:
                    path.append(current)
                    current = came_from[current]
                path.append(start_idx)
                return list(reversed(path))

            if current in closed_set:
                continue

            closed_set.add(current)

            # Check all neighbors
            for neighbor in self.graph.get(current, []):
                log_debug(f"Checking neighbor {neighbor} from {current}")
                if neighbor in closed_set:
                    continue

                # Calculate tentative g score
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

                # Skip if infinite cost (impassable)
                if edge_cost == float('inf'):
                    log_impassable(current, neighbor, "cost=inf")
                    continue
                else:
                    log_debug(f"edge_cost OK: {current}->{neighbor} cost={edge_cost:.2f}")

                tentative_g = g_score[current] + edge_cost

                if neighbor not in g_score or tentative_g < g_score[neighbor]:
                    # This path is better
                    came_from[neighbor] = current
                    g_score[neighbor] = tentative_g

                    h_score = heuristics.calculate_heuristic_cost(
                        tuple(self.vertices[neighbor]),
                        tuple(self.vertices[goal_idx]),
                        neighbor
                    )

                    f_score[neighbor] = tentative_g + h_score
                    heapq.heappush(open_set, (f_score[neighbor], neighbor))

        # No path found
        return []

    def _calculate_distance(self, p1: Tuple[float, float],
                            p2: Tuple[float, float]) -> float:
        """Calculate Euclidean distance."""
        return math.sqrt((p2[0] - p1[0]) ** 2 + (p2[1] - p1[1]) ** 2)