from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional, List

from pydantic import BaseModel, Field, field_validator

from app.services.warsawtz import parse_datetime_warsaw, WARSAW_TZ, now_warsaw



class TimeWindowRequest(BaseModel):
    start_time: Optional[datetime] = Field(default_factory=now_warsaw)
    end_time: Optional[datetime] = Field(default_factory=now_warsaw)
    num_checks: int = Field(default=2,ge=1,le=10)

    @field_validator('start_time', mode='before')
    @classmethod
    def validate_start_time(cls, v):
        if v is None:
            return datetime.now(WARSAW_TZ)

        v = parse_datetime_warsaw(v)
        now = datetime.now(WARSAW_TZ)

        if v < now - timedelta(minutes=5):
            raise ValueError("start_time must be in the future or now")

        return v

    @field_validator('end_time', mode='before')
    @classmethod
    def validate_end_time(cls, v):
        if v is None:
            return None

        v = parse_datetime_warsaw(v)
        return v

    def get_time_points(self) -> List[datetime]:
        """
        Returns list of datetime points for route calculation.
        All datetimes are converted to UTC and returned as naive (no tzinfo)
        for database compatibility with TIMESTAMP WITHOUT TIME ZONE columns.
        """
        start = self.start_time or datetime.now(WARSAW_TZ)
        if start.tzinfo is None:
            start = start.replace(tzinfo=WARSAW_TZ)

        if self.end_time is None or self.num_checks == 1:
            # Convert to UTC naive for DB
            start_utc_naive = start.astimezone(timezone.utc).replace(tzinfo=None)
            return [start_utc_naive]

        end = self.end_time
        if end.tzinfo is None:
            end = end.replace(tzinfo=WARSAW_TZ)
        if end <= start:
            raise ValueError("end_time must be after start_time")

        delta = (end - start) / (self.num_checks - 1) if self.num_checks > 1 else (end - start)

        # Generate time points and convert each to UTC naive for DB compatibility
        time_points = []
        for i in range(self.num_checks):
            point = start + delta * i
            # Convert to UTC and remove tzinfo for TIMESTAMP WITHOUT TIME ZONE
            point_utc_naive = point.astimezone(timezone.utc).replace(tzinfo=None)
            time_points.append(point_utc_naive)

        return time_points