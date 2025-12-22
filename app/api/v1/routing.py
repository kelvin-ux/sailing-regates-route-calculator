from __future__ import annotations

import json
import numpy as np
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from pyproj import Transformer

from pydantic import UUID4
from sqlalchemy import delete
from sqlalchemy import select
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession
from scipy.spatial import KDTree

from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from fastapi import Query
from fastapi import Body

from app.core.database import get_db as get_async_session

from app.models.models import RouteSegments
from app.models.models import RoutePoint
from app.models.models import RoutePointType
from app.models.models import WeatherForecast
from app.models.models import MeshedArea
from app.models.models import Route
from app.models.models import RouteVariant

from app.services.db.services import RouteService
from app.services.db.services import YachtService
from app.services.db.services import MeshedAreaService
from app.services.db.services import RoutePointService
from app.services.db.services import RouteVariantService
from app.services.routing.heuristics import SafeHeuristics
from app.services.routing.heuristics import SailingHeuristics
from app.services.routing.heuristics import SailingRouter
from app.services.routing.heurystic_storage import save_path_heuristics
from app.services.routing.segement_optimalizer import SegmentOptimizer
from app.services.weather.validator import WeatherDataValidator
from app.services.weather.weather_api_manager import OpenMeteoService

from app.services.routing.time_window import TimeWindowRequest
from app.services.routing.diff_calc import RouteDifficultyCalculator
router = APIRouter()

_weather_service: Optional[OpenMeteoService] = None


def get_weather_service() -> OpenMeteoService:
    global _weather_service
    if _weather_service is None:
        _weather_service = OpenMeteoService(
            redis_url=None,
            max_calls_per_minute=500,
            cache_ttl=3600
        )
    return _weather_service


async def _fetch_weather_for_time(weather_points_wgs84: List[tuple], departure_time: datetime, weather_service: OpenMeteoService) -> Dict[int, Dict]:
    """
    Fetch weather forecast for all weather points at a specific departure time.
    Returns dict mapping point index to weather data.
    """
    print(f"Fetching weather for {len(weather_points_wgs84)} points at {departure_time}")

    weather_data = await weather_service.fetch_batch_at_time(
        points=[(lat, lon) for lon, lat in weather_points_wgs84],
        target_time=departure_time
    )

    verified_data = {}
    validator = WeatherDataValidator()

    for idx, data in weather_data.items():
        weather_dict = {
            'wind_speed_10m': data.get('wind_speed', 5.0),
            'wind_direction_10m': data.get('wind_direction', 0.0),
            'wave_height': data.get('wave_height', 0.5),
            'wave_direction': data.get('wave_direction', 0.0),
            'wave_period': data.get('wave_period', 4.0),
            'current_speed': data.get('current_velocity', 0.1),
            'current_direction': data.get('current_direction', 0.0),
        }

        if validator.validate_weather_data(weather_dict):
            verified_data[idx] = weather_dict
        elif not data.get('is_default', True):
            verified_data[idx] = weather_dict

    print(f"Got {len(verified_data)} valid weather points for {departure_time}")
    return verified_data


