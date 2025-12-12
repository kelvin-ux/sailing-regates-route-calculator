from fastapi import APIRouter

from app.api.v1 import db
from app.api.v1 import example
from app.api.v1 import routes_mesh
from app.api.v1 import yacht
from app.api.v1 import weather
from app.api.v1 import routing
from app.api.v1 import view_route
from app.core.config import settings

router_v1 = APIRouter(prefix="/api/v1")
router_v1.include_router(example.router, tags=["example"], prefix="/example")
router_v1.include_router(routes_mesh.router, tags=["routes_mesh"], prefix="/routes_mesh")
router_v1.include_router(weather.router, tags=["weather"], prefix="/weather")
router_v1.include_router(yacht.router, tags=["yacht"], prefix="/yacht")
router_v1.include_router(view_route.router, tags=["visualise"], prefix="/visualise")

router_v1.include_router(routing.router, tags=["routing"], prefix="/routing")

if settings.DEBUG:
    router_v1.include_router(db.router, tags=["db"], prefix="/db")
