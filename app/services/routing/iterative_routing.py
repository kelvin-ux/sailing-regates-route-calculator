from __future__ import annotations

import json
import math
import numpy as np
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field

from pyproj import Transformer
from scipy.spatial import KDTree
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import (
    MeshedArea, Yacht, RoutePoint, RoutePointType, Route
)
from app.schemas.time_aware_weather import (
    TimeAwareWeatherPoint,
    RouteETAProfile,
    SegmentETA,
    ETACalculationConfig,
    IterativeRouteResult,
    ETAConfidence,
)
from app.services.weather.time_aware_weather_service import (
    TimeAwareWeatherService,
    WeatherAtTime,
    weather_at_time_to_heuristics_format,
)
from app.services.routing.heuristics import (
    SailingHeuristics,
    SailingRouter,
    SafeHeuristics,
)
from app.services.weather.validator import WeatherDataValidator


@dataclass
class IterativeRoutingContext:
    meshed: MeshedArea
    yacht: Yacht
    departure_time: datetime
    vertices: np.ndarray
    triangles: np.ndarray
    weather_points: List[Dict[str, Any]]
    weather_points_wgs84: List[Tuple[float, float]]
    transformer_to_wgs84: Transformer
    transformer_from_wgs84: Transformer
    route_points: List[RoutePoint]
    config: ETACalculationConfig = field(default_factory=ETACalculationConfig)
    min_depth: float = 3.0


