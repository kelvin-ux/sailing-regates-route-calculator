from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any

from pydantic import UUID4
from sqlalchemy import select, delete, update
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi import APIRouter, Depends, HTTPException, Query, Body

import numpy as np
from pyproj import Transformer


from app.core.database import get_db as get_async_session
from app.models.models import (
    MeshedArea, Route, RoutePoint, RoutePointType, 
    RouteVariant, Yacht
)
from app.services.db.services import (
    MeshedAreaService, RouteService, YachtService, 
    RoutePointService, RouteVariantService
)
from app.schemas.time_aware_weather import ETACalculationConfig
from app.services.routing.iterative_routing import (
    IterativeRouteCalculator,
    IterativeRoutingContext,
    create_routing_context,
)
from app.services.weather.time_aware_weather_service import TimeAwareWeatherService
from app.services.routing.time_window import TimeWindowRequest
from app.services.routing.diff_calc import RouteDifficultyCalculator

router = APIRouter()

_time_aware_weather_service: Optional[TimeAwareWeatherService] = None


def get_time_aware_weather_service() -> TimeAwareWeatherService:
    global _time_aware_weather_service
    if _time_aware_weather_service is None:
        _time_aware_weather_service = TimeAwareWeatherService()
    return _time_aware_weather_service


@router.post("/{meshed_area_id}/calculate-route", status_code=200)
async def calculate_optimal_route(
    meshed_area_id: UUID4,
    min_depth: float = Query(3.0, description="Minimum water depth in meters"),
    max_iterations: int = Query(3, ge=1, le=5, description="Maximum routing iterations"),
    convergence_threshold: float = Query(300.0, ge=60, le=1800, 
                                          description="Convergence threshold in seconds"),
    time_window: Optional[TimeWindowRequest] = Body(
        default=None,
        description="Optional time window for multiple route calculations"
    ),
    session: AsyncSession = Depends(get_async_session)
):
    try:
        mesh_svc = MeshedAreaService(session)
        meshed = await mesh_svc.get_entity_by_id(meshed_area_id, allow_none=False)
        
        if not meshed:
            raise HTTPException(404, f"Mesh {meshed_area_id} not found")
        
        weather_points_data = json.loads(meshed.weather_points_json) if meshed.weather_points_json else None
        if not weather_points_data or not weather_points_data.get('points'):
            raise HTTPException(400, "No weather points defined. Run mesh creation first.")
        
        route_svc = RouteService(session)
        yacht_svc = YachtService(session)
        
        route = await route_svc.get_entity_by_id(meshed.route_id, allow_none=False)
        yacht = await yacht_svc.get_entity_by_id(route.yacht_id, allow_none=False)
        
        query_points = (
            select(RoutePoint)
            .where(RoutePoint.route_id == meshed.route_id)
            .where(RoutePoint.point_type.in_([
                RoutePointType.START, RoutePointType.CONTROL, RoutePointType.STOP
            ]))
            .order_by(RoutePoint.seq_idx)
        )
        result_points = await session.execute(query_points)
        route_points = list(result_points.scalars().all())
        
        if len(route_points) < 2:
            raise HTTPException(400, "Not enough route points (need at least 2)")
        
        if time_window is None:
            time_points = [datetime.datetime.now()]
        else:
            time_points = time_window.get_time_points()
        
        await session.execute(
            delete(RouteVariant).where(RouteVariant.meshed_area_id == meshed_area_id)
        )
        await session.commit()
        
        estimated_cruise_speed = yacht.max_speed * 0.8 if yacht.max_speed else 6.0
        
        config = ETACalculationConfig(
            max_iterations=max_iterations,
            convergence_threshold_seconds=convergence_threshold,
            initial_speed_knots=estimated_cruise_speed,
            time_round_minutes=5
        )
        
        weather_service = get_time_aware_weather_service()
        calculator = IterativeRouteCalculator(
            weather_service=weather_service,
            config=config,
        )
        
        print(f"[ROUTE] Yacht: {yacht.name} (max_speed: {yacht.max_speed}kt, "
              f"initial estimate: {estimated_cruise_speed:.1f}kt)")
        
        variants_results = []
        
        for idx, departure_time in enumerate(time_points):
            print(f"\n[ROUTE] === Variant {idx + 1}/{len(time_points)}: departure at {departure_time} ===")
            
            ctx = await create_routing_context(
                session=session,
                meshed=meshed,
                yacht=yacht,
                departure_time=departure_time,
                route_points=route_points,
                config=config,
            )
            
            result = await calculator.calculate_route(ctx, session)
            
            if result and result.profile.segments:
                route_data = calculator.get_final_route_data(result, ctx)
                route_data['variant_order'] = idx
                variants_results.append(route_data)
                
                print(f"[ROUTE] Route calculated: {route_data['total_time_hours']:.2f}h, "
                      f"{route_data['total_distance_nm']:.1f}nm, "
                      f"converged={result.converged}, "
                      f"iterations={len(result.iterations)}")
            else:
                print(f"[ROUTE] Failed to calculate route for departure {departure_time}")
        
        if not variants_results:
            raise HTTPException(400, "No navigable routes found for any time point.")
        
        difficulty_calculator = RouteDifficultyCalculator()
        difficulty_result = difficulty_calculator.calculate_for_variants(variants_results)
        overall_difficulty = round(difficulty_result["overall_score"])
        
        stmt_route = (
            update(Route)
            .where(Route.id == meshed.route_id)
            .values(difficulty_level=overall_difficulty)
        )
        await session.execute(stmt_route)
        
        best_variant_idx = min(
            range(len(variants_results)), 
            key=lambda i: variants_results[i]['total_time_hours']
        )
        
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
                "estimated_arrival": variant_data.get('estimated_arrival'),
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
                "difficulty_level": variant_difficulty.get_level().value,
                "waypoints_wgs84": variant_data['waypoints_wgs84'],
                "segments": variant_data['segments'],
                "converged": variant_data.get('converged', False),
                "iterations": variant_data.get('iterations', []),
                "weather_stats": variant_data.get('weather_stats', {}),
            })
        
        best_variant_data = variants_results[best_variant_idx]
        route_save_data = {
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
                "average_speed_knots": best_variant_data['average_speed_knots'],
                "estimated_arrival": best_variant_data.get('estimated_arrival'),
            },
            "time_window": {
                "enabled": time_window is not None,
                "num_variants": len(variants_results)
            },
            "calculation_method": "time_aware_iterative",
        }
        
        stmt = (
            update(MeshedArea)
            .where(MeshedArea.id == meshed_area_id)
            .values(
                calculated_route_json=json.dumps(route_save_data),
                calculated_route_timestamp=datetime.utcnow()
            )
        )
        await session.execute(stmt)
        await session.commit()
        
        return {
            "meshed_area_id": str(meshed_area_id),
            "calculation_method": "time_aware_iterative",
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
            "config": {
                "max_iterations": max_iterations,
                "convergence_threshold_seconds": convergence_threshold,
            },
            "variants_count": len(saved_variants),
            "variants": saved_variants,
            "best_variant": saved_variants[best_variant_idx] if saved_variants else None,
            "difficulty": {
                "overall_score": difficulty_result["overall_score"],
                "level": difficulty_result["overall"].get_level().value,
                "best_variant_score": round(
                    difficulty_result["best_variant"].calculate_total(), 2
                ),
                "worst_variant_score": round(
                    difficulty_result["worst_variant"].calculate_total(), 2
                ),
            },
            "weather_stats": {
                "total_requests": sum(
                    v.get('weather_stats', {}).get('total_requests', 0) 
                    for v in variants_results
                ),
                "cache_hits": sum(
                    v.get('weather_stats', {}).get('cache_hits', 0) 
                    for v in variants_results
                ),
                "api_calls": sum(
                    v.get('weather_stats', {}).get('api_calls', 0) 
                    for v in variants_results
                ),
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(500, f"Failed to calculate route: {str(e)}")



async def calculate_route_time_aware(
    session: AsyncSession,
    meshed: MeshedArea,
    yacht: Yacht,
    weather_points: List[Dict],
    weather_points_wgs84: List[tuple],
    route_points: List[RoutePoint],
    departure_time: datetime,
    config: Optional[ETACalculationConfig] = None,
) -> Optional[Dict[str, Any]]:
    config = config or ETACalculationConfig()
    vertices = np.array(json.loads(meshed.nodes_json))
    triangles = np.array(json.loads(meshed.triangles_json))
    
    transformer_to_wgs84 = Transformer.from_crs(meshed.crs_epsg, 4326, always_xy=True)
    transformer_from_wgs84 = Transformer.from_crs(4326, meshed.crs_epsg, always_xy=True)
    
    ctx = IterativeRoutingContext(
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
        config=config,
    )
    
    weather_service = get_time_aware_weather_service()
    calculator = IterativeRouteCalculator(
        weather_service=weather_service,
        config=config,
    )
    
    result = await calculator.calculate_route(ctx, session)
    
    if result and result.profile.segments:
        return calculator.get_final_route_data(result, ctx)
    
    return None