from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm import declarative_base

from app.core.config import settings

DATABASE_URL = settings.SQLALCHEMY_DATABASE_URI
async_engine = create_async_engine(DATABASE_URL, echo=settings.DEBUG)
async_session = async_sessionmaker(async_engine, expire_on_commit=False)
Base = declarative_base()


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency to get a database session."""
    async with async_session() as session:
        yield session
