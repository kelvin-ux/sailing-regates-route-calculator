import enum
import json
from datetime import date
from datetime import datetime
from typing import List
from typing import Optional
from uuid import UUID
from uuid import uuid4

from sqlalchemy import Column
from sqlalchemy import Date
from sqlalchemy import DateTime
from sqlalchemy import Enum
from sqlalchemy import Float
from sqlalchemy import ForeignKey
from sqlalchemy import func
from sqlalchemy import Integer
from sqlalchemy import MetaData
from sqlalchemy import String
from sqlalchemy import Table
from sqlalchemy import Boolean
from sqlalchemy import JSON
from sqlalchemy import Index
from sqlalchemy import Text
from sqlalchemy import UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncAttrs
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.orm import Mapped
from sqlalchemy.orm import mapped_column
from sqlalchemy.orm import relationship


class Base(AsyncAttrs, DeclarativeBase):
    __abstract__ = True
    created_at: Mapped[DateTime] = mapped_column(DateTime, default=func.now())
    updated_at: Mapped[DateTime] = mapped_column(DateTime, default=func.now(), onupdate=func.now())
    metadata = MetaData(
        naming_convention={
            "ix": "ix_%(column_0_label)s",
            "uq": "uq_%(table_name)s_%(column_0_name)s",
            "ck": "ck_%(table_name)s_%(column_0_name)s",
            "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
            "pk": "pk_%(table_name)s",
        }
    )

class YachtType(enum.StrEnum):
    SAILBOAT = "Sailboat"
    TALL_SHIP = "Tall ship"
    CLASS_40 = "Class 40"
    OMEGA = "Omega"
    CATAMARAN = "catamaran"
    TRIMARAN = "trimaran"
    OPEN_60 = "open_60"


class ObstacleType(enum.StrEnum):
    NATURAL = "Natural"
    NAVIGATIONAL_MARK = "Navigational_mark"
    OTHER = "Other"


class ControlPointType(enum.StrEnum):
    BUOY = "Buoy"
    GATE = "gate"
    NATURAL = "natural"



route_obstacles_association = Table(
    "route_obstacles",
    Base.metadata,
    Column("route_id", ForeignKey("route.id"), primary_key=True, index=True),
    Column("obstacle_id", ForeignKey("obstacle.id"), primary_key=True, index=True),
    Column("impact_level", Float, nullable=True, comment="How much the obstacle affects the route (0.0-1.0)")
)

class Yacht(Base):
    __tablename__ = "yacht"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), default=uuid4, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    yacht_type: Mapped[YachtType] = mapped_column(Enum(YachtType), nullable=False)
    length: Mapped[float] = mapped_column(Float, nullable=False, comment="Length in meters")
    beam: Mapped[float] = mapped_column(Float, nullable=False, comment="Beam in meters")
    sail_number: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    has_spinnaker: Mapped[bool] = mapped_column(Boolean, default=False)
    has_genaker: Mapped[bool] = mapped_column(Boolean, default=False)
    polar_data: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True, comment="Polar chart data (speed vs wind angle)")
    max_speed: Mapped[Optional[float]] = mapped_column(Float, nullable=True, comment="Maximum speed in knots")
    max_wind_speed: Mapped[Optional[float]] = mapped_column(Float, nullable=True, comment="Maximum safe wind speed")
    draft: Mapped[Optional[float]] = mapped_column(Float, nullable=True, comment="Draft in meters")
    amount_of_crew: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, comment="Crew size")

    
    routes: Mapped[List["Route"]] = relationship("Route", back_populates="yacht")


class Obstacle(Base):
    __tablename__ = "obstacle"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), default=uuid4, primary_key=True)
    type: Mapped[ObstacleType] = mapped_column(Enum(ObstacleType), nullable=False)
    desc: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    directions: Mapped[Optional[str]] = mapped_column(Text, nullable=True, comment="Navigation directions")
    is_permanent: Mapped[bool] = mapped_column(Boolean, default=True)
    valid_from: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    valid_to: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    
    routes: Mapped[List["Route"]] = relationship(
        "Route", 
        secondary=route_obstacles_association, 
        back_populates="obstacles"
    )