async def _calculate_single_route(
        session: AsyncSession,
        meshed: MeshedArea,
        yacht,
        weather_points: List,
        weather_points_wgs84: List[tuple],
        vertices: np.ndarray,
        triangles: np.ndarray,
        departure_time: datetime,
        variant_order: int = 0,
        min_depth: float = 3.0,
        weather_service: OpenMeteoService = None
) -> Optional[Dict[str, Any]]:
    """Calculate a single route variant for given departure time with fresh weather data."""
    if weather_service is None:
        weather_service = get_weather_service()

    verified_weather_data = await _fetch_weather_for_time(
        weather_points_wgs84,
        departure_time,
        weather_service
    )

    if len(verified_weather_data) == 0:
        print(f"No valid weather data for departure {departure_time}")
        return None

    weather_positions = []
    weather_indices_map = {}

    for i, wp in enumerate(weather_points):
        data_idx = wp['idx']
        if data_idx in verified_weather_data:
            weather_positions.append((wp['x'], wp['y']))
            weather_indices_map[len(weather_positions) - 1] = data_idx

    if len(weather_positions) == 0:
        print(f"No valid weather positions for departure {departure_time}")
        return None

    weather_tree = KDTree(weather_positions)

    weather_mapping = {i: [] for i in range(len(weather_points))}
    nav_to_weather = {}
    navigable_vertices = []
    non_navigable_vertices = []

    MAX_WEATHER_DISTANCE = 10000.0

    for nav_idx, nav_vertex in enumerate(vertices):
        distance, nearest_idx = weather_tree.query(nav_vertex, k=1)

        if distance > MAX_WEATHER_DISTANCE:
            non_navigable_vertices.append(nav_idx)
            continue

        weather_data_idx = weather_indices_map[nearest_idx]

        if weather_data_idx not in verified_weather_data:
            non_navigable_vertices.append(nav_idx)
            continue

        weather_mapping[weather_data_idx].append(nav_idx)
        nav_to_weather[nav_idx] = weather_data_idx
        navigable_vertices.append(nav_idx)

    if len(navigable_vertices) < len(vertices) * 0.3:
        print(f"Not enough navigable vertices: {len(navigable_vertices)}/{len(vertices)}")
        return None

    query_start = (
        select(RoutePoint)
        .where(RoutePoint.route_id == meshed.route_id)
        .where(RoutePoint.point_type == RoutePointType.START)
        .order_by(RoutePoint.seq_idx)
        .limit(1)
    )
    query_stop = (
        select(RoutePoint)
        .where(RoutePoint.route_id == meshed.route_id)
        .where(RoutePoint.point_type == RoutePointType.STOP)
        .order_by(RoutePoint.seq_idx.desc())
        .limit(1)
    )

    result_start = await session.execute(query_start)
    result_stop = await session.execute(query_stop)

    start_point = result_start.scalar_one_or_none()
    stop_point = result_stop.scalar_one_or_none()

    if not start_point or not stop_point:
        return None

    transformer = Transformer.from_crs(4326, meshed.crs_epsg, always_xy=True)

    start_xy = transformer.transform(start_point.x, start_point.y)
    stop_xy = transformer.transform(stop_point.x, stop_point.y)

    start_vertex_idx = np.argmin(np.sum((vertices - start_xy) ** 2, axis=1))
    if start_vertex_idx not in navigable_vertices:
        print(f"Start point not navigable for departure {departure_time}")
        return None

    stop_vertex_idx = np.argmin(np.sum((vertices - stop_xy) ** 2, axis=1))
    if stop_vertex_idx not in navigable_vertices:
        print(f"Stop point not navigable for departure {departure_time}")
        return None

    navigation_mesh = {
        'vertices': vertices.tolist(),
        'triangles': triangles.tolist()
    }

    router_instance = SailingRouter(navigation_mesh, verified_weather_data, yacht)
    heuristics = SailingHeuristics(yacht, weather_mapping, verified_weather_data)

    route_result = router_instance.find_optimal_route_with_scores(
        start=start_xy,
        goal=stop_xy,
        weather_mapping=weather_mapping
    )
    optimal_path = route_result.path if route_result else None

    if not optimal_path:
        safe_router = SailingRouter(
            navigation_mesh,
            verified_weather_data,
            yacht,
            heuristics_cls=lambda *args, **kwargs: SafeHeuristics(
                *args, **kwargs, non_navigable=non_navigable_vertices
            )
        )

        route_result = safe_router.find_optimal_route_with_scores(
            start=start_xy,
            goal=stop_xy,
            weather_mapping=weather_mapping
        )
        optimal_path = route_result.path if route_result else None

        if not optimal_path:
            print(f"No path found for departure {departure_time}")
            return None

    transformer_back = Transformer.from_crs(meshed.crs_epsg, 4326, always_xy=True)
    path_wgs84 = [
        transformer_back.transform(p[0], p[1]) for p in optimal_path
    ]

    segments = []
    total_time = 0.0
    total_distance = 0.0
    invalid_segments = 0
    total_wind_speed = 0.0
    total_wind_direction = 0.0
    total_wave_height = 0.0
    valid_weather_count = 0
    tacks_count = 0
    jibes_count = 0

    for i in range(len(optimal_path) - 1):
        from_pt = optimal_path[i]
        to_pt = optimal_path[i + 1]

        from_idx = np.argmin(np.sum((vertices - from_pt) ** 2, axis=1))
        to_idx = np.argmin(np.sum((vertices - to_pt) ** 2, axis=1))

        if from_idx not in navigable_vertices or to_idx not in navigable_vertices:
            invalid_segments += 1
            continue

        try:
            segment_cost = heuristics.calculate_edge_cost(
                from_pt, to_pt, from_idx, to_idx,
                previous_heading=None if i == 0 else heuristics._calculate_bearing(optimal_path[i - 1], from_pt)
            )

            if not np.isfinite(segment_cost):
                invalid_segments += 1
                continue

            distance = heuristics._calculate_distance(from_pt, to_pt)
            bearing = heuristics._calculate_bearing(from_pt, to_pt)

            conditions = heuristics._get_conditions_at_vertex(to_idx)
            twa = heuristics._calculate_twa(bearing, conditions.wind_direction)
            boat_speed = heuristics._get_boat_speed(conditions.wind_speed * 0.514444, abs(twa))

            point_of_sail = _get_point_of_sail(abs(twa))

            if i > 0:
                prev_conditions = heuristics._get_conditions_at_vertex(from_idx)
                prev_bearing = heuristics._calculate_bearing(optimal_path[i - 1], from_pt)
                prev_twa = heuristics._calculate_twa(prev_bearing, prev_conditions.wind_direction)

                if (prev_twa > 0 and twa < 0) or (prev_twa < 0 and twa > 0):
                    if abs(prev_twa) < 90 or abs(twa) < 90:
                        tacks_count += 1
                    elif abs(prev_twa) > 120 and abs(twa) > 120:
                        jibes_count += 1

            segments.append({
                "from": {"x": from_pt[0], "y": from_pt[1], "lon": path_wgs84[i][0], "lat": path_wgs84[i][1]},
                "to": {"x": to_pt[0], "y": to_pt[1], "lon": path_wgs84[i + 1][0], "lat": path_wgs84[i + 1][1]},
                "distance_m": float(distance),
                "distance_nm": float(distance / 1852.0),
                "bearing": float(bearing),
                "time_seconds": float(segment_cost),
                "boat_speed_knots": float(boat_speed),
                "wind_speed_knots": float(conditions.wind_speed),
                "wind_direction": float(conditions.wind_direction),
                "twa": float(twa),
                "point_of_sail": point_of_sail,
                "wave_height_m": float(conditions.wave_height),
                "validated": True
            })

            total_time += segment_cost
            total_distance += distance
            total_wind_speed += conditions.wind_speed
            total_wind_direction += conditions.wind_direction
            total_wave_height += conditions.wave_height
            valid_weather_count += 1

        except Exception as e:
            invalid_segments += 1

    if len(segments) == 0:
        return None

    if route_result and route_result.f_scores:
        transformer_back = Transformer.from_crs(meshed.crs_epsg, 4326, always_xy=True)
        path_data = []
        for i, idx in enumerate(route_result.path_indices):
            x, y = vertices[idx]
            lon, lat = transformer_back.transform(x, y)
            path_data.append({
                "x": lon,
                "y": lat,
                "seq_idx": 5000 + i,
                "heuristic_score": route_result.f_scores.get(idx, 0.0)
            })

        await save_path_heuristics(
            session,
            meshed.route_id,
            meshed.id,
            path_data
        )

    avg_wind_speed = total_wind_speed / valid_weather_count if valid_weather_count > 0 else 0.0
    avg_wind_direction = total_wind_direction / valid_weather_count if valid_weather_count > 0 else 0.0
    avg_wave_height = total_wave_height / valid_weather_count if valid_weather_count > 0 else 0.0

    return {
        "departure_time": departure_time,
        "variant_order": variant_order,
        "waypoints_wgs84": [(float(p[0]), float(p[1])) for p in path_wgs84],
        "segments": segments,
        "total_time_hours": float(total_time / 3600),
        "total_distance_nm": float(total_distance / 1852.0),
        "average_speed_knots": float((total_distance / 1852.0) / (total_time / 3600)) if total_time > 0 else 0,
        "avg_wind_speed": float(avg_wind_speed),
        "avg_wind_direction": float(avg_wind_direction),
        "avg_wave_height": float(avg_wave_height),
        "tacks_count": tacks_count,
        "jibes_count": jibes_count,
        "invalid_segments": invalid_segments,
        "navigable_vertices": len(navigable_vertices),
        "weather_points_used": len(verified_weather_data)
    }


