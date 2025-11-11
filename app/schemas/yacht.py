from __future__ import annotations

from typing import Optional
from typing import Dict
from typing import Any
from pydantic import BaseModel
from pydantic import Field
from pydantic import UUID4
from datetime import datetime

from app.models.models import YachtType


class YachtCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    yacht_type: YachtType
    length: float = Field(..., gt=0, description="Length in feet")
    beam: float = Field(..., gt=0, description="Beam in feet")
    draft: Optional[float] = Field(None, gt=0, description="Draft in feet")
    sail_number: Optional[int] = Field(default=2, le=30, description="Number of sails")
    has_spinnaker: bool = False
    has_genaker: bool = False
    max_speed: Optional[float] = Field(None, gt=0, description="Maximum speed in knots")
    max_wind_speed: Optional[float] = Field(None, gt=0, description="Maximum safe wind speed in m/s")
    amount_of_crew: Optional[int] = Field(None, ge=1)
    tack_time: Optional[float] = Field(None, ge=0, description="Time in minutes for tack")
    jibe_time: Optional[float] = Field(None, ge=0, description="Time in minutes for jibe")
    polar_data: Optional[Dict[str, Any]] = Field(None,description="Polar chart data for performance calculations")


class YachtUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    yacht_type: Optional[YachtType] = None
    length: Optional[float] = Field(None, gt=0)
    beam: Optional[float] = Field(None, gt=0)
    draft: Optional[float] = Field(None, gt=0)
    sail_number: Optional[int] = Field(None, le=30)
    has_spinnaker: Optional[bool] = None
    has_genaker: Optional[bool] = None
    max_speed: Optional[float] = Field(None, gt=0)
    max_wind_speed: Optional[float] = Field(None, gt=0)
    amount_of_crew: Optional[int] = Field(None, ge=1)
    tack_time: Optional[float] = Field(None, ge=0)
    jibe_time: Optional[float] = Field(None, ge=0)
    polar_data: Optional[Dict[str, Any]] = None


class YachtResponse(BaseModel):
    id: UUID4
    name: str
    yacht_type: YachtType
    length: float
    beam: float
    draft: Optional[float]
    sail_number: Optional[int]
    has_spinnaker: bool
    has_genaker: bool
    max_speed: Optional[float]
    max_wind_speed: Optional[float]
    amount_of_crew: Optional[int]
    polar_data: Optional[Dict[str, Any]]
    tack_time: Optional[float]
    jibe_time: Optional[float]
    created_at: datetime
    updated_at: datetime

    class Config:
        orm_mode = True

    @classmethod
    def from_orm(cls, obj):
        return cls(
            id=obj.id,
            name=obj.name,
            yacht_type=obj.yacht_type,
            length=obj.length,
            beam=obj.beam,
            draft=obj.draft,
            sail_number=obj.sail_number,
            has_spinnaker=obj.has_spinnaker,
            has_genaker=obj.has_genaker,
            max_speed=obj.max_speed,
            max_wind_speed=obj.max_wind_speed,
            amount_of_crew=obj.amount_of_crew,
            tack_time=obj.tack_time,
            jibe_time=obj.jibe_time,
            polar_data=obj.polar_data,
            created_at=obj.created_at,
            updated_at=obj.updated_at
        )