class WeatherVector(Base):
    __tablename__ = "weather_vector"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), default=uuid4, primary_key=True)
    dir: Mapped[float] = mapped_column(Float, nullable=False, comment="Direction in degrees")
    speed: Mapped[float] = mapped_column(Float, nullable=False, comment="Speed in knots/m/s")

    
    route_points: Mapped[List["RoutePoint"]] = relationship("RoutePoint", back_populates="weather_vector")

class Route(Base):
    __tablename__ = "route"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), default=uuid4, primary_key=True)
    user_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, comment="User who created the route")
    yacht_id: Mapped[UUID] = mapped_column(ForeignKey("yacht.id"), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    control_points: Mapped[Optional[str]] = mapped_column(Text, nullable=True, comment="JSON string of control points")
    estimated_duration: Mapped[Optional[float]] = mapped_column(Float, nullable=True, comment="Estimated duration in hours")
    actual_duration: Mapped[Optional[float]] = mapped_column(Float, nullable=True, comment="Actual duration in hours")
    difficulty_level: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, comment="Difficulty level 1-10")

    
    yacht: Mapped["Yacht"] = relationship("Yacht", back_populates="routes")
    route_points: Mapped[List["RoutePoint"]] = relationship("RoutePoint", back_populates="route")
    control_points_rel: Mapped[List["ControlPoint"]] = relationship("ControlPoint", back_populates="route")
    route_segments: Mapped[List["RouteSegments"]] = relationship("RouteSegments", back_populates="route")
    obstacles: Mapped[List["Obstacle"]] = relationship(
        "Obstacle", 
        secondary=route_obstacles_association, 
        back_populates="routes"
    )

class RoutePoint(Base):
    __tablename__ = "route_point"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), default=uuid4, primary_key=True)
    route_id: Mapped[UUID] = mapped_column(ForeignKey("route.id"), nullable=False)
    seq_idx: Mapped[int] = mapped_column(Integer, nullable=False, comment="Sequence index in route")
    x: Mapped[float] = mapped_column(Float, nullable=False, comment="Longitude")
    y: Mapped[float] = mapped_column(Float, nullable=False, comment="Latitude")
    timestamp: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    heuristic_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True, comment="A* heuristic score")
    weather_vector_id: Mapped[UUID] = mapped_column(ForeignKey("weather_vector.id"), nullable=False)

    
    route: Mapped["Route"] = relationship("Route", back_populates="route_points")
    weather_vector: Mapped["WeatherVector"] = relationship("WeatherVector", back_populates="route_points")
    weather_forecasts: Mapped[List["WeatherForecast"]] = relationship("WeatherForecast", back_populates="route_point")
    segments_from: Mapped[List["RouteSegments"]] = relationship(
        "RouteSegments", 
        foreign_keys="RouteSegments.from_point",
        back_populates="from_point_rel"
    )
    segments_to: Mapped[List["RouteSegments"]] = relationship(
        "RouteSegments", 
        foreign_keys="RouteSegments.to_point",
        back_populates="to_point_rel"
    )

class WeatherForecast(Base):
    __tablename__ = "weather_forecast"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), default=uuid4, primary_key=True)
    route_point_id: Mapped[UUID] = mapped_column(ForeignKey("route_point.id"), nullable=False)
    forecast_timestamp: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    fetched_timestamp: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    temperature: Mapped[Optional[float]] = mapped_column(Float, nullable=True, comment="Temperature in Celsius")
    wind_speed: Mapped[float] = mapped_column(Float, nullable=False, comment="Wind speed in knots")
    wind_direction: Mapped[float] = mapped_column(Float, nullable=False, comment="Wind direction in degrees")
    humidity: Mapped[Optional[float]] = mapped_column(Float, nullable=True, comment="Humidity percentage")
    desc: Mapped[Optional[str]] = mapped_column(String(200), nullable=True, comment="Weather description")
    weather_vector_id: Mapped[UUID] = mapped_column(ForeignKey("weather_vector.id"), nullable=False)

    
    route_point: Mapped["RoutePoint"] = relationship("RoutePoint", back_populates="weather_forecasts")

