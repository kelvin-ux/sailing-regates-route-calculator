from fastapi import APIRouter

from app.core.config import settings
from app.core.database import async_engine

router = APIRouter()


@router.post("/refresh",
             status_code=200,
             description="This endpoint refreshes database.")
async def refresh_db():
    if settings.DEBUG:
        from app.models.models import Base
        async with async_engine.begin() as connection:
            await connection.run_sync(Base.metadata.drop_all)
            await connection.run_sync(Base.metadata.create_all)


@router.post("/create",
             status_code=200,
             description="This endpoint creates database schema.")
async def create_db():
    if settings.DEBUG:
        from app.models.models import Base
        async with async_engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)


@router.post("/drop",
             status_code=200,
             description="This endpoint drops database.")
async def drop_db():
    if settings.DEBUG:
        from app.models.models import Base
        async with async_engine.begin() as connection:
            await connection.run_sync(Base.metadata.drop_all)
