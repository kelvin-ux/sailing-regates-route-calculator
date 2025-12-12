from __future__ import annotations

import math
from typing import List, Any, Dict, Optional
from app.schemas.segement import OptimizedSegment

BEARING_FOR_SAME_COURSE: float = 5.0
MIN_SEGMENT_LENGTH_NM: float = 0.1
SHORT_SEGMENT_TOLERANCE: float = 30.0


class SegmentOptimizer:
    def __init__(self, bearing_tolerance: float = BEARING_FOR_SAME_COURSE, min_segment_length_nm: float = MIN_SEGMENT_LENGTH_NM):
        self.bearing_tolerance = bearing_tolerance
        self.min_segment_length_nm = min_segment_length_nm

    def optimize_segments(self, raw_segments: List[Dict[str, Any]]) -> List[OptimizedSegment]:
        if not raw_segments:
            return []

        optimized: List[OptimizedSegment] = []
        current_group = [raw_segments[0]]

        for i in range(1, len(raw_segments)):
            prev_segment = raw_segments[i - 1]
            segment = raw_segments[i]

            avg_bearing = self._calculate_circular_mean(
                [s['bearing'] for s in current_group],
                [s['distance_nm'] for s in current_group]
            )

            bearing_diff = self._calculate_bearing_difference(avg_bearing, segment['bearing'])
            maneuver_type = self._detect_maneuver_type(prev_segment, segment)

            if bearing_diff <= self.bearing_tolerance and maneuver_type is None:
                current_group.append(segment)
            else:
                opt_segment = self._create_optimized_segment(current_group)

                if maneuver_type == "TACK":
                    opt_segment.has_tack = True
                elif maneuver_type == "JIBE":
                    opt_segment.has_jibe = True

                optimized.append(opt_segment)
                current_group = [segment]

        if current_group:
            optimized.append(self._create_optimized_segment(current_group))

        return self._enforce_minimum_length(optimized)

    def _enforce_minimum_length(self, segments: List[OptimizedSegment]) -> List[OptimizedSegment]:
        if not segments:
            return []

        merged_results = [segments[0]]
        for i in range(1, len(segments)):
            current = segments[i]
            prev = merged_results[-1]

            should_merge = False
            bearing_diff = self._calculate_bearing_difference(prev.avg_bearing, current.avg_bearing)

            if prev.total_distance_nm < self.min_segment_length_nm or current.total_distance_nm < self.min_segment_length_nm:
                if bearing_diff < SHORT_SEGMENT_TOLERANCE:
                    if not self._is_maneuver_between_optimized(prev, current):
                        should_merge = True

            if should_merge:
                merged_segment = self._merge_two_segments(prev, current)
                merged_results[-1] = merged_segment
            else:
                merged_results.append(current)

        if len(merged_results) > 1 and merged_results[-1].total_distance_nm < self.min_segment_length_nm:
            prev = merged_results[-2]
            last = merged_results[-1]
            bearing_diff = self._calculate_bearing_difference(prev.avg_bearing, last.avg_bearing)

            if bearing_diff < SHORT_SEGMENT_TOLERANCE and not self._is_maneuver_between_optimized(prev, last):
                merged_results[-2] = self._merge_two_segments(prev, last)
                merged_results.pop()

        return merged_results

    def _is_maneuver_between_optimized(self, s1: OptimizedSegment, s2: OptimizedSegment) -> bool:
        twa1 = s1.avg_twa
        twa2 = s2.avg_twa

        if (twa1 > 0 and twa2 < 0) or (twa1 < 0 and twa2 > 0):
            return True
        return False

    def _merge_two_segments(self, s1: OptimizedSegment, s2: OptimizedSegment) -> OptimizedSegment:
        dist1 = s1.total_distance_nm
        dist2 = s2.total_distance_nm
        total_dist = dist1 + dist2
        total_time = s1.total_time_hours + s2.total_time_hours

        w1 = dist1 / total_dist if total_dist > 0 else 0.5
        w2 = dist2 / total_dist if total_dist > 0 else 0.5

        avg_bearing = self._calculate_circular_mean([s1.avg_bearing, s2.avg_bearing], [dist1, dist2])
        avg_wind_dir = self._calculate_circular_mean([s1.avg_wind_direction, s2.avg_wind_direction], [dist1, dist2])

        avg_boat_speed = s1.avg_boat_speed_knots * w1 + s2.avg_boat_speed_knots * w2
        avg_wind_speed = s1.avg_wind_speed_knots * w1 + s2.avg_wind_speed_knots * w2
        avg_wave_height = s1.avg_wave_height_m * w1 + s2.avg_wave_height_m * w2
        avg_twa = s1.avg_twa * w1 + s2.avg_twa * w2

        return OptimizedSegment(
            from_point=s1.from_point,
            to_point=s2.to_point,
            from_point_wgs84=s1.from_point_wgs84,
            to_point_wgs84=s2.to_point_wgs84,
            avg_bearing=avg_bearing,
            avg_boat_speed_knots=avg_boat_speed,
            avg_wind_speed_knots=avg_wind_speed,
            avg_wind_direction=avg_wind_dir,
            avg_wave_height_m=avg_wave_height,
            avg_twa=avg_twa,
            total_distance_nm=total_dist,
            total_time_hours=total_time,
            raw_segments_count=s1.raw_segments_count + s2.raw_segments_count,
            predominant_point_of_sail=s1.predominant_point_of_sail if dist1 >= dist2 else s2.predominant_point_of_sail,
            has_tack=s1.has_tack or s2.has_tack,
            has_jibe=s1.has_jibe or s2.has_jibe
        )

    def _detect_maneuver_type(self, prev_seg: Dict[str, Any], curr_seg: Dict[str, Any]) -> Optional[str]:
        if not prev_seg or not curr_seg:
            return None

        prev_twa = prev_seg.get('twa', 0)
        curr_twa = curr_seg.get('twa', 0)

        if (prev_twa > 0 and curr_twa < 0) or (prev_twa < 0 and curr_twa > 0):
            if abs(prev_twa) < 90 or abs(curr_twa) < 90:
                return "TACK"
            if abs(prev_twa) > 120 and abs(curr_twa) > 120:
                return "JIBE"

        return None

    def _calculate_bearing_difference(self, bearing1: float, bearing2: float) -> float:
        diff = abs(bearing1 - bearing2)
        return 360 - diff if diff > 180 else diff

    def _calculate_circular_mean(self, values: List[float], weights: List[float] = None) -> float:
        if not values:
            return 0.0

        if weights is None:
            weights = [1.0] * len(values)

        total_weight = sum(weights)
        if total_weight == 0:
            return values[0]

        x_component = 0.0
        y_component = 0.0

        for val, w in zip(values, weights):
            rad = math.radians(val)
            norm_w = w / total_weight
            x_component += norm_w * math.sin(rad)
            y_component += norm_w * math.cos(rad)

        avg_val = math.degrees(math.atan2(x_component, y_component))
        return (avg_val + 360) % 360

    def _create_optimized_segment(self, segments: List[Dict[str, Any]]) -> OptimizedSegment:
        if not segments:
            raise ValueError("Cannot optimize empty segment list")

        first = segments[0]
        last = segments[-1]

        total_distance_nm = 0.0
        total_time_seconds = 0.0

        bearings = []
        wind_directions = []
        weights = []
        point_of_sail_counts = {}

        sum_boat_speed = 0.0
        sum_wind_speed = 0.0
        sum_wave_height = 0.0
        sum_twa = 0.0

        has_tack = False
        has_jibe = False

        for i, seg in enumerate(segments):
            dist = seg['distance_nm']
            total_distance_nm += dist
            total_time_seconds += seg['time_seconds']

            bearings.append(seg['bearing'])
            wind_directions.append(seg['wind_direction'])
            weights.append(dist)

            pos = seg.get('point_of_sail', 'unknown')
            point_of_sail_counts[pos] = point_of_sail_counts.get(pos, 0) + dist

            sum_boat_speed += seg['boat_speed_knots'] * dist
            sum_wind_speed += seg['wind_speed_knots'] * dist
            sum_wave_height += seg['wave_height_m'] * dist
            sum_twa += seg['twa'] * dist

            if i > 0:
                m_type = self._detect_maneuver_type(segments[i - 1], seg)
                if m_type == "TACK":
                    has_tack = True
                elif m_type == "JIBE":
                    has_jibe = True

        avg_bearing = self._calculate_circular_mean(bearings, weights)
        avg_wind_direction = self._calculate_circular_mean(wind_directions, weights)

        if total_distance_nm > 0:
            avg_boat_speed = sum_boat_speed / total_distance_nm
            avg_wind_speed = sum_wind_speed / total_distance_nm
            avg_wave_height = sum_wave_height / total_distance_nm
            avg_twa = sum_twa / total_distance_nm
        else:
            avg_boat_speed = first['boat_speed_knots']
            avg_wind_speed = first['wind_speed_knots']
            avg_wave_height = first['wave_height_m']
            avg_twa = first['twa']

        predominant_pos = max(point_of_sail_counts.keys(), key=lambda k: point_of_sail_counts[k])

        return OptimizedSegment(
            from_point=(first['from']['x'], first['from']['y']),
            to_point=(last['to']['x'], last['to']['y']),
            from_point_wgs84=(first['from']['lon'], first['from']['lat']),
            to_point_wgs84=(last['to']['lon'], last['to']['lat']),
            avg_bearing=avg_bearing,
            avg_boat_speed_knots=avg_boat_speed,
            avg_wind_speed_knots=avg_wind_speed,
            avg_wind_direction=avg_wind_direction,
            avg_wave_height_m=avg_wave_height,
            avg_twa=avg_twa,
            total_distance_nm=total_distance_nm,
            total_time_hours=total_time_seconds / 3600.0,
            raw_segments_count=len(segments),
            predominant_point_of_sail=predominant_pos,
            has_tack=has_tack,
            has_jibe=has_jibe
        )