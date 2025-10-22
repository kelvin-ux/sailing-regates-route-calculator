from __future__ import annotations

import json
import numpy as np
from typing import Optional
from typing import List
from datetime import datetime
from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession
from pyproj import Transformer

from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from fastapi import Query
from pydantic import UUID4
from sqlalchemy import select
from sqlalchemy import and_

from app.core.database import get_db as get_async_session
from app.models.models import RoutePointType
from app.models.models import RoutePoint
from app.models.models import WeatherForecast
from app.services.db.services import MeshedAreaService
from app.services.db.services import RoutePointService
from app.services.db.services import WeatherForecastService
from app.schemas.db_create import WeatherForecastCreate
from app.schemas.db_create import RoutePointCreate

from app.services.weather.weather_api_manager import OpenMeteoService
from app.schemas.weather import WeatherBatchResponse
from app.schemas.weather import WeatherPointResponse

router = APIRouter()

_weather_service: Optional[OpenMeteoService] = None


def get_weather_service() -> OpenMeteoService:
    """Get or create weather service instance """
    global _weather_service
    if _weather_service is None:
        _weather_service = OpenMeteoService(
            redis_url=None,  # "redis://localhost:6379"
            max_calls_per_minute=500,
            cache_ttl=3600  # 1 hour cache
        )
    return _weather_service


@router.post("/{meshed_area_id}/fetch-weather",
             response_model=WeatherBatchResponse,
             status_code=200,
             description="Fetch current marine weather data for weather points")
