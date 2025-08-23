from sqlalchemy.ext.asyncio import AsyncSession
from app.models.models import Route, RoutePoint, WeatherVector, MeshedArea
from app.services.common import BaseService

class RouteService(BaseService[Route]):
    def __init__(self, session: AsyncSession): super().__init__(session, Route)

class RoutePointService(BaseService[RoutePoint]):
    def __init__(self, session: AsyncSession): super().__init__(session, RoutePoint)

class WeatherVectorService(BaseService[WeatherVector]):
    def __init__(self, session: AsyncSession): super().__init__(session, WeatherVector)

class MeshedAreaService(BaseService[MeshedArea]):
    def __init__(self, session: AsyncSession): super().__init__(session, MeshedArea)