@router.post("/{meshed_area_id}/calculate-route", status_code=200)
async def calculate_optimal_route(
        meshed_area_id: UUID4,
        min_depth: float = Query(3.0, description="Minimum water depth in meters"),
        time_window: Optional[TimeWindowRequest] = Body(default=None,
                                                        description="Optional time window for multiple route calculations"),
        session: AsyncSession = Depends(get_async_session)
):
    """
    Calculate optimal sailing route with optional time window analysis.

    If time_window is provided, calculates multiple route variants for different
    departure times within the window.

    Example time_window payload:
    ```json
    {
        "start_time": "2025-01-15T08:00:00Z",
        "end_time": "2025-01-15T14:00:00Z",
        "num_checks": 4
    }
    ```
    """
    try:
        mesh_svc = MeshedAreaService(session)
        meshed = await mesh_svc.get_entity_by_id(meshed_area_id, allow_none=False)

        if not meshed:
            raise HTTPException(404, f"Mesh {meshed_area_id} not found")

        navigation_mesh = {
            'vertices': json.loads(meshed.nodes_json),
            'triangles': json.loads(meshed.triangles_json)
        }

        vertices = np.array(navigation_mesh['vertices'])
        weather_points_data = json.loads(meshed.weather_points_json) if meshed.weather_points_json else None

        if not weather_points_data:
            raise HTTPException(400, "No weather points defined. Run mesh creation first.")

        weather_points = weather_points_data.get('points', [])

        if len(weather_points) == 0:
            raise HTTPException(400, "No weather points in mesh metadata")

        rpoint_svc = RoutePointService(session)

        weather_points_db = await rpoint_svc.get_all_entities(
            filters={'meshed_area_id': meshed_area_id, 'point_type': RoutePointType.WEATHER},
            page=1,
            limit=1000
        )

        validator = WeatherDataValidator()
        verified_weather_data = {}
        invalid_weather_points = []

        for wp in weather_points_db:
            query = (
                select(WeatherForecast)
                .where(WeatherForecast.route_point_id == wp.id)
                .where(WeatherForecast.is_default == False)
                .order_by(WeatherForecast.forecast_timestamp.desc())
                .limit(1)
            )
            result = await session.execute(query)
            forecast = result.scalar_one_or_none()

            if not forecast:
                invalid_weather_points.append(wp.seq_idx - 1000)
                continue

            idx = wp.seq_idx - 1000

            weather_dict = {
                'wind_speed_10m': forecast.wind_speed if forecast.wind_speed else None,
                'wind_direction_10m': forecast.wind_direction,
                'wave_height': forecast.wave_height,
                'wave_direction': forecast.wave_direction,
                'wave_period': forecast.wave_period,
                'current_speed': forecast.current_velocity if forecast.current_velocity else None,
                'current_direction': forecast.current_direction,
            }

            if not validator.validate_weather_data(weather_dict):
                invalid_weather_points.append(idx)
                continue

            verified_weather_data[idx] = weather_dict

        if len(verified_weather_data) == 0:
            raise HTTPException(400, "No weather points have valid data. Run fetch-weather first.")

        weather_positions = []
        weather_indices_map = {}

        for i, wp in enumerate(weather_points):
            data_idx = wp['idx']
            if data_idx in verified_weather_data:
                weather_positions.append((wp['x'], wp['y']))
                weather_indices_map[len(weather_positions) - 1] = data_idx

        if len(weather_positions) == 0:
            raise HTTPException(400, "No valid weather points after validation")

        weather_tree = KDTree(weather_positions)

        weather_mapping = {i: [] for i in range(len(weather_points))}
        nav_to_weather = {}
        navigable_vertices = []
        non_navigable_vertices = []

        MAX_WEATHER_DISTANCE = 10000.0

        for nav_idx, nav_vertex in enumerate(vertices):
            distance, nearest_idx = weather_tree.query(nav_vertex, k=1)

            if distance > MAX_WEATHER_DISTANCE:
                non_navigable_vertices.append(nav_idx)
                continue

            weather_data_idx = weather_indices_map[nearest_idx]

            if weather_data_idx not in verified_weather_data:
                non_navigable_vertices.append(nav_idx)
                continue

            weather_mapping[weather_data_idx].append(nav_idx)
            nav_to_weather[nav_idx] = weather_data_idx
            navigable_vertices.append(nav_idx)

        if len(navigable_vertices) < len(vertices) * 0.5:
            raise HTTPException(400, f"Only {len(navigable_vertices)}/{len(vertices)} vertices are navigable.")

        route_svc = RouteService(session)
        yacht_svc = YachtService(session)
        variant_svc = RouteVariantService(session)

        route = await route_svc.get_entity_by_id(meshed.route_id, allow_none=False)
        yacht = await yacht_svc.get_entity_by_id(route.yacht_id, allow_none=False)

        if time_window is None:
            time_points = [datetime.now(timezone.utc)]
        else:
            time_points = time_window.get_time_points()

        await session.execute(
            delete(RouteVariant).where(RouteVariant.meshed_area_id == meshed_area_id)
        )
        await session.commit()

        transformer_to_wgs84 = Transformer.from_crs(meshed.crs_epsg, 4326, always_xy=True)
        weather_points_wgs84 = []
        for wp in weather_points:
            lon, lat = transformer_to_wgs84.transform(wp['x'], wp['y'])
            weather_points_wgs84.append((lon, lat))

        triangles = np.array(json.loads(meshed.triangles_json))
        weather_service = get_weather_service()
        variants_results = []
        for idx, departure_time in enumerate(time_points):
            print(f"  Variant {idx + 1}/{len(time_points)}: departure at {departure_time}")

            variant_result = await _calculate_single_route(
                session=session,
                meshed=meshed,
                yacht=yacht,
                weather_points=weather_points,
                weather_points_wgs84=weather_points_wgs84,
                vertices=vertices,
                triangles=triangles,
                departure_time=departure_time,
                variant_order=idx,
                min_depth=min_depth,
                weather_service=weather_service
            )

            if variant_result:
                variants_results.append(variant_result)
                print(f"    -> Route calculated: {variant_result['total_time_hours']:.2f}h, "
                      f"{variant_result['total_distance_nm']:.1f}nm, "
                      f"wind: {variant_result['avg_wind_speed']:.1f}kt")
            else:
                print(f"    -> Failed to calculate route")

        if not variants_results:
            raise HTTPException(400, "No navigable routes found for any time point.")

        difficulty_calculator = RouteDifficultyCalculator()
        difficulty_result = difficulty_calculator.calculate_for_variants(variants_results)
        overall_difficulty = round(difficulty_result["overall_score"])
        stmt_route = (
            update(Route)
            .where(Route.id == meshed.route_id)
            .values(difficulty_level=overall_difficulty))
        await session.execute(stmt_route)

        best_variant_idx = min(range(len(variants_results)), key=lambda i: variants_results[i]['total_time_hours'])

        saved_variants = []
        for idx, variant_data in enumerate(variants_results):
            is_best = (idx == best_variant_idx)

            variant = RouteVariant(
                meshed_area_id=meshed_area_id,
                departure_time=variant_data['departure_time'],
                variant_order=variant_data['variant_order'],
                waypoints_json=json.dumps(variant_data['waypoints_wgs84']),
                segments_json=json.dumps(variant_data['segments']),
                total_time_hours=variant_data['total_time_hours'],
                total_distance_nm=variant_data['total_distance_nm'],
                average_speed_knots=variant_data['average_speed_knots'],
                avg_wind_speed=variant_data['avg_wind_speed'],
                avg_wave_height=variant_data['avg_wave_height'],
                tacks_count=variant_data['tacks_count'],
                jibes_count=variant_data['jibes_count'],
                is_best=is_best,
                is_selected=is_best
            )
            session.add(variant)
            await session.flush()

            variant_difficulty = difficulty_result["variants"][idx]

            saved_variants.append({
                "variant_id": str(variant.id),
                "departure_time": variant_data['departure_time'].isoformat(),
                "total_time_hours": variant_data['total_time_hours'],
                "total_distance_nm": variant_data['total_distance_nm'],
                "average_speed_knots": variant_data['average_speed_knots'],
                "avg_wind_speed": variant_data['avg_wind_speed'],
                "avg_wave_height": variant_data['avg_wave_height'],
                "tacks_count": variant_data['tacks_count'],
                "jibes_count": variant_data['jibes_count'],
                "is_best": is_best,
                "segments_count": len(variant_data['segments']),
                "difficulty_score": round(variant_difficulty.calculate_total(), 2),
                "difficulty_level": variant_difficulty.get_level().value
            })

        best_variant_data = variants_results[best_variant_idx]
        route_data = {
            "meshed_area_id": str(meshed_area_id),
            "calculated_at": datetime.utcnow().isoformat(),
            "yacht": {"id": str(yacht.id), "name": yacht.name, "type": yacht.yacht_type},
            "route": {
                "waypoints_count": len(best_variant_data['waypoints_wgs84']),
                "waypoints_wgs84": best_variant_data['waypoints_wgs84'],
                "segments_count": len(best_variant_data['segments']),
                "segments": best_variant_data['segments'],
                "total_time_hours": best_variant_data['total_time_hours'],
                "total_distance_nm": best_variant_data['total_distance_nm'],
                "average_speed_knots": best_variant_data['average_speed_knots']
            },
            "time_window": {
                "enabled": time_window is not None,
                "num_variants": len(variants_results)
            }
        }
        stmt = (
            update(MeshedArea)
            .where(MeshedArea.id == meshed_area_id)
            .values(
                calculated_route_json=json.dumps(route_data),
                calculated_route_timestamp=datetime.utcnow()
            )
        )
        await session.execute(stmt)
        await session.commit()

        return {
            "meshed_area_id": str(meshed_area_id),
            "yacht": {
                "id": str(yacht.id),
                "name": yacht.name,
                "type": yacht.yacht_type
            },
            "time_window": {
                "start_time": time_points[0].isoformat() if time_points else None,
                "end_time": time_points[-1].isoformat() if len(time_points) > 1 else None,
                "num_checks": len(time_points)
            },
            "variants_count": len(saved_variants),
            "variants": saved_variants,
            "best_variant": saved_variants[best_variant_idx] if saved_variants else None,
            "validation": {
                "navigable_vertices": len(navigable_vertices),
                "total_vertices": len(vertices),
                "coverage_percent": (len(navigable_vertices) / len(vertices) * 100),
                "valid_weather_points": len(verified_weather_data),
                "total_weather_points": len(weather_points)
            },
            "difficulty": {
                "overall_score": difficulty_result["overall_score"],
                "level": difficulty_result["overall"].get_level().value,
                "best_variant_score": round(difficulty_result["best_variant"].calculate_total(), 2),
                "worst_variant_score": round(difficulty_result["worst_variant"].calculate_total(), 2),
                "breakdown": difficulty_result["overall"].to_dict()["breakdown"]
            }
        }

    except HTTPException:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(500, f"Failed to calculate route: {str(e)}")