async def fetch_weather_for_mesh(
        meshed_area_id: UUID4,
        save_to_db: bool = Query(True, description="Save weather data to database"),
        session: AsyncSession = Depends(get_async_session),
        service: OpenMeteoService = Depends(get_weather_service)
):
    """
    Fetch current weather data for all weather points.
    """
    try:
        mesh_svc = MeshedAreaService(session)
        rpoint_svc = RoutePointService(session)
        wf_svc = WeatherForecastService(session)

        meshed = await mesh_svc.get_entity_by_id(meshed_area_id, allow_none=False)

        if not meshed:
            raise HTTPException(404, f"MeshedArea {meshed_area_id} not found")

        weather_points_data = {}
        if meshed.weather_points_json:
            weather_points_data = json.loads(meshed.weather_points_json)

        if not weather_points_data:
            weather_points = await _extract_weather_points(meshed)
        else:
            weather_points = [(p['x'], p['y']) for p in weather_points_data.get('points', [])]

        if not weather_points:
            raise HTTPException(400, "No weather points found for this mesh")

        epsg = int(meshed.crs_epsg or 4326)
        if epsg != 4326:
            transformer = Transformer.from_crs(epsg, 4326, always_xy=True)
            weather_points_wgs84 = [
                transformer.transform(x, y) for x, y in weather_points
            ]
        else:
            weather_points_wgs84 = weather_points

        existing_weather_points = await rpoint_svc.get_all_entities(
            filters={
                'meshed_area_id': meshed_area_id,
                'point_type': RoutePointType.WEATHER
            },
            page=1,
            limit=1000
        )

        weather_point_ids = []
        if not existing_weather_points or len(existing_weather_points) == 0:
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

        initial_stats = service.get_stats()

        weather_data = await service.fetch_batch(
            [(lat, lon) for lon, lat in weather_points_wgs84],
            priorities=None
        )

        final_stats = service.get_stats()

        response_points = []
        successful = 0
        failed = 0
        current_time = datetime.utcnow()

        for idx, data in weather_data.items():
            lon, lat = weather_points_wgs84[idx]

            is_default = data.get('is_default', False)
            if is_default:
                failed += 1
            else:
                successful += 1

            if save_to_db and idx < len(weather_point_ids):
                weather_forecast = await wf_svc.create_entity(
                    model_data=WeatherForecastCreate(
                        route_point_id=weather_point_ids[idx],
                        forecast_timestamp=current_time,
                        temperature=data.get('temperature'),
                        humidity=data.get('humidity'),
                        pressure=data.get('pressure'),
                        wind_speed=data.get('wind_speed', 0.0),
                        wind_direction=data.get('wind_direction', 0.0),
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

        weather_points_metadata = {
            'points': [
                {
                    'idx': idx,
                    'x': weather_points[idx][0],
                    'y': weather_points[idx][1],
                    'lon': weather_points_wgs84[idx][0],
                    'lat': weather_points_wgs84[idx][1],
                    'route_point_id': str(weather_point_ids[idx]) if idx < len(weather_point_ids) else None
                }
                for idx in range(len(weather_points))
            ],
            'last_updated': current_time.isoformat()
        }

        meshed.weather_points_json = json.dumps(weather_points_metadata)
        await session.commit()

        return WeatherBatchResponse(
            meshed_area_id=meshed_area_id,
            total_points=len(response_points),
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
        raise HTTPException(500, f"Failed to fetch weather: {str(e)}")


@router.get("/{meshed_area_id}/weather-history",
            status_code=200,
            description="Get historical weather data from database")
async def get_weather_history(
        meshed_area_id: UUID4,
        hours: int = Query(24, description="Number of hours to look back"),
        session: AsyncSession = Depends(get_async_session)
):
    """
    Get historical weather data from WeatherForecast.
    """
    try:
        mesh_svc = MeshedAreaService(session)
        meshed = await mesh_svc.get_entity_by_id(meshed_area_id, allow_none=False)

        if not meshed:
            raise HTTPException(404, f"MeshedArea {meshed_area_id} not found")

        end_time = datetime.utcnow()
        start_time = end_time - timedelta(hours=hours)

        query = (
            select(RoutePoint, WeatherForecast)
            .join(WeatherForecast, RoutePoint.id == WeatherForecast.route_point_id)
            .where(
                and_(
                    RoutePoint.meshed_area_id == meshed_area_id,
                    RoutePoint.point_type == RoutePointType.WEATHER,
                    WeatherForecast.forecast_timestamp >= start_time,
                    WeatherForecast.forecast_timestamp <= end_time
                )
            )
            .order_by(RoutePoint.seq_idx, WeatherForecast.forecast_timestamp.desc())
        )

        result = await session.execute(query)
        rows = result.all()

        weather_history = {}
        for point, forecast in rows:
            point_key = f"{point.seq_idx}_{point.x:.4f}_{point.y:.4f}"
            if point_key not in weather_history:
                weather_history[point_key] = {
                    "point_id": str(point.id),
                    "lon": point.x,
                    "lat": point.y,
                    "seq_idx": point.seq_idx,
                    "forecasts": []
                }

            weather_history[point_key]["forecasts"].append({
                "forecast_id": str(forecast.id),
                "timestamp": forecast.forecast_timestamp.isoformat(),
                "fetched_at": forecast.fetched_timestamp.isoformat(),
                "wind_speed": forecast.wind_speed,
                "wind_direction": forecast.wind_direction,
                "wind_gusts": forecast.wind_gusts,
                "wave_height": forecast.wave_height,
                "wave_direction": forecast.wave_direction,
                "wave_period": forecast.wave_period,
                "temperature": forecast.temperature,
                "pressure": forecast.pressure,
                "source": forecast.source,
                "is_default": forecast.is_default
            })

        return {
            "meshed_area_id": str(meshed_area_id),
            "time_range": {
                "start": start_time.isoformat(),
                "end": end_time.isoformat(),
                "hours": hours
            },
            "points_count": len(weather_history),
            "total_forecasts": sum(len(p["forecasts"]) for p in weather_history.values()),
            "weather_points": list(weather_history.values())
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Failed to get weather history: {str(e)}")

async def _extract_weather_points(meshed_area) -> List[tuple[float, float]]:
    """
    Extract weather points from meshed area.
    """
    nodes = np.array(json.loads(meshed_area.nodes_json))
    step = max(1, len(nodes) // 30)
    selected_indices = list(range(0, len(nodes), step))[:30]
    weather_points = nodes[selected_indices]

    return [(float(p[0]), float(p[1])) for p in weather_points]