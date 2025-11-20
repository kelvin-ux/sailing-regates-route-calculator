from fastapi import FastAPI

from app.api.exceptions.middleware import RequestContextMiddleware
from app.api.v1.routes import router_v1
from app.core.config import settings
from app.core.database import async_session
from app.core.yacht_seeder import seed_yachts

app = FastAPI(debug=settings.DEBUG)
app.include_router(router_v1)


def add_middleware():
    app.add_middleware(RequestContextMiddleware)

@app.on_event("startup")
async def startup_event():
    async with async_session() as session:
        await seed_yachts(session)

add_middleware()