@router.get("/{meshed_area_id}/variants", status_code=200)
async def get_route_variants(
        meshed_area_id: UUID4,
        session: AsyncSession = Depends(get_async_session)
):
    """Get all calculated route variants for a mesh."""

    query = (
        select(RouteVariant)
        .where(RouteVariant.meshed_area_id == meshed_area_id)
        .order_by(RouteVariant.variant_order)
    )
    result = await session.execute(query)
    variants = result.scalars().all()

    if not variants:
        raise HTTPException(404, "No variants found. Calculate routes first.")

    return {
        "meshed_area_id": str(meshed_area_id),
        "variants_count": len(variants),
        "variants": [
            {
                "variant_id": str(v.id),
                "departure_time": v.departure_time.isoformat(),
                "variant_order": v.variant_order,
                "total_time_hours": v.total_time_hours,
                "total_distance_nm": v.total_distance_nm,
                "average_speed_knots": v.average_speed_knots,
                "avg_wind_speed": v.avg_wind_speed,
                "avg_wave_height": v.avg_wave_height,
                "tacks_count": v.tacks_count,
                "jibes_count": v.jibes_count,
                "is_best": v.is_best,
                "is_selected": v.is_selected
            }
            for v in variants
        ]
    }


@router.post("/{meshed_area_id}/variants/select", status_code=200)
async def select_route_variants(
        meshed_area_id: UUID4,
        variant_ids: List[UUID4] = Body(..., description="List of variant IDs to select for display"),
        session: AsyncSession = Depends(get_async_session)
):
    """Select which route variants to display on the map."""

    await session.execute(
        update(RouteVariant)
        .where(RouteVariant.meshed_area_id == meshed_area_id)
        .values(is_selected=False)
    )
    for variant_id in variant_ids:
        await session.execute(
            update(RouteVariant)
            .where(RouteVariant.id == variant_id)
            .where(RouteVariant.meshed_area_id == meshed_area_id)
            .values(is_selected=True)
        )

    await session.commit()

    return {"status": "success", "selected_count": len(variant_ids)}


