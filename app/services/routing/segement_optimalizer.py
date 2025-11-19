from __future__ import annotations

import math
import numpy as np
from typing import List, Dict, Any, Tuple
from dataclasses import dataclass
from datetime import datetime


@dataclass
class OptimizedSegment:
    """Represents an optimized route segment combining multiple raw segments"""
    from_point: Tuple[float, float]  # (x, y) in local CRS
    to_point: Tuple[float, float]
    from_point_wgs84: Tuple[float, float]  # (lon, lat)
    to_point_wgs84: Tuple[float, float]

    # Averaged values
    avg_bearing: float
    avg_boat_speed_knots: float
    avg_wind_speed_knots: float
    avg_wind_direction: float
    avg_wave_height_m: float
    avg_twa: float

    # Accumulated values
    total_distance_nm: float
    total_time_hours: float

    # Segment info
    raw_segments_count: int
    predominant_point_of_sail: str

    # For maneuvers
    has_tack: bool = False
    has_jibe: bool = False


class SegmentOptimizer:
    """Optimizes route segments by combining those with similar bearings"""

    def __init__(self, bearing_tolerance: float = 5.0):
        """
        Initialize optimizer

        Args:
            bearing_tolerance: Maximum bearing difference in degrees to combine segments
        """
        self.bearing_tolerance = bearing_tolerance

    def _detect_maneuver_at_end(self, current_segments: List[Dict[str, Any]],
                                next_segment: Dict[str, Any] = None) -> str:
        """
        Detect maneuver at the END of current segment group
        Returns: "TACK", "JIBE" or None
        """
        if not next_segment or not current_segments:
            return None

        # Get TWA at end of current group and start of next
        last_twa = current_segments[-1].get('twa', 0)
        next_twa = next_segment.get('twa', 0)

        # Check for sign change in TWA
        if (last_twa > 0 and next_twa < 0) or (last_twa < 0 and next_twa > 0):
            # Tack (upwind maneuver)
            if abs(last_twa) < 90 or abs(next_twa) < 90:
                return "TACK"
            # Jibe (downwind maneuver)
            elif abs(last_twa) > 120 and abs(next_twa) > 120:
                return "JIBE"

        return None

    # Zmodyfikuj metodę optimize_segments:
    def optimize_segments(self, raw_segments: List[Dict[str, Any]]) -> List[OptimizedSegment]:
        """
        Optimize raw segments by combining those with similar bearings
        """
        if not raw_segments:
            return []

        optimized = []
        current_group = [raw_segments[0]]

        for i in range(1, len(raw_segments)):
            segment = raw_segments[i]

            # Check if bearing is similar to the average of current group
            avg_bearing = self._calculate_average_bearing(current_group)
            bearing_diff = self._calculate_bearing_difference(
                avg_bearing,
                segment['bearing']
            )

            # Check for maneuver at transition
            has_maneuver = self._detect_maneuver(
                current_group[-1] if current_group else None,
                segment
            )

            if bearing_diff <= self.bearing_tolerance and not has_maneuver:
                # Add to current group
                current_group.append(segment)
            else:
                # Detect maneuver at END of current group before creating segment
                maneuver_type = self._detect_maneuver_at_end(current_group, segment)

                # Create optimized segment from current group
                if current_group:
                    opt_segment = self._create_optimized_segment(current_group)
                    # Add maneuver info
                    if maneuver_type == "TACK":
                        opt_segment.has_tack = True
                    elif maneuver_type == "JIBE":
                        opt_segment.has_jibe = True
                    optimized.append(opt_segment)

                # Start new group
                current_group = [segment]

        # Don't forget the last group (no maneuver at the end)
        if current_group:
            optimized.append(self._create_optimized_segment(current_group))

        return optimized

    def _calculate_bearing_difference(self, bearing1: float, bearing2: float) -> float:
        """Calculate the minimum difference between two bearings"""
        diff = abs(bearing1 - bearing2)
        if diff > 180:
            diff = 360 - diff
        return diff

    def _calculate_average_bearing(self, segments: List[Dict[str, Any]]) -> float:
        """Calculate weighted average bearing based on distance"""
        if not segments:
            return 0.0

        # Use vector averaging for bearings
        total_distance = sum(s['distance_nm'] for s in segments)
        if total_distance == 0:
            return segments[0]['bearing']

        x_component = 0.0
        y_component = 0.0

        for seg in segments:
            weight = seg['distance_nm'] / total_distance
            bearing_rad = math.radians(seg['bearing'])
            x_component += weight * math.sin(bearing_rad)
            y_component += weight * math.cos(bearing_rad)

        avg_bearing = math.degrees(math.atan2(x_component, y_component))
        return (avg_bearing + 360) % 360

    def _detect_maneuver(self, prev_segment: Dict[str, Any],
                         curr_segment: Dict[str, Any]) -> bool:
        """
        Detect if there's a tack or jibe between segments
        """
        if not prev_segment:
            return False

        prev_twa = prev_segment.get('twa', 0)
        curr_twa = curr_segment.get('twa', 0)

        # Check for sign change in TWA (crossing through wind)
        if (prev_twa > 0 and curr_twa < 0) or (prev_twa < 0 and curr_twa > 0):
            # Tack (upwind maneuver)
            if abs(prev_twa) < 90 or abs(curr_twa) < 90:
                return True
            # Jibe (downwind maneuver)
            if abs(prev_twa) > 120 and abs(curr_twa) > 120:
                return True

        return False

    def _create_optimized_segment(self, segments: List[Dict[str, Any]]) -> OptimizedSegment:
        """Create an optimized segment from a group of raw segments"""

        # Get start and end points
        from_point = (segments[0]['from']['x'], segments[0]['from']['y'])
        to_point = (segments[-1]['to']['x'], segments[-1]['to']['y'])
        from_point_wgs84 = (segments[0]['from']['lon'], segments[0]['from']['lat'])
        to_point_wgs84 = (segments[-1]['to']['lon'], segments[-1]['to']['lat'])

        # Calculate totals
        total_distance_nm = sum(s['distance_nm'] for s in segments)
        total_time_seconds = sum(s['time_seconds'] for s in segments)
        total_time_hours = total_time_seconds / 3600.0

        # Calculate weighted averages (weighted by distance)
        weights = [s['distance_nm'] / total_distance_nm if total_distance_nm > 0 else 1.0 / len(segments)
                   for s in segments]

        avg_bearing = self._calculate_average_bearing(segments)
        avg_boat_speed = sum(s['boat_speed_knots'] * w for s, w in zip(segments, weights))
        avg_wind_speed = sum(s['wind_speed_knots'] * w for s, w in zip(segments, weights))
        avg_wind_direction = self._calculate_weighted_average_direction(
            [s['wind_direction'] for s in segments], weights
        )
        avg_wave_height = sum(s['wave_height_m'] * w for s, w in zip(segments, weights))
        avg_twa = sum(s['twa'] * w for s, w in zip(segments, weights))

        # Determine predominant point of sail
        point_of_sail_counts = {}
        for seg in segments:
            pos = seg.get('point_of_sail', 'unknown')
            point_of_sail_counts[pos] = point_of_sail_counts.get(pos, 0) + seg['distance_nm']

        predominant_pos = max(point_of_sail_counts.keys(),
                              key=lambda k: point_of_sail_counts[k])

        # Check for maneuvers in the group
        has_tack = False
        has_jibe = False

        for i in range(1, len(segments)):
            if self._detect_maneuver(segments[i - 1], segments[i]):
                prev_twa = segments[i - 1]['twa']
                curr_twa = segments[i]['twa']

                if abs(prev_twa) < 90 or abs(curr_twa) < 90:
                    has_tack = True
                elif abs(prev_twa) > 120 and abs(curr_twa) > 120:
                    has_jibe = True

        return OptimizedSegment(
            from_point=from_point,
            to_point=to_point,
            from_point_wgs84=from_point_wgs84,
            to_point_wgs84=to_point_wgs84,
            avg_bearing=avg_bearing,
            avg_boat_speed_knots=avg_boat_speed,
            avg_wind_speed_knots=avg_wind_speed,
            avg_wind_direction=avg_wind_direction,
            avg_wave_height_m=avg_wave_height,
            avg_twa=avg_twa,
            total_distance_nm=total_distance_nm,
            total_time_hours=total_time_hours,
            raw_segments_count=len(segments),
            predominant_point_of_sail=predominant_pos,
            has_tack=has_tack,
            has_jibe=has_jibe
        )

    def _calculate_weighted_average_direction(self, directions: List[float],
                                              weights: List[float]) -> float:
        """Calculate weighted average of directions (handles circular averaging)"""
        x_component = 0.0
        y_component = 0.0

        for direction, weight in zip(directions, weights):
            rad = math.radians(direction)
            x_component += weight * math.sin(rad)
            y_component += weight * math.cos(rad)

        avg_direction = math.degrees(math.atan2(x_component, y_component))
        return (avg_direction + 360) % 360