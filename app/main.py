from fastapi import FastAPI

from app.api.exceptions.middleware import RequestContextMiddleware
from app.api.v1.routes import router_v1
from app.core.config import settings

app = FastAPI(debug=settings.DEBUG)
app.include_router(router_v1)


def add_middleware():
    app.add_middleware(RequestContextMiddleware)


add_middleware()