class ControlPoint(Base):
    __tablename__ = "control_point"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), default=uuid4, primary_key=True)
    route_id: Mapped[UUID] = mapped_column(ForeignKey("route.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    x: Mapped[float] = mapped_column(Float, nullable=False, comment="Longitude of first object")
    y: Mapped[float] = mapped_column(Float, nullable=False, comment="Latitude of first object")
    x2: Mapped[float] = mapped_column(Float, nullable=True, default=None, comment="Longitude of second object")
    y2: Mapped[float] = mapped_column(Float, nullable=True, default=None, comment="Latitude of second object")
    width: Mapped[Optional[float]] = mapped_column(Float, nullable=True, comment="Width of control point in meters")
    type: Mapped[ControlPointType] = mapped_column(Enum(ControlPointType), nullable=False)
    desc: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    
    route: Mapped["Route"] = relationship("Route", back_populates="control_points_rel")

class RouteSegments(Base):
    __tablename__ = "route_segments"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), default=uuid4, primary_key=True)
    route_id: Mapped[UUID] = mapped_column(ForeignKey("route.id"), nullable=False)
    from_point: Mapped[UUID] = mapped_column(ForeignKey("route_point.id"), nullable=False)
    to_point: Mapped[UUID] = mapped_column(ForeignKey("route_point.id"), nullable=False)
    segment_order: Mapped[int] = mapped_column(Integer, nullable=False, comment="Order of segment in route")
    recommended_course: Mapped[Optional[float]] = mapped_column(Float, nullable=True, comment="Recommended course in degrees")
    estimated_time: Mapped[Optional[float]] = mapped_column(Float, nullable=True, comment="Estimated time in minutes")
    sail_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, comment="Recommended sail type")
    tack_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, comment="Type of tack (bajdewind, baksztag, etc.)")
    maneuver_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, comment="Maneuver at end of segment")
    distance_nm: Mapped[Optional[float]] = mapped_column(Float, nullable=True, comment="Distance in nautical miles")
    bearing: Mapped[Optional[float]] = mapped_column(Float, nullable=True, comment="Magnetic bearing")
    wind_angle: Mapped[Optional[float]] = mapped_column(Float, nullable=True, comment="Wind angle relative to course")
    current_effect: Mapped[Optional[float]] = mapped_column(Float, nullable=True, comment="Current effect on segment")

    route: Mapped["Route"] = relationship("Route", back_populates="route_segments")
    from_point_rel: Mapped["RoutePoint"] = relationship(
        "RoutePoint", 
        foreign_keys=[from_point],
        back_populates="segments_from"
    )
    to_point_rel: Mapped["RoutePoint"] = relationship(
        "RoutePoint", 
        foreign_keys=[to_point],
        back_populates="segments_to"
    )

from sqlalchemy import DateTime, ForeignKey, Integer, Text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from uuid import uuid4, UUID
from datetime import datetime

class MeshedArea(Base):
    __tablename__ = "meshed_area"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    route_id: Mapped[UUID] = mapped_column(ForeignKey("route.id"), nullable=False)
    crs_epsg: Mapped[int] = mapped_column(Integer, nullable=False)

    nodes_json: Mapped[str] = mapped_column(Text, nullable=False, comment="[[x,y],...] w lokalnym CRS (metry)")
    triangles_json: Mapped[str] = mapped_column(Text, nullable=False, comment="[[i,j,k],...] indeksy węzłów")

    water_wkt: Mapped[str] = mapped_column(Text, nullable=False)
    route_wkt: Mapped[str] = mapped_column(Text, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    route: Mapped["Route"] = relationship("Route", backref="meshed_areas")


Index('idx_route_yacht_id', Route.yacht_id)
Index('idx_route_point_route_id', RoutePoint.route_id)
Index('idx_route_point_seq_idx', RoutePoint.seq_idx)
Index('idx_weather_forecast_route_point_id', WeatherForecast.route_point_id)
Index('idx_weather_forecast_timestamp', WeatherForecast.forecast_timestamp)
Index('idx_route_segments_route_id', RouteSegments.route_id)
Index('idx_route_segments_order', RouteSegments.segment_order)
Index('idx_control_point_route_id', ControlPoint.route_id)

Index('idx_route_point_route_seq', RoutePoint.route_id, RoutePoint.seq_idx)
Index('idx_weather_forecast_point_time', WeatherForecast.route_point_id, WeatherForecast.forecast_timestamp)