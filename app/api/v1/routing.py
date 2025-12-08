from __future__ import annotations

import json
import numpy as np
from datetime import datetime
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

from app.core.database import get_db as get_async_session

from app.models.models import RouteSegments
from app.models.models import RoutePoint
from app.models.models import RoutePointType
from app.models.models import WeatherForecast
from app.models.models import MeshedArea
from app.models.models import Route

from app.services.db.services import RouteService
from app.services.db.services import YachtService
from app.services.db.services import MeshedAreaService
from app.services.db.services import RoutePointService
from app.services.routing.heuristics import SafeHeuristics
from app.services.routing.heuristics import SailingHeuristics
from app.services.routing.heuristics import SailingRouter
from app.services.routing.segement_optimalizer import SegmentOptimizer
from app.services.weather.validator import WeatherDataValidator


router = APIRouter()


@router.post("/{meshed_area_id}/calculate-route", status_code=200)
async def calculate_optimal_route(meshed_area_id: UUID4, min_depth: float = 3.0, session: AsyncSession = Depends(get_async_session)):
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
            filters={'meshed_area_id': meshed_area_id,'point_type': RoutePointType.WEATHER},
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
        weather_indices_map = {}  # Maps weather array index to weather data index

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

        MAX_WEATHER_DISTANCE = 10000.0 # distance to furthest weatherpoint

        for nav_idx, nav_vertex in enumerate(vertices):
            distance, nearest_idx = weather_tree.query(nav_vertex, k=1)

            if distance > MAX_WEATHER_DISTANCE:
                print(f"Nav vertex {nav_idx}: Too far from weather data ({distance:.0f}m)")
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
            raise HTTPException(400,f"Only {len(navigable_vertices)}/{len(vertices)} vertices are navigable.")

        route_svc = RouteService(session)
        yacht_svc = YachtService(session)

        route = await route_svc.get_entity_by_id(meshed.route_id, allow_none=False)
        yacht = await yacht_svc.get_entity_by_id(route.yacht_id, allow_none=False)

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
            raise HTTPException(400, "Start or stop point not found")


        transformer = Transformer.from_crs(4326, meshed.crs_epsg, always_xy=True)

        start_xy = transformer.transform(start_point.x, start_point.y)
        stop_xy = transformer.transform(stop_point.x, stop_point.y)

        start_vertex_idx = np.argmin(np.sum((vertices - start_xy) ** 2, axis=1))
        if start_vertex_idx not in navigable_vertices:
            raise HTTPException(400, "Start point is not in navigable area (no weather data)")

        stop_vertex_idx = np.argmin(np.sum((vertices - stop_xy) ** 2, axis=1))
        if stop_vertex_idx not in navigable_vertices:
            raise HTTPException(400, "Stop point is not in navigable area (no weather data)")

        router_instance = SailingRouter(navigation_mesh, verified_weather_data, yacht)

        heuristics = SailingHeuristics(yacht, weather_mapping, verified_weather_data)

        nav_points = await rpoint_svc.get_all_entities(
            filters={
                'route_id': meshed.route_id,
                'point_type': RoutePointType.NAVIGATION
            },
            page=1,
            limit=10000
        )

        POSITION_TOLERANCE = 10.0

        db_points_local = []
        for np_obj in nav_points:
            np_xy = transformer.transform(np_obj.x, np_obj.y)
            db_points_local.append((np_xy, np_obj))

        if len(db_points_local) > 0:
            db_positions = np.array([p[0] for p in db_points_local])
            db_tree = KDTree(db_positions)

            matched = 0
            updates = []

            for vertex_idx in navigable_vertices:
                vertex = vertices[vertex_idx]
                dist, db_idx = db_tree.query(vertex, k=1)

                if dist < POSITION_TOLERANCE:
                    h_score = heuristics.calculate_heuristic_cost(
                        tuple(vertex),
                        stop_xy,
                        vertex_idx
                    )

                    if np.isfinite(h_score):
                        db_point = db_points_local[db_idx][1]
                        updates.append({
                            'id': db_point.id,
                            'heuristic_score': float(h_score),
                            'meshed_area_id': meshed_area_id
                        })
                        matched += 1

            if updates:
                for update_data in updates:
                    update_stmt = (
                        update(RoutePoint)
                        .where(RoutePoint.id == update_data['id'])
                        .values(
                            heuristic_score=update_data['heuristic_score'],
                            meshed_area_id=update_data['meshed_area_id']
                        )
                    )
                    await session.execute(update_stmt)

                await session.commit()


        optimal_path = router_instance.find_optimal_route(
            start=start_xy,
            goal=stop_xy,
            weather_mapping=weather_mapping
        )

        if not optimal_path:
            safe_router = SailingRouter(
                navigation_mesh,
                verified_weather_data,
                yacht,
                heuristics_cls=lambda *args, **kwargs: SafeHeuristics(
                    *args, **kwargs, non_navigable=non_navigable_vertices
                )
            )

            optimal_path = safe_router.find_optimal_route(
                start=start_xy,
                goal=stop_xy,
                weather_mapping=weather_mapping
            )

            if not optimal_path:
                raise HTTPException(400, "No navigable route found. Check weather coverage and water depth.")

        transformer_back = Transformer.from_crs(meshed.crs_epsg, 4326, always_xy=True)
        path_wgs84 = [
            transformer_back.transform(p[0], p[1]) for p in optimal_path
        ]

        segments = []
        total_time = 0.0
        total_distance = 0.0
        invalid_segments = 0

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
                    "point_of_sail": _get_point_of_sail(abs(twa)),
                    "wave_height_m": float(conditions.wave_height),
                    "validated": True
                })

                total_time += segment_cost
                total_distance += distance

            except Exception as e:
                invalid_segments += 1

        if len(segments) == 0:
            raise HTTPException(400, "No valid segments in route")

        route_data = {
            "meshed_area_id": str(meshed_area_id),
            "calculated_at": datetime.utcnow().isoformat(),
            "yacht": {"id": str(yacht.id), "name": yacht.name, "type": yacht.yacht_type},
            "route": {
                "waypoints_count": len(optimal_path),
                "waypoints_local": [(float(p[0]), float(p[1])) for p in optimal_path],
                "waypoints_wgs84": [(float(p[0]), float(p[1])) for p in path_wgs84],
                "segments_count": len(segments),
                "segments": segments,
                "total_time_hours": float(total_time / 3600),
                "total_distance_nm": float(total_distance / 1852.0),
                "average_speed_knots": float((total_distance / 1852.0) / (total_time / 3600)) if total_time > 0 else 0
            },
            "validation": {
                "valid_weather_points": len(verified_weather_data),
                "navigable_vertices": len(navigable_vertices)
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


        optimizer = SegmentOptimizer(bearing_tolerance=5.0)
        optimized_segments = optimizer.optimize_segments(segments)

        await session.execute(delete(RouteSegments).where(RouteSegments.route_id == meshed.route_id))
        await session.commit()

        for idx, opt_seg in enumerate(optimized_segments):
            from_point = await _get_or_create_route_point(
                session, meshed.route_id,
                opt_seg.from_point_wgs84[0], opt_seg.from_point_wgs84[1],
                idx * 2, RoutePointType.NAVIGATION
            )

            to_point = await _get_or_create_route_point(
                session, meshed.route_id,
                opt_seg.to_point_wgs84[0], opt_seg.to_point_wgs84[1],
                idx * 2 + 1, RoutePointType.NAVIGATION
            )

            maneuver_type = None
            if opt_seg.has_tack:
                maneuver_type = "TACK"
            elif opt_seg.has_jibe:
                maneuver_type = "JIBE"

            new_segment = RouteSegments(
                route_id=meshed.route_id,
                from_point=from_point.id,
                to_point=to_point.id,
                segment_order=idx,
                recommended_course=opt_seg.avg_bearing,
                estimated_time=opt_seg.total_time_hours * 60,  # Convert to minutes
                sail_type=_determine_sail_type(opt_seg.avg_twa, opt_seg.avg_wind_speed_knots),
                tack_type=opt_seg.predominant_point_of_sail,
                maneuver_type=maneuver_type,
                distance_nm=opt_seg.total_distance_nm,
                bearing=opt_seg.avg_bearing,
                wind_angle=opt_seg.avg_twa,
                current_effect=0.0
            )

            session.add(new_segment)

        final_total_time_minutes = sum(seg.total_time_hours * 60 for seg in optimized_segments)
        stmt_route = (
            update(Route)
            .where(Route.id == meshed.route_id)
            .values(estimated_duration=final_total_time_minutes)
        )
        await session.execute(stmt_route)

        await session.commit()

        return {
            "meshed_area_id": str(meshed_area_id),
            "yacht": {
                "id": str(yacht.id),
                "name": yacht.name,
                "type": yacht.yacht_type
            },
            "route": {
                "waypoints_count": len(optimal_path),
                "waypoints_local": [(float(p[0]), float(p[1])) for p in optimal_path],
                "waypoints_wgs84": [(float(p[0]), float(p[1])) for p in path_wgs84],
                "segments_count": len(segments),
                "segments": segments,
                "total_time_seconds": float(total_time),
                "total_time_hours": float(total_time / 3600),
                "total_distance_m": float(total_distance),
                "total_distance_nm": float(total_distance / 1852.0),
                "average_speed_knots": float((total_distance / 1852.0) / (total_time / 3600)) if total_time > 0 else 0
            },
            "validation": {
                "navigable_vertices": len(navigable_vertices),
                "total_vertices": len(vertices),
                "coverage_percent": (len(navigable_vertices) / len(vertices) * 100),
                "valid_weather_points": len(verified_weather_data),
                "total_weather_points": len(weather_points),
                "invalid_segments": invalid_segments
            }
        }

    except HTTPException:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(500, f"Failed to calculate route: {str(e)}")

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

async def save_calculated_route_to_db(session: AsyncSession, meshed_area_id: UUID4, route_data: dict) -> None:
    mesh_svc = MeshedAreaService(session)

    route_data['calculated_at'] = datetime.utcnow().isoformat()
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

async def _get_or_create_route_point(
        session: AsyncSession,
        route_id: UUID4,
        lon: float,
        lat: float,
        seq_idx: int,
        point_type: RoutePointType
) -> RoutePoint:
    TOLERANCE = 0.00001  # ~1 meter

    query = (
        select(RoutePoint)
        .where(RoutePoint.route_id == route_id)
        .where(RoutePoint.x.between(lon - TOLERANCE, lon + TOLERANCE))
        .where(RoutePoint.y.between(lat - TOLERANCE, lat + TOLERANCE))
        .where(RoutePoint.point_type == point_type)
    )

    result = await session.execute(query)
    existing = result.scalar_one_or_none()

    if existing:
        return existing

    new_point = RoutePoint(
        route_id=route_id,
        point_type=point_type,
        seq_idx=seq_idx,
        x=lon,
        y=lat,
        timestamp=datetime.utcnow()
    )

    session.add(new_point)
    await session.flush()

    return new_point


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