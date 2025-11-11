from __future__ import annotations

from typing import List
from typing import Optional
from pydantic import UUID4

from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from fastapi import Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db as get_async_session
from app.schemas.yacht import YachtCreate
from app.schemas.yacht import YachtUpdate # TODO
from app.schemas.yacht import YachtResponse
from app.services.db.services import YachtService

router = APIRouter()


@router.post("/", response_model=YachtResponse, status_code=201)
async def create_yacht(
        payload: YachtCreate,
        session: AsyncSession = Depends(get_async_session)
):
    """
    Przykładowe dane:
    ```json
    {
      "name": "zebra",
      "yacht_type": "Sailboat",
      "length": 46,
      "beam": 14,
      "draft": 7,
      "sail_number": 2,
      "has_spinnaker": false,
      "has_genaker": false,
      "max_speed": 9,
      "max_wind_speed": 45,
      "amount_of_crew": 4,
      "tack_time": 1.5,
      "jibe_time": 3,
      "polar_data": {
        "additionalProp1": {}
      }
    }
    ```
    """
    yacht_svc = YachtService(session)

    try:
        yacht = await yacht_svc.create_entity(model_data=payload)
        return YachtResponse.from_orm(yacht)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Failed to create yacht: {str(e)}")


@router.get("/{yacht_id}", response_model=YachtResponse)
async def get_yacht(
        yacht_id: UUID4,
        session: AsyncSession = Depends(get_async_session)
):
    yacht_svc = YachtService(session)

    yacht = await yacht_svc.get_entity_by_id(yacht_id, allow_none=False)
    if not yacht:
        raise HTTPException(404, f"Yacht {yacht_id} not found")

    return YachtResponse.from_orm(yacht)


@router.get("/", response_model=List[YachtResponse])
async def list_yachts(
        page: int = Query(1, ge=1),
        limit: int = Query(10, ge=1, le=100),
        session: AsyncSession = Depends(get_async_session)
):
    yacht_svc = YachtService(session)
    yachts = await yacht_svc.get_all_entities(page=page, limit=limit)
    return [YachtResponse.from_orm(yacht) for yacht in yachts]


@router.delete("/{yacht_id}", status_code=204)
async def delete_yacht(
        yacht_id: UUID4,
        session: AsyncSession = Depends(get_async_session)
):
    yacht_svc = YachtService(session)

    yacht = await yacht_svc.get_entity_by_id(yacht_id, allow_none=False)
    if not yacht:
        raise HTTPException(404, f"Yacht {yacht_id} not found")

    await session.delete(yacht)
    await session.commit()
    return None