@router.get("/{meshed_area_id}/calculated-route", status_code=200)
async def get_calculated_route(
        meshed_area_id: UUID4,
        session: AsyncSession = Depends(get_async_session)
):
    mesh_svc = MeshedAreaService(session)
    meshed = await mesh_svc.get_entity_by_id(meshed_area_id, allow_none=False)

    if not meshed or not meshed.calculated_route_json:
        raise HTTPException(404, "No calculated route found")

    route_data = json.loads(meshed.calculated_route_json)

    return {
        "status": "success",
        "meshed_area_id": str(meshed_area_id),
        "calculated_at": route_data.get('calculated_at'),
        "data": route_data
    }



@router.get("/{meshed_area_id}/difficulty", status_code=200)
async def get_route_difficulty(
        meshed_area_id: UUID4,
        include_breakdown: bool = Query(True, description="Include detailed breakdown"),
        session: AsyncSession = Depends(get_async_session)
):
    """Get difficulty analysis for calculated route variants."""

    query = (
        select(RouteVariant)
        .where(RouteVariant.meshed_area_id == meshed_area_id)
        .order_by(RouteVariant.variant_order)
    )
    result = await session.execute(query)
    variants = result.scalars().all()

    if not variants:
        raise HTTPException(404, "No variants found. Calculate routes first.")

    variants_data = []
    for v in variants:
        segments = json.loads(v.segments_json) if v.segments_json else []
        variants_data.append({
            "segments": segments,
            "tacks_count": v.tacks_count or 0,
            "jibes_count": v.jibes_count or 0,
            "total_distance_nm": v.total_distance_nm or 0,
            "total_time_hours": v.total_time_hours or 0,
            "departure_time": v.departure_time
        })

    calculator = RouteDifficultyCalculator()
    difficulty_result = calculator.calculate_for_variants(variants_data)

    response = {
        "meshed_area_id": str(meshed_area_id),
        "overall_score": difficulty_result["overall_score"],
        "level": difficulty_result["overall"].get_level().value,
        "best_variant": {
            "idx": difficulty_result["best_variant_idx"],
            "score": round(difficulty_result["best_variant"].calculate_total(), 2),
            "level": difficulty_result["best_variant"].get_level().value
        },
        "worst_variant": {
            "idx": difficulty_result["worst_variant_idx"],
            "score": round(difficulty_result["worst_variant"].calculate_total(), 2),
            "level": difficulty_result["worst_variant"].get_level().value
        },
        "variants": [
            {
                "variant_order": i,
                "score": round(f.calculate_total(), 2),
                "level": f.get_level().value
            }
            for i, f in enumerate(difficulty_result["variants"])
        ]
    }

    if include_breakdown:
        response["breakdown"] = difficulty_result["overall"].to_dict()["breakdown"]
        response["variants_breakdown"] = [
            f.to_dict() for f in difficulty_result["variants"]
        ]

    return response

def _get_point_of_sail(twa: float) -> str:
    twa = abs(twa)

    if twa < 25:
        return "no-go zone"
    elif twa < 45:
        return "close-hauled"
    elif twa < 60:
        return "close reach"
    elif twa < 90:
        return "beam reach"
    elif twa < 120:
        return "broad reach"
    elif twa < 150:
        return "running"
    else:
        return "dead run"


def _determine_sail_type(twa: float, wind_speed_knots: float) -> str:
    abs_twa = abs(twa)

    if wind_speed_knots < 8:
        if abs_twa > 90:
            return "spinnaker"
        else:
            return "genoa"
    elif wind_speed_knots < 15:
        if abs_twa > 120:
            return "spinnaker"
        elif abs_twa > 60:
            return "genoa"
        else:
            return "jib"
    else:
        if abs_twa > 140:
            return "spinnaker"
        elif abs_twa > 90:
            return "jib"
        else:
            return "storm_jib"