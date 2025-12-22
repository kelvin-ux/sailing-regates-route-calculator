from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
from enum import Enum
import math
from datetime import datetime, timedelta


class DifficultyLevel(str, Enum):
    VERY_EASY = "very_easy"      # 1-2
    EASY = "easy"                 # 3-4
    MODERATE = "moderate"         # 5-6
    DIFFICULT = "difficult"       # 7-8
    VERY_DIFFICULT = "very_difficult"  # 9-10


@dataclass
class DifficultyFactors:
    wind_speed_score: float = 0.0
    wind_gust_score: float = 0.0
    wave_height_score: float = 0.0
    wind_consistency_score: float = 0.0

    distance_score: float = 0.0
    tack_count_score: float = 0.0
    jibe_count_score: float = 0.0
    maneuver_density_score: float = 0.0
    upwind_ratio_score: float = 0.0

    night_sailing_score: float = 0.0
    course_complexity_score: float = 0.0

    weights: Dict[str, float] = field(default_factory=lambda: {
        # Meteo - 40%
        "wind_speed": 0.15,
        "wind_gust": 0.08,
        "wave_height": 0.12,
        "wind_consistency": 0.05,
        # Geometria - 45%
        "distance": 0.10,
        "tack_count": 0.12,
        "jibe_count": 0.08,
        "maneuver_density": 0.10,
        "upwind_ratio": 0.05,
        # Nawigacja - 15%
        "night_sailing": 0.08,
        "course_complexity": 0.07,
    })

    def calculate_total(self) -> float:
        weighted_sum = (
            self.wind_speed_score * self.weights["wind_speed"] +
            self.wind_gust_score * self.weights["wind_gust"] +
            self.wave_height_score * self.weights["wave_height"] +
            self.wind_consistency_score * self.weights["wind_consistency"] +
            self.distance_score * self.weights["distance"] +
            self.tack_count_score * self.weights["tack_count"] +
            self.jibe_count_score * self.weights["jibe_count"] +
            self.maneuver_density_score * self.weights["maneuver_density"] +
            self.upwind_ratio_score * self.weights["upwind_ratio"] +
            self.night_sailing_score * self.weights["night_sailing"] +
            self.course_complexity_score * self.weights["course_complexity"]
        )

        return max(1.0, min(10.0, weighted_sum))

    def get_level(self) -> DifficultyLevel:
        total = self.calculate_total()
        if total <= 2:
            return DifficultyLevel.VERY_EASY
        elif total <= 4:
            return DifficultyLevel.EASY
        elif total <= 6:
            return DifficultyLevel.MODERATE
        elif total <= 8:
            return DifficultyLevel.DIFFICULT
        else:
            return DifficultyLevel.VERY_DIFFICULT

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_score": round(self.calculate_total(), 2),
            "level": self.get_level().value,
            "breakdown": {
                "meteo": {
                    "wind_speed": round(self.wind_speed_score, 2),
                    "wind_gust": round(self.wind_gust_score, 2),
                    "wave_height": round(self.wave_height_score, 2),
                    "wind_consistency": round(self.wind_consistency_score, 2),
                    "subtotal": round(
                        (self.wind_speed_score * self.weights["wind_speed"] +
                         self.wind_gust_score * self.weights["wind_gust"] +
                         self.wave_height_score * self.weights["wave_height"] +
                         self.wind_consistency_score * self.weights["wind_consistency"]) / 0.40 * 10, 2
                    )
                },
                "geometry": {
                    "distance": round(self.distance_score, 2),
                    "tack_count": round(self.tack_count_score, 2),
                    "jibe_count": round(self.jibe_count_score, 2),
                    "maneuver_density": round(self.maneuver_density_score, 2),
                    "upwind_ratio": round(self.upwind_ratio_score, 2),
                    "subtotal": round(
                        (self.distance_score * self.weights["distance"] +
                         self.tack_count_score * self.weights["tack_count"] +
                         self.jibe_count_score * self.weights["jibe_count"] +
                         self.maneuver_density_score * self.weights["maneuver_density"] +
                         self.upwind_ratio_score * self.weights["upwind_ratio"]) / 0.45 * 10, 2
                    )
                },
                "navigation": {
                    "night_sailing": round(self.night_sailing_score, 2),
                    "course_complexity": round(self.course_complexity_score, 2),
                    "subtotal": round(
                        (self.night_sailing_score * self.weights["night_sailing"] +
                         self.course_complexity_score * self.weights["course_complexity"]) / 0.15 * 10, 2
                    )
                }
            },
            "weights": self.weights
        }


