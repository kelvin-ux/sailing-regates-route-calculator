from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

from app.services.common import request_context


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_context.set(request)
        return await call_next(request)
