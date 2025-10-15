from __future__ import annotations

import json
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, UUID4
from pyproj import Transformer
from sqlalchemy.ext.asyncio import AsyncSession
import numpy as np

from app.core.database import get_db as get_async_session
from app.services.db.services import MeshedAreaService
from app.services.weather.weather_api_manager import OpenMeteoService

from app.schemas.weather import (
    WeatherBatchResponse, WeatherPointResponse,
    WeatherPointResponse, WeatherDataResponse
)

router = APIRouter()


_weather_service: Optional[OpenMeteoService] = None


def get_weather_service() -> OpenMeteoService:
    """Get or create weather service instance """
    global _weather_service
    if _weather_service is None:
        _weather_service = OpenMeteoService(
            redis_url=None, # "redis://localhost:6379"
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
        force_refresh: bool = Query(False, description="Force refresh from API, bypass cache"),
        session: AsyncSession = Depends(get_async_session),
        service: OpenMeteoService = Depends(get_weather_service)
):
    """
    Fetch current weather data for all weather points in the mesh.
    """
    try:
        mesh_svc = MeshedAreaService(session)
        meshed = await mesh_svc.get_entity_by_id(meshed_area_id, allow_none=False)

        if not meshed:
            raise HTTPException(404, f"MeshedArea {meshed_area_id} not found")

        weather_points = await _extract_weather_points(meshed)

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

        initial_stats = service.get_stats()

        weather_data = await service.fetch_batch(
            [(lat, lon) for lon, lat in weather_points_wgs84],
            priorities=None
        )

        final_stats = service.get_stats()

        response_points = []
        successful = 0
        failed = 0

        for idx, data in weather_data.items():
            lon, lat = weather_points_wgs84[idx]

            is_default = data.get('is_default', False)
            if is_default:
                failed += 1
            else:
                successful += 1

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

        # TODO  - database
        weather_json = {
            str(idx): {
                'coords': {'lat': p.lat, 'lon': p.lon},
                'wind_speed': p.wind_speed,
                'wind_direction': p.wind_direction,
                'wind_gusts': p.wind_gusts,
                'wave_height': p.wave_height,
                'wave_direction': p.wave_direction,
                'wave_period': p.wave_period,
                'wind_wave_height': p.wind_wave_height,
                'swell_wave_height': p.swell_wave_height,
                'current_velocity': p.current_velocity,
                'current_direction': p.current_direction,
                'temperature': p.temperature,
                'humidity': p.humidity,
                'pressure': p.pressure,
                'timestamp': p.timestamp
            }
            for idx, p in enumerate(response_points)
        }

        meshed.weather_data_json = json.dumps(weather_json)
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
        raise HTTPException(500, f"Failed to fetch weather: {str(e)}")


@router.get("/{meshed_area_id}/weather-data",
            response_model=WeatherDataResponse,
            status_code=200,
            description="Get stored weather data")
async def get_weather_data(
        meshed_area_id: UUID4,
        session: AsyncSession = Depends(get_async_session)
):
    """
    Get stored weather data for the mesh.

    Returns the last fetched weather data without making new API calls.
    """
    try:
        mesh_svc = MeshedAreaService(session)
        meshed = await mesh_svc.get_entity_by_id(meshed_area_id, allow_none=False)

        if not meshed:
            raise HTTPException(404, f"MeshedArea {meshed_area_id} not found")

        weather_data = {}
        if hasattr(meshed, 'weather_data_json') and meshed.weather_data_json:
            weather_data = json.loads(meshed.weather_data_json)

        return WeatherDataResponse(
            meshed_area_id=str(meshed_area_id),
            has_data=bool(weather_data),
            point_count=len(weather_data),
            data=weather_data
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Failed to get weather data: {str(e)}")


@router.get("/{meshed_area_id}/weather-geojson",
            status_code=200,
            description="Get weather data as GeoJSON for map visualization")
async def get_weather_geojson(
        meshed_area_id: UUID4,
        session: AsyncSession = Depends(get_async_session)
):
    """
    Get weather data as GeoJSON for map visualization.

    Returns weather points with all marine data as GeoJSON Feature Collection.
    """
    try:
        mesh_svc = MeshedAreaService(session)
        meshed = await mesh_svc.get_entity_by_id(meshed_area_id, allow_none=False)

        if not meshed:
            raise HTTPException(404, f"MeshedArea {meshed_area_id} not found")

        weather_data = {}
        if hasattr(meshed, 'weather_data_json') and meshed.weather_data_json:
            weather_data = json.loads(meshed.weather_data_json)

        features = []
        for idx, data in weather_data.items():
            features.append({
                "type": "Feature",
                "properties": {
                    "index": int(idx),
                    "wind_speed": data.get("wind_speed"),
                    "wind_direction": data.get("wind_direction"),
                    "wind_gusts": data.get("wind_gusts"),
                    "wave_height": data.get("wave_height"),
                    "wave_direction": data.get("wave_direction"),
                    "wave_period": data.get("wave_period"),
                    "wind_wave_height": data.get("wind_wave_height"),
                    "swell_wave_height": data.get("swell_wave_height"),
                    "current_velocity": data.get("current_velocity"),
                    "current_direction": data.get("current_direction"),
                    "temperature": data.get("temperature"),
                    "humidity": data.get("humidity"),
                    "pressure": data.get("pressure"),
                    "timestamp": data.get("timestamp")
                },
                "geometry": {
                    "type": "Point",
                    "coordinates": [
                        data["coords"]["lon"],
                        data["coords"]["lat"]
                    ]
                }
            })

        return {
            "type": "FeatureCollection",
            "features": features
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Failed to generate GeoJSON: {str(e)}")


@router.get("/service/stats",
            status_code=200,
            description="Get weather service statistics and performance metrics")
async def get_service_stats(
        service: OpenMeteoService = Depends(get_weather_service)
):
    """
    Get weather service statistics.
    """
    return service.get_stats()


async def _extract_weather_points(meshed_area) -> List[tuple[float, float]]:
    """
    Extract weather points from meshed area.
    """
    nodes = np.array(json.loads(meshed_area.nodes_json))
    step = max(1, len(nodes) // 30)
    selected_indices = list(range(0, len(nodes), step))[:30]
    weather_points = nodes[selected_indices]

    return [(float(p[0]), float(p[1])) for p in weather_points]