class RouteDifficultyCalculator:
    WIND_OPTIMAL_MIN = 8.0
    WIND_OPTIMAL_MAX = 18.0
    WIND_DANGEROUS = 30.0

    WAVE_COMFORTABLE = 0.5
    WAVE_MODERATE = 1.5
    WAVE_DIFFICULT = 2.5
    WAVE_DANGEROUS = 4.0

    DISTANCE_SHORT = 10.0
    DISTANCE_MEDIUM = 30.0
    DISTANCE_LONG = 60.0
    DISTANCE_VERY_LONG = 100.0

    TACKS_FEW = 3
    TACKS_MODERATE = 8
    TACKS_MANY = 15
    TACKS_EXTREME = 25

    def calculate(
        self,
        segments: List[Dict[str, Any]],
        tacks_count: int,
        jibes_count: int,
        total_distance_nm: float,
        total_time_hours: float,
        departure_time: Optional[Any] = None,
        include_night: bool = True
    ) -> DifficultyFactors:
        factors = DifficultyFactors()

        if not segments:
            return factors

        wind_speeds = [s.get('wind_speed_knots', 0) for s in segments]
        wave_heights = [s.get('wave_height_m', 0) for s in segments]
        wind_directions = [s.get('wind_direction', 0) for s in segments]
        twas = [s.get('twa', 0) for s in segments]
        bearings = [s.get('bearing', 0) for s in segments]

        factors.wind_speed_score = self._calc_wind_speed_score(wind_speeds)
        factors.wind_gust_score = self._calc_wind_gust_score(wind_speeds)
        factors.wave_height_score = self._calc_wave_score(wave_heights)
        factors.wind_consistency_score = self._calc_wind_consistency_score(wind_directions)

        factors.distance_score = self._calc_distance_score(total_distance_nm)
        factors.tack_count_score = self._calc_tack_score(tacks_count)
        factors.jibe_count_score = self._calc_jibe_score(jibes_count)
        factors.maneuver_density_score = self._calc_maneuver_density_score(
            tacks_count + jibes_count, total_distance_nm
        )
        factors.upwind_ratio_score = self._calc_upwind_ratio_score(twas)

        if include_night and departure_time and total_time_hours > 0:
            factors.night_sailing_score = self._calc_night_score(
                departure_time, total_time_hours
            )
        factors.course_complexity_score = self._calc_course_complexity_score(bearings)

        return factors

    def calculate_for_variants(
        self,
        variants: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        if not variants:
            return {
                "overall": DifficultyFactors(),
                "best_variant": None,
                "worst_variant": None,
                "variants": []
            }

        variant_factors = []

        for v in variants:
            factors = self.calculate(
                segments=v.get('segments', []),
                tacks_count=v.get('tacks_count', 0),
                jibes_count=v.get('jibes_count', 0),
                total_distance_nm=v.get('total_distance_nm', 0),
                total_time_hours=v.get('total_time_hours', 0),
                departure_time=v.get('departure_time')
            )
            variant_factors.append(factors)

        scores = [f.calculate_total() for f in variant_factors]
        best_idx = scores.index(min(scores))
        worst_idx = scores.index(max(scores))
        avg_score = sum(scores) / len(scores)
        overall = self._average_factors(variant_factors)

        return {
            "overall": overall,
            "overall_score": round(avg_score, 2),
            "best_variant_idx": best_idx,
            "best_variant": variant_factors[best_idx],
            "worst_variant_idx": worst_idx,
            "worst_variant": variant_factors[worst_idx],
            "variants": variant_factors
        }


    def _calc_wind_speed_score(self, wind_speeds: List[float]) -> float:
        if not wind_speeds:
            return 5.0

        avg_wind = sum(wind_speeds) / len(wind_speeds)
        max_wind = max(wind_speeds)

        if avg_wind < self.WIND_OPTIMAL_MIN:
            score = 4.0 + (self.WIND_OPTIMAL_MIN - avg_wind) * 0.5
        elif avg_wind <= self.WIND_OPTIMAL_MAX:
            score = 2.0 + (avg_wind - self.WIND_OPTIMAL_MIN) * 0.1
        elif avg_wind <= self.WIND_DANGEROUS:
            score = 4.0 + (avg_wind - self.WIND_OPTIMAL_MAX) * 0.4
        else:
            score = 9.0 + min(1.0, (avg_wind - self.WIND_DANGEROUS) * 0.1)

        if max_wind > self.WIND_DANGEROUS:
            score = min(10.0, score + 1.5)

        return max(1.0, min(10.0, score))

    def _calc_wind_gust_score(self, wind_speeds: List[float]) -> float:
        if not wind_speeds or len(wind_speeds) < 2:
            return 3.0

        avg_wind = sum(wind_speeds) / len(wind_speeds)
        max_wind = max(wind_speeds)

        gust_factor = max_wind - avg_wind

        if gust_factor < 3:
            return 1.0
        elif gust_factor < 6:
            return 3.0
        elif gust_factor < 10:
            return 5.0
        elif gust_factor < 15:
            return 7.0
        else:
            return 9.0

    def _calc_wave_score(self, wave_heights: List[float]) -> float:
        if not wave_heights:
            return 3.0

        avg_wave = sum(wave_heights) / len(wave_heights)
        max_wave = max(wave_heights)

        if avg_wave < self.WAVE_COMFORTABLE:
            score = 1.0
        elif avg_wave < self.WAVE_MODERATE:
            score = 2.0 + (avg_wave - self.WAVE_COMFORTABLE) * 2.0
        elif avg_wave < self.WAVE_DIFFICULT:
            score = 4.0 + (avg_wave - self.WAVE_MODERATE) * 2.0
        elif avg_wave < self.WAVE_DANGEROUS:
            score = 6.0 + (avg_wave - self.WAVE_DIFFICULT) * 2.0
        else:
            score = 9.0

        if max_wave > self.WAVE_DANGEROUS:
            score = min(10.0, score + 1.0)

        return max(1.0, min(10.0, score))

    def _calc_wind_consistency_score(self, wind_directions: List[float]) -> float:
        if not wind_directions or len(wind_directions) < 2:
            return 2.0
        sin_sum = sum(math.sin(math.radians(d)) for d in wind_directions)
        cos_sum = sum(math.cos(math.radians(d)) for d in wind_directions)
        n = len(wind_directions)

        r = math.sqrt(sin_sum**2 + cos_sum**2) / n
        consistency = r  # 0-1

        return max(1.0, min(10.0, (1 - consistency) * 10))


    def _calc_distance_score(self, distance_nm: float) -> float:
        if distance_nm < self.DISTANCE_SHORT:
            return 1.0 + distance_nm / self.DISTANCE_SHORT
        elif distance_nm < self.DISTANCE_MEDIUM:
            return 2.0 + (distance_nm - self.DISTANCE_SHORT) / (self.DISTANCE_MEDIUM - self.DISTANCE_SHORT) * 2
        elif distance_nm < self.DISTANCE_LONG:
            return 4.0 + (distance_nm - self.DISTANCE_MEDIUM) / (self.DISTANCE_LONG - self.DISTANCE_MEDIUM) * 2
        elif distance_nm < self.DISTANCE_VERY_LONG:
            return 6.0 + (distance_nm - self.DISTANCE_LONG) / (self.DISTANCE_VERY_LONG - self.DISTANCE_LONG) * 2
        else:
            return min(10.0, 8.0 + (distance_nm - self.DISTANCE_VERY_LONG) / 50)

    def _calc_tack_score(self, tacks: int) -> float:
        if tacks <= self.TACKS_FEW:
            return 1.0 + tacks * 0.5
        elif tacks <= self.TACKS_MODERATE:
            return 3.0 + (tacks - self.TACKS_FEW) * 0.4
        elif tacks <= self.TACKS_MANY:
            return 5.0 + (tacks - self.TACKS_MODERATE) * 0.3
        elif tacks <= self.TACKS_EXTREME:
            return 7.0 + (tacks - self.TACKS_MANY) * 0.2
        else:
            return min(10.0, 9.0 + (tacks - self.TACKS_EXTREME) * 0.1)

    def _calc_jibe_score(self, jibes: int) -> float:
        if jibes <= 2:
            return 1.0 + jibes * 0.75
        elif jibes <= 5:
            return 2.5 + (jibes - 2) * 0.7
        elif jibes <= 10:
            return 4.5 + (jibes - 5) * 0.5
        else:
            return min(10.0, 7.0 + (jibes - 10) * 0.3)

    def _calc_maneuver_density_score(self, total_maneuvers: int, distance_nm: float) -> float:
        if distance_nm <= 0:
            return 5.0

        density = total_maneuvers / distance_nm
        if density < 0.1:
            return 1.0 + density * 20
        elif density < 0.3:
            return 3.0 + (density - 0.1) * 15
        elif density < 0.5:
            return 6.0 + (density - 0.3) * 10
        else:
            return min(10.0, 8.0 + (density - 0.5) * 4)

    def _calc_upwind_ratio_score(self, twas: List[float]) -> float:
        if not twas:
            return 3.0

        upwind_segments = sum(1 for twa in twas if abs(twa) < 60)
        upwind_ratio = upwind_segments / len(twas)

        return 1.0 + upwind_ratio * 9


    def _calc_night_score(self, departure_time, total_time_hours: float) -> float:
        if not departure_time:
            return 2.0

        if isinstance(departure_time, str):
            departure_time = datetime.fromisoformat(departure_time.replace('Z', '+00:00'))

        # Symuluj trasę godzina po godzinie
        night_hours = 0
        current_time = departure_time

        for _ in range(int(total_time_hours) + 1):
            hour = current_time.hour
            if hour >= 18 or hour < 6:
                night_hours += 1
            current_time += timedelta(hours=1)

        night_ratio = night_hours / max(1, total_time_hours)

        return 1.0 + night_ratio * 9

    def _calc_course_complexity_score(self, bearings: List[float]) -> float:
        if not bearings or len(bearings) < 2:
            return 2.0

        changes = []
        for i in range(1, len(bearings)):
            diff = abs(bearings[i] - bearings[i-1])
            if diff > 180:
                diff = 360 - diff
            changes.append(diff)

        if not changes:
            return 2.0

        avg_change = sum(changes) / len(changes)
        max_change = max(changes)
        if avg_change < 10:
            score = 1.0 + avg_change * 0.1
        elif avg_change < 30:
            score = 2.0 + (avg_change - 10) * 0.1
        elif avg_change < 60:
            score = 4.0 + (avg_change - 30) * 0.1
        else:
            score = 7.0 + min(3.0, (avg_change - 60) * 0.05)

        if max_change > 90:
            score = min(10.0, score + 1.0)

        return max(1.0, min(10.0, score))

    def _average_factors(self, factors_list: List[DifficultyFactors]) -> DifficultyFactors:
        if not factors_list:
            return DifficultyFactors()

        n = len(factors_list)
        avg = DifficultyFactors()

        avg.wind_speed_score = sum(f.wind_speed_score for f in factors_list) / n
        avg.wind_gust_score = sum(f.wind_gust_score for f in factors_list) / n
        avg.wave_height_score = sum(f.wave_height_score for f in factors_list) / n
        avg.wind_consistency_score = sum(f.wind_consistency_score for f in factors_list) / n
        avg.distance_score = sum(f.distance_score for f in factors_list) / n
        avg.tack_count_score = sum(f.tack_count_score for f in factors_list) / n
        avg.jibe_count_score = sum(f.jibe_count_score for f in factors_list) / n
        avg.maneuver_density_score = sum(f.maneuver_density_score for f in factors_list) / n
        avg.upwind_ratio_score = sum(f.upwind_ratio_score for f in factors_list) / n
        avg.night_sailing_score = sum(f.night_sailing_score for f in factors_list) / n
        avg.course_complexity_score = sum(f.course_complexity_score for f in factors_list) / n

        return avg