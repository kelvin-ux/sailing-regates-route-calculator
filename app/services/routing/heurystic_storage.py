"""
Moduł do zapisywania wyników heurystyki do bazy danych.

Heuristic score jest obliczany podczas A* i zależy od:
- Pozycji bieżącej
- Pozycji celu
- Warunków pogodowych

Dlatego zapisujemy go dopiero PO obliczeniu trasy, dla punktów które są częścią optymalnej ścieżki.
"""
from __future__ import annotations

from typing import List, Dict, Tuple, Optional
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import update

from app.models.models import RoutePoint, RoutePointType


async def update_heuristic_scores(
        session: AsyncSession,
        route_id: UUID,
        path_vertices: List[Tuple[float, float]],
        heuristic_scores: Dict[int, float],
        vertex_to_routepoint: Dict[int, UUID]
) -> int:
    """
    Aktualizuje heuristic_score dla RoutePoint po obliczeniu trasy.

    Args:
        session: Sesja bazy danych
        route_id: ID trasy
        path_vertices: Lista wierzchołków w optymalnej ścieżce [(x,y), ...]
        heuristic_scores: Mapa vertex_idx -> heuristic_score z A*
        vertex_to_routepoint: Mapa vertex_idx -> RoutePoint.id

    Returns:
        Liczba zaktualizowanych rekordów
    """
    updated_count = 0

    for vertex_idx, score in heuristic_scores.items():
        if vertex_idx in vertex_to_routepoint:
            route_point_id = vertex_to_routepoint[vertex_idx]

            stmt = (
                update(RoutePoint)
                .where(RoutePoint.id == route_point_id)
                .values(heuristic_score=float(score))
            )
            await session.execute(stmt)
            updated_count += 1

    await session.commit()
    return updated_count


async def save_path_heuristics(
        session: AsyncSession,
        route_id: UUID,
        meshed_area_id: UUID,
        path_with_scores: List[Dict]
) -> int:
    """
    Zapisuje heuristic_score dla wszystkich punktów na ścieżce.

    Args:
        session: Sesja bazy danych
        route_id: ID trasy
        meshed_area_id: ID meshed area
        path_with_scores: Lista słowników z danymi punktów:
            [{"x": float, "y": float, "heuristic_score": float, "seq_idx": int}, ...]

    Returns:
        Liczba zaktualizowanych/utworzonych rekordów
    """
    from app.services.db.services import RoutePointService
    from app.schemas.db_create import RoutePointCreate

    rpoint_svc = RoutePointService(session)
    count = 0

    for point_data in path_with_scores:
        existing = await rpoint_svc.get_entity_by_field(
            route_id=route_id,
            seq_idx=point_data.get("seq_idx")
        )

        if existing:
            stmt = (
                update(RoutePoint)
                .where(RoutePoint.id == existing.id)
                .values(heuristic_score=point_data.get("heuristic_score"))
            )
            await session.execute(stmt)
        else:
            await rpoint_svc.create_entity(
                model_data=RoutePointCreate(
                    route_id=route_id,
                    meshed_area_id=meshed_area_id,
                    point_type=RoutePointType.NAVIGATION,
                    seq_idx=point_data.get("seq_idx", 9999),
                    x=point_data.get("x", 0.0),
                    y=point_data.get("y", 0.0),
                    heuristic_score=point_data.get("heuristic_score")
                )
            )
        count += 1

    await session.commit()
    return count