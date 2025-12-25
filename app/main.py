from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.exceptions.middleware import RequestContextMiddleware
from app.api.v1.routes import router_v1
from app.core.config import settings
from app.core.database import async_session, async_engine
from app.models.models import Base
from app.core.yacht_seeder import seed_yachts

app = FastAPI(debug=settings.DEBUG)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router_v1)


def add_middleware():
    app.add_middleware(RequestContextMiddleware)


@app.on_event("startup")
async def startup_event():
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with async_session() as session:
        await seed_yachts(session)


add_middleware()