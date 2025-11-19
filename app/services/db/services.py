from sqlalchemy.ext.asyncio import AsyncSession
from app.models.models import Route
from app.models.models import RoutePoint
from app.models.models import WeatherForecast
from app.models.models import MeshedArea
from app.models.models import Yacht
from app.services.common import BaseService
from app.models.models import RouteSegments
from app.services.common import BaseService

class RouteService(BaseService[Route]):
    def __init__(self, session: AsyncSession): super().__init__(session, Route)

class RoutePointService(BaseService[RoutePoint]):
    def __init__(self, session: AsyncSession): super().__init__(session, RoutePoint)

class WeatherForecastService(BaseService[WeatherForecast]):
    def __init__(self, session: AsyncSession): super().__init__(session, WeatherForecast)

class MeshedAreaService(BaseService[MeshedArea]):
    def __init__(self, session: AsyncSession): super().__init__(session, MeshedArea)

class YachtService(BaseService[Yacht]):
    def __init__(self, session: AsyncSession): super().__init__(session, Yacht)

class RouteSegmentsService(BaseService[RouteSegments]):
    def __init__(self, session: AsyncSession): super().__init__(session, RouteSegments)