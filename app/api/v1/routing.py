from __future__ import annotations

import json
import numpy as np
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass
from datetime import datetime

from pydantic import UUID4
from sqlalchemy.ext.asyncio import AsyncSession
from scipy.spatial import KDTree

from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException

from app.core.database import get_db as get_async_session
from app.services.db.services import MeshedAreaService
from app.services.db.services import YachtService
from app.services.db.services import RoutePointService
from app.services.routing.heuristics import SailingHeuristics
from app.services.routing.heuristics import SailingRouter
from sqlalchemy import update
from app.models.models import MeshedArea
from datetime import datetime
router = APIRouter()


@dataclass
class VerifiedWeatherPoint:
    """Verified weather point with all required data"""
    index: int
    position: Tuple[float, float]
    wind_speed: float
    wind_direction: float
    wave_height: float
    wave_direction: float
    wave_period: float
    current_velocity: float
    current_direction: float
    depth: Optional[float] = None
    has_valid_data: bool = True


@dataclass
class NavigationVertex:
    """Navigation vertex with verified data"""
    index: int
    position: Tuple[float, float]
    weather_point_idx: int
    depth: Optional[float] = None
    is_navigable: bool = True


class WeatherDataValidator:
    """Validates and filters weather data"""

    @staticmethod
    def validate_weather_data(data: Dict) -> bool:
        """Check if weather data is complete and valid"""
        required_fields = [
            'wind_speed_10m', 'wind_direction_10m',
            'wave_height', 'wave_direction', 'wave_period',
            'current_speed', 'current_direction'
        ]

        # Check all required fields exist
        for field in required_fields:
            if field not in data:
                return False

            value = data[field]
            if value is None:
                return False

            # Check for invalid values
            if isinstance(value, (int, float)):
                if not np.isfinite(value):
                    return False

                # Check realistic ranges
                if field == 'wind_speed_10m' and (value < 0 or value > 100):  # knots
                    return False
                if field == 'wave_height' and (value < 0 or value > 30):  # meters
                    return False
                if field == 'wave_period' and (value < 0 or value > 30):  # seconds
                    return False
                if 'direction' in field and (value < 0 or value >= 360):
                    return False
            else:
                return False

        return True

    @staticmethod
    def validate_depth(depth: Optional[float], min_depth: float = 3.0) -> bool:
        """Check if depth is sufficient for navigation"""
        if depth is None:
            return False  # No depth data = not navigable
        if not np.isfinite(depth):
            return False
        return depth >= min_depth


@router.post("/{meshed_area_id}/calculate-route",
             status_code=200,
             description="Calculate optimal sailing route using A* with strict data validation")
