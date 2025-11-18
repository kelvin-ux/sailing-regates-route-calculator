from __future__ import annotations

import json
import numpy as np
from typing import Dict
from typing import List
from typing import Tuple

from pydantic import UUID4
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException

from app.core.database import get_db as get_async_session
from app.services.db.services import MeshedAreaService
from app.services.db.services import YachtService
from app.services.db.services import RoutePointService
from app.services.routing.heuristics import SailingHeuristics
from app.services.routing.heuristics import SailingRouter

router = APIRouter()


@router.post("/{meshed_area_id}/calculate-route",
             status_code=200,
             description="Calculate optimal sailing route using A*")
async def calculate_optimal_route(
        meshed_area_id: UUID4,
        session: AsyncSession = Depends(get_async_session)
):
    """
    Calculates optimal sailing route using A* algorithm with heuristics.
    Also saves heuristic scores to database.
    """
    try:
        mesh_svc = MeshedAreaService(session)
        meshed = await mesh_svc.get_entity_by_id(meshed_area_id, allow_none=False)

        if not meshed:
            raise HTTPException(404, f"Mesh {meshed_area_id} not found")

        # Load mesh data
        navigation_mesh = {
            'vertices': json.loads(meshed.nodes_json),
            'triangles': json.loads(meshed.triangles_json)
        }

        vertices = np.array(navigation_mesh['vertices'])

        weather_points_data = json.loads(meshed.weather_points_json) if meshed.weather_points_json else None
        if not weather_points_data:
            raise HTTPException(400, "No weather points. Run fetch-weather first.")

        weather_mapping = weather_points_data.get('mapping', {})
        weather_mapping = {int(k): v for k, v in weather_mapping.items()}

        # Get weather data
        from app.services.db.services import RoutePointService
        from app.models.models import RoutePointType, WeatherForecast, RoutePoint
        from sqlalchemy import select, update

        rpoint_svc = RoutePointService(session)
        weather_points = await rpoint_svc.get_all_entities(
            filters={
                'meshed_area_id': meshed_area_id,
                'point_type': RoutePointType.WEATHER
            },
            page=1,
            limit=1000
        )

        weather_data = {}
        for wp in weather_points:
            query = (
                select(WeatherForecast)
                .where(WeatherForecast.route_point_id == wp.id)
                .order_by(WeatherForecast.forecast_timestamp.desc())
                .limit(1)
            )
            result = await session.execute(query)
            forecast = result.scalar_one_or_none()

            if forecast:
                idx = wp.seq_idx - 1000
                weather_data[idx] = {
                    'wind_speed_10m': forecast.wind_speed,
                    'wind_direction_10m': forecast.wind_direction,
                    'wave_height': forecast.wave_height or 0.5,
                    'wave_direction': forecast.wave_direction or 0.0,
                    'wave_period': forecast.wave_period or 4.0,
                    'current_speed': forecast.current_velocity or 0.1,
                    'current_direction': forecast.current_direction or 0.0,
                }

        # Load yacht
        from app.services.db.services import RouteService, YachtService
        route_svc = RouteService(session)
        yacht_svc = YachtService(session)

        route = await route_svc.get_entity_by_id(meshed.route_id, allow_none=False)
        yacht = await yacht_svc.get_entity_by_id(route.yacht_id, allow_none=False)

        # Find start and stop points
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

        # Transform coordinates to local CRS
        from pyproj import Transformer
        transformer = Transformer.from_crs(4326, meshed.crs_epsg, always_xy=True)

        start_xy = transformer.transform(start_point.x, start_point.y)
        stop_xy = transformer.transform(stop_point.x, stop_point.y)

        # Create router and find route
        router = SailingRouter(navigation_mesh, weather_data, yacht)

        # Initialize heuristics for score calculation
        heuristics = SailingHeuristics(yacht, weather_mapping, weather_data)

        # Calculate heuristic scores for all vertices and save to DB
        goal_xy = stop_xy

        print(f"Calculating heuristic scores for {len(vertices)} vertices...")

        # Update existing navigation points with heuristic scores
        nav_points = await rpoint_svc.get_all_entities(
            filters={
                'route_id': meshed.route_id,
                'point_type': RoutePointType.NAVIGATION
            },
            page=1,
            limit=10000
        )

        # Create a mapping of approximate position to RoutePoint
        nav_points_by_pos = {}
        for np_obj in nav_points:
            # Transform to local coordinates
            np_xy = transformer.transform(np_obj.x, np_obj.y)
            # Round to nearest meter for matching
            key = (round(np_xy[0]), round(np_xy[1]))
            nav_points_by_pos[key] = np_obj

        # Calculate and update heuristic scores
        matched = 0
        for i, vertex in enumerate(vertices):
            h_score = heuristics.calculate_heuristic_cost(
                tuple(vertex),
                goal_xy,
                i
            )

            # Find corresponding RoutePoint
            key = (round(vertex[0]), round(vertex[1]))
            if key in nav_points_by_pos:
                matched += 1
                rp = nav_points_by_pos[key]
                # Update heuristic score and meshed_area_id
                update_stmt = (
                    update(RoutePoint)
                    .where(RoutePoint.id == rp.id)
                    .values(
                        heuristic_score=float(h_score),
                        meshed_area_id=meshed_area_id
                    )
                )
                await session.execute(update_stmt)

        await session.commit()
        print(f"Heuristic scores saved to database {matched} occurences ")

        # Find optimal path
        router = SailingRouter(navigation_mesh, weather_data, yacht)

        optimal_path = router.find_optimal_route(
            start=start_xy,
            goal=stop_xy,
            weather_mapping=weather_mapping
        )

        if not optimal_path:
            print("No path found with current conditions, trying relaxed parameters...")

            class RelaxedHeuristics(SailingHeuristics):
                def __init__(self, *args, **kwargs):
                    super().__init__(*args, **kwargs)
                    self.DEAD_ANGLE = 0.0

            # drugi router z poluzowaną heurystyką
            relaxed_router = SailingRouter(
                navigation_mesh,
                weather_data,
                yacht,
                heuristics_cls=RelaxedHeuristics,
            )

            optimal_path = relaxed_router.find_optimal_route(
                start=start_xy,
                goal=stop_xy,
                weather_mapping=weather_mapping
            )

            if not optimal_path:
                raise HTTPException(400, "No route found even with relaxed conditions")
        # Convert back to WGS84
        transformer_back = Transformer.from_crs(meshed.crs_epsg, 4326, always_xy=True)
        path_wgs84 = [
            transformer_back.transform(p[0], p[1]) for p in optimal_path
        ]

        # Calculate segment details
        segments = []
        total_time = 0.0
        total_distance = 0.0

        for i in range(len(optimal_path) - 1):
            from_pt = optimal_path[i]
            to_pt = optimal_path[i + 1]

            # Find vertex indices
            from_idx = np.argmin(np.sum((vertices - from_pt) ** 2, axis=1))
            to_idx = np.argmin(np.sum((vertices - to_pt) ** 2, axis=1))

            # Calculate segment cost and details
            segment_cost = heuristics.calculate_edge_cost(
                from_pt, to_pt, from_idx, to_idx,
                previous_heading=None if i == 0 else heuristics._calculate_bearing(optimal_path[i - 1], from_pt)
            )

            distance = heuristics._calculate_distance(from_pt, to_pt)
            bearing = heuristics._calculate_bearing(from_pt, to_pt)

            # Get conditions
            try:
                conditions = heuristics._get_conditions_at_vertex(to_idx)
                twa = heuristics._calculate_twa(bearing, conditions.wind_direction)
                # Convert wind speed from knots to m/s for boat speed calculation
                wind_ms = conditions.wind_speed * 0.514444
                boat_speed = heuristics._get_boat_speed(wind_ms, abs(twa))

                # Determine point of sail
                point_of_sail = _get_point_of_sail(abs(twa))

                segments.append({
                    "from": {"x": from_pt[0], "y": from_pt[1], "lon": path_wgs84[i][0], "lat": path_wgs84[i][1]},
                    "to": {"x": to_pt[0], "y": to_pt[1], "lon": path_wgs84[i + 1][0], "lat": path_wgs84[i + 1][1]},
                    "distance_m": float(distance),
                    "distance_nm": float(distance / 1852.0),
                    "bearing": float(bearing),
                    "time_seconds": float(segment_cost),
                    "time_minutes": float(segment_cost / 60),
                    "boat_speed_ms": float(boat_speed),
                    "boat_speed_knots": float(boat_speed / 0.514444),
                    "wind_speed_knots": float(conditions.wind_speed),
                    "wind_direction": float(conditions.wind_direction),
                    "twa": float(twa),
                    "point_of_sail": point_of_sail,
                    "wave_height_m": float(conditions.wave_height)
                })

                total_time += segment_cost
                total_distance += distance
            except Exception as e:
                print(f"Error processing segment {i}: {e}")
                # Skip problematic segments
                pass

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
            "heuristics_saved": True,
            "weather_points_used": len(weather_data)
        }

    except HTTPException:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(500, f"Failed to calculate route: {str(e)}")


def _get_point_of_sail(twa: float) -> str:
    """Determine point of sail from True Wind Angle"""
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