class IterativeRouteCalculator:
    def __init__(
        self,
        weather_service: Optional[TimeAwareWeatherService] = None,
        config: Optional[ETACalculationConfig] = None,
    ):
        self.weather_service = weather_service or TimeAwareWeatherService()
        self.config = config or ETACalculationConfig()
        self.validator = WeatherDataValidator()
    
    async def calculate_route(
        self,
        ctx: IterativeRoutingContext,
        session: AsyncSession,
    ) -> Optional[IterativeRouteResult]:
        result = IterativeRouteResult(
            profile=RouteETAProfile(
                meshed_area_id=ctx.meshed.id,
                route_id=ctx.meshed.route_id,
                departure_time=ctx.departure_time,
            ),
            calculation_started=datetime.utcnow(),
        )
        
        profile = self._create_initial_profile(ctx)
        result.profile = profile
        for iteration in range(self.config.max_iterations):
            print(f"[ITER] === Iteration {iteration + 1}/{self.config.max_iterations} ===")
            weather_data = await self.weather_service.fetch_weather_for_points(
                profile.weather_points
            )
            
            result.total_weather_requests += len(profile.weather_points)
            result.cache_hits += self.weather_service.stats.get('cache_hits', 0)
            result.api_calls += self.weather_service.stats.get('api_calls', 0)
            
            heuristics_weather = weather_at_time_to_heuristics_format(weather_data)
            
            verified_weather, navigable_vertices = self._validate_weather(
                ctx, heuristics_weather
            )
            
            if len(navigable_vertices) < len(ctx.vertices) * 0.3:
                print(f"[ITER] Not enough navigable vertices: {len(navigable_vertices)}")
                if iteration == 0:
                    return None
                break
            route_result = self._calculate_route_with_weather(
                ctx, verified_weather, navigable_vertices
            )
            
            if route_result is None:
                print(f"[ITER] Route calculation failed at iteration {iteration + 1}")
                if iteration == 0:
                    return None
                break
            
            path, segments = route_result
            
            segment_etas = self._create_segment_etas(
                segments, ctx.departure_time, ctx
            )
            old_max_change = profile.max_eta_change_seconds
            profile.update_from_segments(segment_etas)
            profile.iteration = iteration + 1
            
            result.add_iteration(
                iteration_num=iteration + 1,
                max_eta_change=profile.max_eta_change_seconds,
                weather_requests=len(profile.weather_points),
                route_time_hours=profile.total_time_hours
            )
            
            print(f"[ITER] Route: {profile.total_time_hours:.2f}h, "
                  f"{profile.total_distance_nm:.1f}nm, "
                  f"max ETA change: {profile.max_eta_change_seconds:.0f}s")
            
            if (iteration > 0 and 
                profile.max_eta_change_seconds < self.config.convergence_threshold_seconds):
                print(f"[ITER] Converged at iteration {iteration + 1}")
                result.converged = True
                result.convergence_iteration = iteration + 1
                break
            
            profile.max_eta_change_seconds = 0.0
        
        result.profile = profile
        result.calculation_finished = datetime.utcnow()
        
        return result
    
    def _create_initial_profile(
        self,
        ctx: IterativeRoutingContext
    ) -> RouteETAProfile:
        from shapely.geometry import LineString, Point
        
        profile = RouteETAProfile(
            meshed_area_id=ctx.meshed.id,
            route_id=ctx.meshed.route_id,
            departure_time=ctx.departure_time,
        )
        
        initial_speed_ms = self.config.initial_speed_knots * 0.514444
        if initial_speed_ms <= 0.1:
            initial_speed_ms = 5.0 * 0.514444 # Fallback 5kt
        route_coords = []
        for rp in ctx.route_points:
            x, y = ctx.transformer_from_wgs84.transform(rp.x, rp.y) 
            route_coords.append((x, y))
        
        route_line = LineString(route_coords) if len(route_coords) >= 2 else None
        
        for wp_data in ctx.weather_points:
            idx = wp_data.get('idx', 0)
            x = wp_data.get('x', 0.0)
            y = wp_data.get('y', 0.0)
            
            lon, lat = ctx.transformer_to_wgs84.transform(x, y)
            
            distance_along = 0.0
            if route_line:
                point = Point(x, y)
                distance_along = route_line.project(point)

            travel_time_seconds = distance_along / initial_speed_ms
            eta = ctx.departure_time + timedelta(seconds=travel_time_seconds)
            
            weather_point = TimeAwareWeatherPoint(
                idx=idx,
                x=x,
                y=y,
                lon=lon,
                lat=lat,
                eta=eta,
                eta_confidence=ETAConfidence.ESTIMATED,
                elapsed_seconds=travel_time_seconds,
                distance_from_start_m=distance_along,
                route_point_id=wp_data.get('route_point_id'),
            )
            
            profile.weather_points.append(weather_point)
            
        print(f"[ITER] Initial profile created. Avg Speed: {initial_speed_ms:.2f * 1.93} knts. " 
              f"Points: {len(profile.weather_points)}")
        
        return profile
    
    def _validate_weather(
        self,
        ctx: IterativeRoutingContext,
        weather_data: Dict[int, Dict[str, Any]]
    ) -> Tuple[Dict[int, Dict[str, Any]], List[int]]:
        weather_positions = []
        weather_indices_map = {}
        
        for i, wp in enumerate(ctx.weather_points):
            data_idx = wp['idx']
            if data_idx in weather_data:
                weather_positions.append((wp['x'], wp['y']))
                weather_indices_map[len(weather_positions) - 1] = data_idx
        
        if len(weather_positions) == 0:
            return {}, []
        
        weather_tree = KDTree(weather_positions)
        
        # Mapuj wierzchołki do pogody
        navigable_vertices = []
        nav_to_weather = {}
        weather_mapping = {i: [] for i in range(len(ctx.weather_points))}
        
        MAX_WEATHER_DISTANCE = 50000.0
        
        for nav_idx, nav_vertex in enumerate(ctx.vertices):
            distance, nearest_idx = weather_tree.query(nav_vertex, k=1)
            
            if distance > MAX_WEATHER_DISTANCE:
                continue
            
            if nearest_idx >= len(weather_indices_map):
                continue
                
            weather_data_idx = weather_indices_map[nearest_idx]
            
            if weather_data_idx not in weather_data:
                print(f"[DEBUG] Missing data for weather idx {weather_data_idx}")
                continue
            
            # Waliduj dane pogodowe
            wd = weather_data[weather_data_idx]
            if not self.validator.validate_weather_data(wd):
                continue
            
            weather_mapping[weather_data_idx].append(nav_idx)
            nav_to_weather[nav_idx] = weather_data_idx
            navigable_vertices.append(nav_idx)
        
        return weather_data, navigable_vertices
    
    def _calculate_route_with_weather(
        self,
        ctx: IterativeRoutingContext,
        weather_data: Dict[int, Dict[str, Any]],
        navigable_vertices: List[int],
    ) -> Optional[Tuple[List[Tuple[float, float]], List[Dict[str, Any]]]]:
        weather_positions = []
        weather_indices_map = {}
        
        for i, wp in enumerate(ctx.weather_points):
            data_idx = wp['idx']
            if data_idx in weather_data:
                weather_positions.append((wp['x'], wp['y']))
                weather_indices_map[len(weather_positions) - 1] = data_idx
        
        if len(weather_positions) == 0:
            return None
        
        weather_tree = KDTree(weather_positions)
        
        weather_mapping = {i: [] for i in range(len(ctx.weather_points))}
        nav_to_weather = {}
        non_navigable = set(range(len(ctx.vertices))) - set(navigable_vertices)
        
        for nav_idx in navigable_vertices:
            nav_vertex = ctx.vertices[nav_idx]
            distance, nearest_idx = weather_tree.query(nav_vertex, k=1)
            
            if nearest_idx < len(weather_indices_map):
                weather_data_idx = weather_indices_map[nearest_idx]
                weather_mapping[weather_data_idx].append(nav_idx)
                nav_to_weather[nav_idx] = weather_data_idx
        
        navigation_mesh = {
            'vertices': ctx.vertices.tolist(),
            'triangles': ctx.triangles.tolist()
        }
        
        router = SailingRouter(navigation_mesh, weather_data, ctx.yacht)
        heuristics = SailingHeuristics(ctx.yacht, weather_mapping, weather_data)
        
        safe_router = SailingRouter(
            navigation_mesh, weather_data, ctx.yacht,
            heuristics_cls=lambda *args, **kwargs: SafeHeuristics(
                *args, **kwargs, non_navigable=list(non_navigable)
            )
        )
    
        full_path = []
        all_segments = []
        
        for i in range(len(ctx.route_points) - 1):
            pt_a = ctx.route_points[i]
            pt_b = ctx.route_points[i + 1]
            
            xy_a = ctx.transformer_from_wgs84.transform(pt_a.x, pt_a.y)
            xy_b = ctx.transformer_from_wgs84.transform(pt_b.x, pt_b.y)
            
            idx_a = np.argmin(np.sum((ctx.vertices - xy_a) ** 2, axis=1))
            idx_b = np.argmin(np.sum((ctx.vertices - xy_b) ** 2, axis=1))
            
            if idx_a not in navigable_vertices or idx_b not in navigable_vertices:
                print(f"[ITER] Leg {i}: Points not navigable")
                return None
            
            leg_result = router.find_optimal_route_with_scores(
                start=xy_a, goal=xy_b, weather_mapping=weather_mapping
            )
            
            if not leg_result or not leg_result.path:
                leg_result = safe_router.find_optimal_route_with_scores(
                    start=xy_a, goal=xy_b, weather_mapping=weather_mapping
                )
            
            if not leg_result or not leg_result.path:
                print(f"[ITER] Leg {i}: No path found")
                return None
            
            path_segment = leg_result.path
            if i > 0:
                path_segment = path_segment[1:]
            
            full_path.extend(path_segment)
            
            leg_segments = self._calculate_leg_segments(
                path_segment, ctx, heuristics, navigable_vertices
            )
            all_segments.extend(leg_segments)
        
        return full_path, all_segments
    
    def _calculate_leg_segments(
        self,
        path: List[Tuple[float, float]],
        ctx: IterativeRoutingContext,
        heuristics: SailingHeuristics,
        navigable_vertices: List[int],
    ) -> List[Dict[str, Any]]:
        segments = []
        
        for i in range(len(path) - 1):
            from_pt = path[i]
            to_pt = path[i + 1]
            
            from_idx = np.argmin(np.sum((ctx.vertices - from_pt) ** 2, axis=1))
            to_idx = np.argmin(np.sum((ctx.vertices - to_pt) ** 2, axis=1))
            
            if from_idx not in navigable_vertices or to_idx not in navigable_vertices:
                continue
            
            try:
                segment_cost = heuristics.calculate_edge_cost(
                    from_pt, to_pt, from_idx, to_idx,
                    previous_heading=None if i == 0 else heuristics._calculate_bearing(
                        path[i - 1], from_pt
                    )
                )
                
                if not np.isfinite(segment_cost):
                    continue
                
                distance = heuristics._calculate_distance(from_pt, to_pt)
                bearing = heuristics._calculate_bearing(from_pt, to_pt)
                
                conditions = heuristics._get_conditions_at_vertex(to_idx)
                twa = heuristics._calculate_twa(bearing, conditions.wind_direction)
                boat_speed = heuristics._get_boat_speed(
                    conditions.wind_speed * 0.514444, abs(twa)
                )
                
                from_wgs = ctx.transformer_to_wgs84.transform(from_pt[0], from_pt[1])
                to_wgs = ctx.transformer_to_wgs84.transform(to_pt[0], to_pt[1])
                
                segments.append({
                    "from": {"x": from_pt[0], "y": from_pt[1], 
                             "lon": from_wgs[0], "lat": from_wgs[1]},
                    "to": {"x": to_pt[0], "y": to_pt[1], 
                           "lon": to_wgs[0], "lat": to_wgs[1]},
                    "distance_m": float(distance),
                    "distance_nm": float(distance / 1852.0),
                    "bearing": float(bearing),
                    "time_seconds": float(segment_cost),
                    "boat_speed_knots": float(boat_speed),
                    "boat_speed_ms": float(boat_speed * 0.514444),
                    "wind_speed_knots": float(conditions.wind_speed),
                    "wind_direction": float(conditions.wind_direction),
                    "twa": float(twa),
                    "wave_height_m": float(conditions.wave_height),
                })
                
            except Exception as e:
                print(f"[ITER] Segment error: {e}")
                continue
        
        return segments
    
    def _create_segment_etas(
        self,
        segments: List[Dict[str, Any]],
        departure_time: datetime,
        ctx: IterativeRoutingContext,
    ) -> List[SegmentETA]:
        segment_etas = []
        current_time = departure_time
        
        for i, seg in enumerate(segments):
            duration = seg.get('time_seconds', 0)
            end_time = current_time + timedelta(seconds=duration)
            
            segment_eta = SegmentETA(
                from_idx=i,
                to_idx=i + 1,
                from_point=(seg['from']['x'], seg['from']['y']),
                to_point=(seg['to']['x'], seg['to']['y']),
                from_point_wgs84=(seg['from']['lon'], seg['from']['lat']),
                to_point_wgs84=(seg['to']['lon'], seg['to']['lat']),
                start_time=current_time,
                end_time=end_time,
                duration_seconds=duration,
                distance_m=seg.get('distance_m', 0),
                distance_nm=seg.get('distance_nm', 0),
                boat_speed_ms=seg.get('boat_speed_ms', 0),
                boat_speed_knots=seg.get('boat_speed_knots', 0),
                bearing=seg.get('bearing', 0),
                twa=seg.get('twa', 0),
                wind_speed_knots=seg.get('wind_speed_knots', 0),
                wind_direction=seg.get('wind_direction', 0),
                wave_height_m=seg.get('wave_height_m', 0),
            )
            
            segment_etas.append(segment_eta)
            current_time = end_time
        
        return segment_etas
    
    def get_final_route_data(
        self,
        result: IterativeRouteResult,
        ctx: IterativeRoutingContext,
    ) -> Dict[str, Any]:
        profile = result.profile
        waypoints_wgs84 = []
        for seg in profile.segments:
            if not waypoints_wgs84:
                waypoints_wgs84.append(seg.from_point_wgs84)
            waypoints_wgs84.append(seg.to_point_wgs84)
        
        segments = []
        for seg in profile.segments:
            segments.append({
                "from": {
                    "x": seg.from_point[0], "y": seg.from_point[1],
                    "lon": seg.from_point_wgs84[0], "lat": seg.from_point_wgs84[1]
                },
                "to": {
                    "x": seg.to_point[0], "y": seg.to_point[1],
                    "lon": seg.to_point_wgs84[0], "lat": seg.to_point_wgs84[1]
                },
                "distance_m": seg.distance_m,
                "distance_nm": seg.distance_nm,
                "bearing": seg.bearing,
                "time_seconds": seg.duration_seconds,
                "boat_speed_knots": seg.boat_speed_knots,
                "wind_speed_knots": seg.wind_speed_knots,
                "wind_direction": seg.wind_direction,
                "twa": seg.twa,
                "wave_height_m": seg.wave_height_m,
                "validated": True,
                "start_time": seg.start_time.isoformat(),
                "end_time": seg.end_time.isoformat(),
            })
        
        total_wind_speed = sum(s.wind_speed_knots for s in profile.segments)
        total_wave_height = sum(s.wave_height_m for s in profile.segments)
        n_segments = len(profile.segments)
        
        avg_wind_speed = total_wind_speed / n_segments if n_segments > 0 else 0
        avg_wave_height = total_wave_height / n_segments if n_segments > 0 else 0
        
        tacks_count = 0
        jibes_count = 0
        for i, seg in enumerate(profile.segments[1:], 1):
            prev_seg = profile.segments[i - 1]
            prev_twa = prev_seg.twa
            curr_twa = seg.twa
            
            if (prev_twa > 0 and curr_twa < 0) or (prev_twa < 0 and curr_twa > 0):
                if abs(prev_twa) < 90 or abs(curr_twa) < 90:
                    tacks_count += 1
                elif abs(prev_twa) > 120 and abs(curr_twa) > 120:
                    jibes_count += 1
        
        return {
            "departure_time": ctx.departure_time,
            "waypoints_wgs84": [(float(p[0]), float(p[1])) for p in waypoints_wgs84],
            "segments": segments,
            "total_time_hours": profile.total_time_hours,
            "total_distance_nm": profile.total_distance_nm,
            "average_speed_knots": (
                profile.total_distance_nm / profile.total_time_hours 
                if profile.total_time_hours > 0 else 0
            ),
            "avg_wind_speed": avg_wind_speed,
            "avg_wave_height": avg_wave_height,
            "tacks_count": tacks_count,
            "jibes_count": jibes_count,
            "estimated_arrival": profile.estimated_arrival.isoformat() if profile.estimated_arrival else None,
            "iterations": result.iterations,
            "converged": result.converged,
            "calculation_time_seconds": result.calculation_time_seconds,
            "weather_stats": {
                "total_requests": result.total_weather_requests,
                "cache_hits": result.cache_hits,
                "api_calls": result.api_calls,
            }
        }