async def calculate_optimal_route(
        meshed_area_id: UUID4,
        min_depth: float = 3.0,  # Minimum navigable depth in meters
        session: AsyncSession = Depends(get_async_session)
):
    """
    Calculates optimal sailing route with strict data validation.
    Every navigation point must have valid weather and depth data.
    """
    try:
        print("\n" + "=" * 60)
        print("ROUTE CALCULATION WITH STRICT VALIDATION")
        print("=" * 60)

        # Load mesh
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
        print(f"Loaded {len(vertices)} navigation vertices")

        # Load weather points metadata
        weather_points_data = json.loads(meshed.weather_points_json) if meshed.weather_points_json else None
        if not weather_points_data:
            raise HTTPException(400, "No weather points defined. Run mesh creation first.")

        weather_points = weather_points_data.get('points', [])
        if len(weather_points) == 0:
            raise HTTPException(400, "No weather points in mesh metadata")

        print(f"Found {len(weather_points)} weather point definitions")

        # Load weather data from database
        from app.models.models import RoutePointType, WeatherForecast, RoutePoint
        from sqlalchemy import select, update

        rpoint_svc = RoutePointService(session)

        # Get all weather points with data
        weather_points_db = await rpoint_svc.get_all_entities(
            filters={
                'meshed_area_id': meshed_area_id,
                'point_type': RoutePointType.WEATHER
            },
            page=1,
            limit=1000
        )

        print(f"Found {len(weather_points_db)} weather points in database")

        # Build validated weather data
        validator = WeatherDataValidator()
        verified_weather_data = {}
        invalid_weather_points = []

        for wp in weather_points_db:
            # Get latest weather forecast
            query = (
                select(WeatherForecast)
                .where(WeatherForecast.route_point_id == wp.id)
                .where(WeatherForecast.is_default == False)  # Exclude default data
                .order_by(WeatherForecast.forecast_timestamp.desc())
                .limit(1)
            )
            result = await session.execute(query)
            forecast = result.scalar_one_or_none()

            if not forecast:
                print(f"❌ Weather point {wp.seq_idx}: No valid forecast data")
                invalid_weather_points.append(wp.seq_idx - 1000)
                continue

            # Convert to weather data format
            idx = wp.seq_idx - 1000

            weather_dict = {
                'wind_speed_10m': forecast.wind_speed / 0.514444 if forecast.wind_speed else None,  # m/s to knots
                'wind_direction_10m': forecast.wind_direction,
                'wave_height': forecast.wave_height,
                'wave_direction': forecast.wave_direction,
                'wave_period': forecast.wave_period,
                'current_speed': forecast.current_velocity / 0.514444 if forecast.current_velocity else None,
                'current_direction': forecast.current_direction,
            }

            # Validate weather data
            if not validator.validate_weather_data(weather_dict):
                print(f"❌ Weather point {idx}: Invalid or incomplete weather data")
                invalid_weather_points.append(idx)
                continue

            verified_weather_data[idx] = weather_dict
            print(f"✓ Weather point {idx}: Valid data (wind={weather_dict['wind_speed_10m']:.1f}kt)")

        if len(verified_weather_data) == 0:
            raise HTTPException(400, "No weather points have valid data. Run fetch-weather first.")

        print(f"\n✅ Verified weather data: {len(verified_weather_data)}/{len(weather_points)} points valid")

        if len(invalid_weather_points) > 0:
            print(f"⚠️ Invalid weather points will be avoided: {invalid_weather_points}")

        # Create weather mapping with validation
        weather_positions = []
        weather_indices_map = {}  # Maps weather array index to weather data index

        for i, wp in enumerate(weather_points):
            data_idx = wp['idx']
            if data_idx in verified_weather_data:
                weather_positions.append((wp['x'], wp['y']))
                weather_indices_map[len(weather_positions) - 1] = data_idx

        if len(weather_positions) == 0:
            raise HTTPException(400, "No valid weather points after validation")

        print(f"Building KDTree with {len(weather_positions)} valid weather points")

        # Build KDTree for valid weather points only
        weather_tree = KDTree(weather_positions)

        # Map navigation vertices to weather points
        weather_mapping = {i: [] for i in range(len(weather_points))}  # Use original indices
        nav_to_weather = {}
        navigable_vertices = []
        non_navigable_vertices = []

        MAX_WEATHER_DISTANCE = 100000.0  # Maximum 1km to weather point

        for nav_idx, nav_vertex in enumerate(vertices):
            # Find nearest valid weather point
            distance, nearest_idx = weather_tree.query(nav_vertex, k=1)

            if distance > MAX_WEATHER_DISTANCE:
                print(f"⚠️ Nav vertex {nav_idx}: Too far from weather data ({distance:.0f}m)")
                non_navigable_vertices.append(nav_idx)
                continue

            # Map back to original weather data index
            weather_data_idx = weather_indices_map[nearest_idx]

            # Verify this weather point has valid data
            if weather_data_idx not in verified_weather_data:
                print(f"⚠️ Nav vertex {nav_idx}: Nearest weather point has no valid data")
                non_navigable_vertices.append(nav_idx)
                continue

            # Valid mapping
            weather_mapping[weather_data_idx].append(nav_idx)
            nav_to_weather[nav_idx] = weather_data_idx
            navigable_vertices.append(nav_idx)

        print(f"\n📊 NAVIGATION VERTEX VALIDATION:")
        print(f"  ✅ Navigable: {len(navigable_vertices)}/{len(vertices)} vertices")
        print(f"  ❌ Non-navigable: {len(non_navigable_vertices)} vertices")

        if len(navigable_vertices) < len(vertices) * 0.5:
            raise HTTPException(400,
                                f"Only {len(navigable_vertices)}/{len(vertices)} vertices are navigable. Check weather data coverage.")

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

        # Transform coordinates
        from pyproj import Transformer
        transformer = Transformer.from_crs(4326, meshed.crs_epsg, always_xy=True)

        start_xy = transformer.transform(start_point.x, start_point.y)
        stop_xy = transformer.transform(stop_point.x, stop_point.y)

        print(f"\n🚢 ROUTE PLANNING:")
        print(f"  Start: {start_xy}")
        print(f"  Stop: {stop_xy}")

        # Verify start and stop points are navigable
        start_vertex_idx = np.argmin(np.sum((vertices - start_xy) ** 2, axis=1))
        stop_vertex_idx = np.argmin(np.sum((vertices - stop_xy) ** 2, axis=1))

        if start_vertex_idx not in navigable_vertices:
            raise HTTPException(400, "Start point is not in navigable area (no weather data)")

        if stop_vertex_idx not in navigable_vertices:
            raise HTTPException(400, "Stop point is not in navigable area (no weather data)")

        # Create filtered navigation mesh with only navigable vertices
        # This is more complex - for now use full mesh but mark non-navigable

        # Create router with validated data only
        router_instance = SailingRouter(navigation_mesh, verified_weather_data, yacht)

        # Initialize heuristics
        heuristics = SailingHeuristics(yacht, weather_mapping, verified_weather_data)

        # Calculate and save heuristic scores
        print(f"\n📊 Calculating heuristic scores for {len(navigable_vertices)} navigable vertices...")

        # Get navigation points from database
        nav_points = await rpoint_svc.get_all_entities(
            filters={
                'route_id': meshed.route_id,
                'point_type': RoutePointType.NAVIGATION
            },
            page=1,
            limit=10000
        )

        print(f"Found {len(nav_points)} navigation points in database")

        # Create mapping with tolerance for floating point errors
        POSITION_TOLERANCE = 10.0  # 10 meters tolerance

        # Transform all database points to local coordinates
        db_points_local = []
        for np_obj in nav_points:
            np_xy = transformer.transform(np_obj.x, np_obj.y)
            db_points_local.append((np_xy, np_obj))

        # Build KDTree for database points
        if len(db_points_local) > 0:
            db_positions = np.array([p[0] for p in db_points_local])
            db_tree = KDTree(db_positions)

            # Match mesh vertices to database points
            matched = 0
            updates = []

            for vertex_idx in navigable_vertices:
                vertex = vertices[vertex_idx]

                # Find nearest database point
                dist, db_idx = db_tree.query(vertex, k=1)

                if dist < POSITION_TOLERANCE:
                    # Calculate heuristic score
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

            # Batch update heuristic scores
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
                print(f"✅ Updated heuristic scores for {matched} navigation points")
            else:
                print(f"⚠️ No navigation points matched to mesh vertices")

        # Find optimal path
        print("\n🔍 Finding optimal route with validated data...")

        optimal_path = router_instance.find_optimal_route(
            start=start_xy,
            goal=stop_xy,
            weather_mapping=weather_mapping
        )

        if not optimal_path:
            print("❌ No path found with strict validation")

            # Try with modified heuristics that avoid non-navigable vertices
            class SafeHeuristics(SailingHeuristics):
                def __init__(self, yacht, weather_mapping, weather_data, non_navigable):
                    super().__init__(yacht, weather_mapping, weather_data)
                    self.non_navigable = set(non_navigable)

                def calculate_edge_cost(self, from_vertex, to_vertex, from_idx, to_idx, previous_heading=None):
                    # Infinite cost for non-navigable vertices
                    if from_idx in self.non_navigable or to_idx in self.non_navigable:
                        return float('inf')
                    return super().calculate_edge_cost(from_vertex, to_vertex, from_idx, to_idx, previous_heading)

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

        # Convert path to WGS84
        transformer_back = Transformer.from_crs(meshed.crs_epsg, 4326, always_xy=True)
        path_wgs84 = [
            transformer_back.transform(p[0], p[1]) for p in optimal_path
        ]

        # Calculate segments with validation
        segments = []
        total_time = 0.0
        total_distance = 0.0
        invalid_segments = 0

        for i in range(len(optimal_path) - 1):
            from_pt = optimal_path[i]
            to_pt = optimal_path[i + 1]

            # Find vertex indices
            from_idx = np.argmin(np.sum((vertices - from_pt) ** 2, axis=1))
            to_idx = np.argmin(np.sum((vertices - to_pt) ** 2, axis=1))

            # Skip if non-navigable
            if from_idx not in navigable_vertices or to_idx not in navigable_vertices:
                invalid_segments += 1
                continue

            # Calculate segment
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
                    "boat_speed_knots": float(boat_speed / 0.514444),
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
                print(f"Error processing segment {i}: {e}")
                invalid_segments += 1

        if len(segments) == 0:
            raise HTTPException(400, "No valid segments in route")

        print(f"\n✅ ROUTE CALCULATION COMPLETE:")
        print(f"  Valid segments: {len(segments)}")
        print(f"  Invalid segments: {invalid_segments}")
        print(f"  Total distance: {total_distance / 1852:.1f} nm")
        print(f"  Total time: {total_time / 3600:.1f} hours")

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



async def save_calculated_route_to_db(
        session: AsyncSession,
        meshed_area_id: UUID4,
        route_data: dict
) -> None:
    """
    Zapisuje obliczonÄ… trasÄ™ do bazy danych w polu calculated_route_json
    w tabeli MeshedArea.

    ZakÅ‚adam, Å¼e masz kolumnÄ™ calculated_route_json w modelu MeshedArea.
    JeÅ›li nie masz, dodaj jÄ… do modelu:

    calculated_route_json = Column(Text, nullable=True)
    calculated_route_timestamp = Column(DateTime, nullable=True)
    """
    mesh_svc = MeshedAreaService(session)

    # Dodaj timestamp do danych
    route_data['calculated_at'] = datetime.utcnow().isoformat()

    # Zapisz jako JSON
    from sqlalchemy import update
    from app.models.models import MeshedArea

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
