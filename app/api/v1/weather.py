from __future__ import annotations

import json
import numpy as np
from typing import Optional, List
from datetime import datetime

from pydantic import UUID4
from sqlalchemy.ext.asyncio import AsyncSession
from pyproj import Transformer

from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from fastapi import Query
from sqlalchemy import select

from app.core.database import get_db as get_async_session
from app.models.models import RoutePointType, RoutePoint, WeatherForecast
from app.services.db.services import MeshedAreaService, RoutePointService, WeatherForecastService
from app.schemas.db_create import WeatherForecastCreate, RoutePointCreate
from app.services.weather.weather_api_manager import OpenMeteoService
from app.schemas.weather import WeatherBatchResponse, WeatherPointResponse

router = APIRouter()

_weather_service: Optional[OpenMeteoService] = None


def get_weather_service() -> OpenMeteoService:
    """Get or create weather service instance"""
    global _weather_service
    if _weather_service is None:
        _weather_service = OpenMeteoService(
            redis_url=None,
            max_calls_per_minute=500,
            cache_ttl=3600
        )
    return _weather_service


@router.post("/{meshed_area_id}/fetch-weather",
             response_model=WeatherBatchResponse,
             status_code=200,
             description="Fetch marine weather data - only saves valid data, no defaults")
async def fetch_weather_for_mesh(
        meshed_area_id: UUID4,
        save_to_db: bool = Query(True, description="Save weather data to database"),
        allow_defaults: bool = Query(False, description="Allow saving default/fallback data"),
        session: AsyncSession = Depends(get_async_session),
        service: OpenMeteoService = Depends(get_weather_service)
):
    """
    Fetch weather data for all weather points.
    Only saves data that was successfully retrieved from API.
    Points with failed API calls are skipped unless allow_defaults=True.
    """
    try:
        print("\n" + "=" * 60)
        print("WEATHER FETCHING WITH VALIDATION")
        print("=" * 60)

        mesh_svc = MeshedAreaService(session)
        rpoint_svc = RoutePointService(session)
        wf_svc = WeatherForecastService(session)

        meshed = await mesh_svc.get_entity_by_id(meshed_area_id, allow_none=False)

        if not meshed:
            raise HTTPException(404, f"MeshedArea {meshed_area_id} not found")

        # Get weather points configuration
        weather_points_data = {}
        if meshed.weather_points_json:
            weather_points_data = json.loads(meshed.weather_points_json)

        if not weather_points_data:
            weather_points = await _extract_weather_points(meshed)
        else:
            weather_points = [(p['x'], p['y']) for p in weather_points_data.get('points', [])]

        if not weather_points:
            raise HTTPException(400, "No weather points found for this mesh")

        print(f"Found {len(weather_points)} weather points to fetch")

        # Transform to WGS84 if needed
        epsg = int(meshed.crs_epsg or 4326)
        if epsg != 4326:
            transformer = Transformer.from_crs(epsg, 4326, always_xy=True)
            weather_points_wgs84 = [
                transformer.transform(x, y) for x, y in weather_points
            ]
        else:
            weather_points_wgs84 = weather_points

        # Check for existing weather points in database
        existing_weather_points = await rpoint_svc.get_all_entities(
            filters={
                'meshed_area_id': meshed_area_id,
                'point_type': RoutePointType.WEATHER
            },
            page=1,
            limit=1000
        )

        weather_point_ids = []

        # Create weather points if they don't exist
        if not existing_weather_points or len(existing_weather_points) == 0:
            print("Creating weather points in database...")
            for idx, (lon, lat) in enumerate(weather_points_wgs84):
                rp = await rpoint_svc.create_entity(
                    model_data=RoutePointCreate(
                        route_id=meshed.route_id,
                        meshed_area_id=meshed_area_id,
                        point_type=RoutePointType.WEATHER,
                        seq_idx=1000 + idx,
                        x=lon,
                        y=lat
                    )
                )
                weather_point_ids.append(rp.id)
        else:
            weather_point_ids = [p.id for p in existing_weather_points]
            print(f"Using {len(weather_point_ids)} existing weather points")

        # Track statistics
        initial_stats = service.get_stats()

        # Fetch weather data from API
        print("Fetching weather data from Open-Meteo API...")
        weather_data = await service.fetch_batch(
            [(lat, lon) for lon, lat in weather_points_wgs84],
            priorities=None
        )

        final_stats = service.get_stats()

        # Process results with validation
        response_points = []
        successful = 0
        failed = 0
        skipped = 0
        current_time = datetime.utcnow()

        for idx, data in weather_data.items():
            lon, lat = weather_points_wgs84[idx]

            # Check if this is default/fallback data
            is_default = data.get('is_default', False)

            # Validate data completeness
            required_fields = ['wind_speed', 'wind_direction', 'wave_height', 'wave_period']
            has_all_data = all(
                field in data and data[field] is not None and np.isfinite(data[field])
                for field in required_fields
            )

            if is_default:
                if allow_defaults:
                    print(f"⚠️ Point {idx}: Using default data (API failed)")
                    failed += 1
                else:
                    print(f"❌ Point {idx}: Skipping - API failed, defaults not allowed")
                    skipped += 1
                    continue
            elif not has_all_data:
                print(f"❌ Point {idx}: Skipping - incomplete data from API")
                skipped += 1
                continue
            else:
                successful += 1
                print(f"✓ Point {idx}: Valid data received")

            # Save to database if requested and data is valid
            if save_to_db and idx < len(weather_point_ids):
                # Additional validation before saving
                wind_speed = data.get('wind_speed', 0.0)
                wind_direction = data.get('wind_direction', 0.0)

                # Sanity checks
                if wind_speed < 0 or wind_speed > 50:  # m/s
                    print(f"⚠️ Point {idx}: Unrealistic wind speed {wind_speed} m/s")
                    if not allow_defaults:
                        skipped += 1
                        continue

                if wind_direction < 0 or wind_direction >= 360:
                    wind_direction = wind_direction % 360

                # Create forecast record
                weather_forecast = await wf_svc.create_entity(
                    model_data=WeatherForecastCreate(
                        route_point_id=weather_point_ids[idx],
                        forecast_timestamp=current_time,
                        temperature=data.get('temperature'),
                        humidity=data.get('humidity'),
                        pressure=data.get('pressure'),
                        wind_speed=wind_speed,
                        wind_direction=wind_direction,
                        wind_gusts=data.get('wind_gusts'),
                        wave_height=data.get('wave_height'),
                        wave_direction=data.get('wave_direction'),
                        wave_period=data.get('wave_period'),
                        wind_wave_height=data.get('wind_wave_height'),
                        swell_wave_height=data.get('swell_wave_height'),
                        current_velocity=data.get('current_velocity'),
                        current_direction=data.get('current_direction'),
                        source=data.get('source', 'open-meteo'),
                        is_default=is_default
                    )
                )

            # Add to response
            response_points.append(WeatherPointResponse(
                index=idx,
                lat=lat,
                lon=lon,
                wind_speed=data.get('wind_speed', 0.0),
                wind_direction=data.get('wind_direction', 0.0),
                wind_gusts=data.get('wind_gusts', 0.0),
                wave_height=data.get('wave_height', 0.0),
                wave_direction=data.get('wave_direction', 0.0),
                wave_period=data.get('wave_period', 0.0),
                wind_wave_height=data.get('wind_wave_height', 0.0),
                swell_wave_height=data.get('swell_wave_height', 0.0),
                current_velocity=data.get('current_velocity', 0.0),
                current_direction=data.get('current_direction', 0.0),
                temperature=data.get('temperature', 0.0),
                humidity=data.get('humidity', 0.0),
                pressure=data.get('pressure', 0.0),
                timestamp=data.get('timestamp', ''),
                is_default=is_default
            ))

        # Update weather points metadata
        weather_points_metadata = {
            'points': [
                {
                    'idx': idx,
                    'x': weather_points[idx][0],
                    'y': weather_points[idx][1],
                    'lon': weather_points_wgs84[idx][0],
                    'lat': weather_points_wgs84[idx][1],
                    'route_point_id': str(weather_point_ids[idx]) if idx < len(weather_point_ids) else None,
                    'has_valid_data': idx in [p.index for p in response_points if not p.is_default]
                }
                for idx in range(len(weather_points))
            ],
            'last_updated': current_time.isoformat(),
            'valid_points': successful,
            'failed_points': failed,
            'skipped_points': skipped
        }

        meshed.weather_points_json = json.dumps(weather_points_metadata)
        await session.commit()

        print("\n" + "=" * 60)
        print("WEATHER FETCHING SUMMARY")
        print("=" * 60)
        print(f"✅ Successful: {successful} points")
        print(f"❌ Failed: {failed} points")
        print(f"⚠️ Skipped: {skipped} points")
        print(f"📊 API calls: {final_stats['api_calls'] - initial_stats['api_calls']}")
        print(f"💾 Cache hits: {final_stats['cache_hits'] - initial_stats['cache_hits']}")

        if successful < len(weather_points) * 0.5:
            print(f"\n⚠️ WARNING: Only {successful}/{len(weather_points)} points have valid data!")
            print("Consider:")
            print("  1. Checking API connectivity")
            print("  2. Verifying coordinates are in marine areas")
            print("  3. Using allow_defaults=True for testing")

        return WeatherBatchResponse(
            meshed_area_id=meshed_area_id,
            total_points=len(weather_points),
            successful=successful,
            failed=failed,
            cache_hits=final_stats['cache_hits'] - initial_stats['cache_hits'],
            api_calls=final_stats['api_calls'] - initial_stats['api_calls'],
            points=response_points
        )

    except HTTPException:
        raise
    except Exception as e:
        await session.rollback()
        import traceback
        traceback.print_exc()
        raise HTTPException(500, f"Failed to fetch weather: {str(e)}")