async def create_routing_context(
    session: AsyncSession,
    meshed: MeshedArea,
    yacht: Yacht,
    departure_time: datetime,
    route_points: List[RoutePoint],
    config: Optional[ETACalculationConfig] = None,
) -> IterativeRoutingContext:
    vertices = np.array(json.loads(meshed.nodes_json))
    triangles = np.array(json.loads(meshed.triangles_json))
    weather_points_data = json.loads(meshed.weather_points_json) if meshed.weather_points_json else {}
    weather_points = weather_points_data.get('points', [])
    transformer_to_wgs84 = Transformer.from_crs(meshed.crs_epsg, 4326, always_xy=True)
    transformer_from_wgs84 = Transformer.from_crs(4326, meshed.crs_epsg, always_xy=True)
    weather_points_wgs84 = []
    for wp in weather_points:
        lon, lat = transformer_to_wgs84.transform(wp['x'], wp['y'])
        weather_points_wgs84.append((lon, lat))
    
    return IterativeRoutingContext(
        meshed=meshed,
        yacht=yacht,
        departure_time=departure_time,
        vertices=vertices,
        triangles=triangles,
        weather_points=weather_points,
        weather_points_wgs84=weather_points_wgs84,
        transformer_to_wgs84=transformer_to_wgs84,
        transformer_from_wgs84=transformer_from_wgs84,
        route_points=route_points,
        config=config or ETACalculationConfig(),
    )