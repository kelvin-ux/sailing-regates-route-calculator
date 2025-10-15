from fastapi import APIRouter

from app.api.v1 import db
from app.api.v1 import example
from app.api.v1 import routes_mesh
from app.api.v1 import weather
from app.core.config import settings

router_v1 = APIRouter(prefix="/api/v1")
router_v1.include_router(example.router, tags=["example"], prefix="/example")
router_v1.include_router(routes_mesh.router, tags=["routes_mesh"], prefix="/routes_mesh")
router_v1.include_router(weather.router, tags=["weather"], prefix="/weather")
if settings.DEBUG:
    router_v1.include_router(db.router, tags=["db"], prefix="/db")