@router.get("/{meshed_area_id}/weather-validation",
            status_code=200,
            description="Check weather data validation status")
async def validate_weather_data(
        meshed_area_id: UUID4,
        session: AsyncSession = Depends(get_async_session)
):
    """
    Check which weather points have valid (non-default) data.
    """
    try:
        mesh_svc = MeshedAreaService(session)
        meshed = await mesh_svc.get_entity_by_id(meshed_area_id, allow_none=False)

        if not meshed:
            raise HTTPException(404, f"MeshedArea {meshed_area_id} not found")

        # Get weather points
        from app.services.db.services import RoutePointService
        rpoint_svc = RoutePointService(session)

        weather_points = await rpoint_svc.get_all_entities(
            filters={
                'meshed_area_id': meshed_area_id,
                'point_type': RoutePointType.WEATHER
            },
            page=1,
            limit=1000
        )

        validation_results = []

        for wp in weather_points:
            # Get latest non-default forecast
            query = (
                select(WeatherForecast)
                .where(WeatherForecast.route_point_id == wp.id)
                .order_by(WeatherForecast.forecast_timestamp.desc())
                .limit(1)
            )
            result = await session.execute(query)
            forecast = result.scalar_one_or_none()

            if forecast:
                # Check if data is complete
                is_valid = (
                        forecast.wind_speed is not None and
                        forecast.wind_direction is not None and
                        forecast.wave_height is not None and
                        not forecast.is_default
                )

                validation_results.append({
                    "point_id": str(wp.id),
                    "seq_idx": wp.seq_idx,
                    "lon": wp.x,
                    "lat": wp.y,
                    "has_data": True,
                    "is_valid": is_valid,
                    "is_default": forecast.is_default,
                    "wind_speed": forecast.wind_speed,
                    "wave_height": forecast.wave_height,
                    "timestamp": forecast.forecast_timestamp.isoformat() if forecast.forecast_timestamp else None
                })
            else:
                validation_results.append({
                    "point_id": str(wp.id),
                    "seq_idx": wp.seq_idx,
                    "lon": wp.x,
                    "lat": wp.y,
                    "has_data": False,
                    "is_valid": False,
                    "is_default": None,
                    "wind_speed": None,
                    "wave_height": None,
                    "timestamp": None
                })

        # Summary statistics
        total = len(validation_results)
        with_data = sum(1 for r in validation_results if r['has_data'])
        valid = sum(1 for r in validation_results if r['is_valid'])
        defaults = sum(1 for r in validation_results if r.get('is_default', False))

        return {
            "meshed_area_id": str(meshed_area_id),
            "summary": {
                "total_points": total,
                "points_with_data": with_data,
                "valid_points": valid,
                "default_points": defaults,
                "missing_data": total - with_data,
                "coverage_percent": (valid / total * 100) if total > 0 else 0
            },
            "validation_results": validation_results
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Failed to validate weather data: {str(e)}")


async def _extract_weather_points(meshed_area) -> List[tuple[float, float]]:
    """Extract weather points from meshed area."""
    nodes = np.array(json.loads(meshed_area.nodes_json))
    step = max(1, len(nodes) // 30)
    selected_indices = list(range(0, len(nodes), step))[:30]
    weather_points = nodes[selected_indices]
    return [(float(p[0]), float(p[1])) for p in weather_points]