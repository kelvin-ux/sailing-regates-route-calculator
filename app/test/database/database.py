import unittest
import pytest
from datetime import datetime, timedelta
from uuid import uuid4
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.models import (
    Base, Yacht, Route, RoutePoint, WeatherVector, WeatherForecast,
    ControlPoint, Obstacle, RouteSegments, YachtType, ObstacleType, 
    ControlPointType, route_obstacles_association
)



class DatabaseTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls) -> None:
        cls.engine = create_engine('sqlite:///:memory:')
        __Session = sessionmaker(bind=cls.engine)
        cls.Session = __Session()

    def setUp(self):
        Base.metadata.create_all(self.engine)

    def tearDown(self):
        if self.Session.is_active:
            self.Session.rollback()
        Base.metadata.drop_all(self.engine)


class TestYacht(DatabaseTest):
    
    def test_create_yacht(self):
        yacht = self.create_yacht_instance()
        self.Session.add(yacht)
        self.Session.commit()

        self.assertIsNotNone(yacht.id)
        
        yacht_db = self.Session.query(Yacht).filter_by(name="Test Yacht").first()
        self.assertIsNotNone(yacht_db)
        self.assertEqual(yacht_db.id, yacht.id)
        self.assertEqual(yacht_db.yacht_type, YachtType.SAILBOAT)

    def test_delete_yacht(self):
        yacht = self.create_yacht_instance()
        self.Session.add(yacht)
        self.Session.commit()
        
        self.Session.delete(yacht)
        self.Session.commit()

        yacht_db = self.Session.query(Yacht).filter_by(name="Test Yacht").first()
        self.assertIsNone(yacht_db)

    def test_yacht_polar_data(self):
        yacht = self.create_yacht_instance()
        yacht.polar_data = {"0": 0, "45": 5.2, "90": 6.8, "135": 7.1, "180": 6.5}
        self.Session.add(yacht)
        self.Session.commit()

        yacht_db = self.Session.query(Yacht).filter_by(name="Test Yacht").first()
        self.assertIsInstance(yacht_db.polar_data, dict)
        self.assertEqual(yacht_db.polar_data["90"], 6.8)

    def create_yacht_instance(self) -> Yacht:
        yacht = Yacht(
            name="Test Yacht",
            yacht_type=YachtType.SAILBOAT,
            length=12.5,
            beam=3.8,
            sail_number="POL123",
            has_spinnaker=True,
            has_genaker=False,
            max_speed=8.5,
            max_wind_speed=25.0,
            draft=2.1,
            amount_of_crew=4
        )
        return yacht


class TestRoute(DatabaseTest):

    def test_create_route(self):
        yacht = self.create_yacht_instance()
        self.Session.add(yacht)
        self.Session.commit()

        route = self.create_route_instance(yacht.id)
        self.Session.add(route)
        self.Session.commit()

        self.assertIsNotNone(route.id)
        
        route_db = self.Session.query(Route).filter_by(description="Test Route").first()
        self.assertIsNotNone(route_db)
        self.assertEqual(route_db.yacht_id, yacht.id)

    def test_route_yacht_relationship_n_to_1(self):
        yacht = self.create_yacht_instance()
        self.Session.add(yacht)
        self.Session.commit()

        route1 = self.create_route_instance(yacht.id, description="Route 1")
        route2 = self.create_route_instance(yacht.id, description="Route 2")
        
        self.Session.add_all([route1, route2])
        self.Session.commit()

        yacht_db = self.Session.query(Yacht).filter_by(name="Test Yacht").first()
        self.assertEqual(len(yacht_db.routes), 2)
        
        route_descriptions = [route.description for route in yacht_db.routes]
        self.assertIn("Route 1", route_descriptions)
        self.assertIn("Route 2", route_descriptions)

    def test_route_obstacles_many_to_many(self):
        yacht = self.create_yacht_instance()
        obstacle1 = self.create_obstacle_instance("Shallow Water")
        obstacle2 = self.create_obstacle_instance("Navigation Mark")
        
        self.Session.add_all([yacht, obstacle1, obstacle2])
        self.Session.commit()

        route = self.create_route_instance(yacht.id)
        route.obstacles.append(obstacle1)
        route.obstacles.append(obstacle2)
        
        self.Session.add(route)
        self.Session.commit()

        route_db = self.Session.query(Route).filter_by(description="Test Route").first()
        self.assertEqual(len(route_db.obstacles), 2)
        
        obstacle_descriptions = [obs.desc for obs in route_db.obstacles]
        self.assertIn("Shallow Water", obstacle_descriptions)
        self.assertIn("Navigation Mark", obstacle_descriptions)

    def create_yacht_instance(self) -> Yacht:
        return Yacht(
            name="Test Yacht",
            yacht_type=YachtType.SAILBOAT,
            length=12.5,
            beam=3.8
        )

    def create_route_instance(self, yacht_id, description="Test Route") -> Route:
        return Route(
            user_id=uuid4(),
            yacht_id=yacht_id,
            description=description,
            estimated_duration=2.5,
            difficulty_level=3
        )

    def create_obstacle_instance(self, description="Test Obstacle") -> Obstacle:
        return Obstacle(
            type=ObstacleType.NATURAL,
            desc=description,
            is_permanent=True
        )


class TestRoutePoint(DatabaseTest):

    def test_create_route_point(self):
        yacht = self.create_yacht_instance()
        weather_vector = self.create_weather_vector_instance()
        self.Session.add_all([yacht, weather_vector])
        self.Session.commit()

        route = self.create_route_instance(yacht.id)
        self.Session.add(route)
        self.Session.commit()

        route_point = self.create_route_point_instance(route.id, weather_vector.id)
        self.Session.add(route_point)
        self.Session.commit()

        self.assertIsNotNone(route_point.id)
        
        point_db = self.Session.query(RoutePoint).filter_by(seq_idx=1).first()
        self.assertIsNotNone(point_db)
        self.assertEqual(point_db.route_id, route.id)

    def test_route_point_relationships(self):
        yacht = self.create_yacht_instance()
        weather_vector = self.create_weather_vector_instance()
        self.Session.add_all([yacht, weather_vector])
        self.Session.commit()

        route = self.create_route_instance(yacht.id)
        self.Session.add(route)
        self.Session.commit()

        route_point = self.create_route_point_instance(route.id, weather_vector.id)
        self.Session.add(route_point)
        self.Session.commit()

        point_db = self.Session.query(RoutePoint).first()
        self.assertEqual(point_db.route.description, "Test Route")

        self.assertEqual(point_db.weather_vector.speed, 15.5)

    def create_yacht_instance(self) -> Yacht:
        return Yacht(
            name="Test Yacht",
            yacht_type=YachtType.SAILBOAT,
            length=12.5,
            beam=3.8
        )

    def create_route_instance(self, yacht_id) -> Route:
        return Route(
            user_id=uuid4(),
            yacht_id=yacht_id,
            description="Test Route"
        )

    def create_weather_vector_instance(self) -> WeatherVector:
        return WeatherVector(
            dir=270.0,  # West wind
            speed=15.5  # 15.5 knots
        )

    def create_route_point_instance(self, route_id, weather_vector_id) -> RoutePoint:
        return RoutePoint(
            route_id=route_id,
            seq_idx=1,
            x=18.6466,  # Gdansk longitude
            y=54.3520,  # Gdansk latitude
            weather_vector_id=weather_vector_id,
            heuristic_score=0.8
        )


class TestWeatherForecast(DatabaseTest):

    def test_create_weather_forecast(self):
        yacht = self.create_yacht_instance()
        weather_vector = self.create_weather_vector_instance()
        self.Session.add_all([yacht, weather_vector])
        self.Session.commit()

        route = self.create_route_instance(yacht.id)
        self.Session.add(route)
        self.Session.commit()

        route_point = self.create_route_point_instance(route.id, weather_vector.id)
        self.Session.add(route_point)
        self.Session.commit()

        forecast = self.create_weather_forecast_instance(route_point.id, weather_vector.id)
        self.Session.add(forecast)
        self.Session.commit()

        self.assertIsNotNone(forecast.id)
        
        forecast_db = self.Session.query(WeatherForecast).first()
        self.assertEqual(forecast_db.wind_speed, 12.0)
        self.assertEqual(forecast_db.route_point_id, route_point.id)

    def test_weather_forecast_route_point_relationship(self):
        yacht = self.create_yacht_instance()
        weather_vector = self.create_weather_vector_instance()
        self.Session.add_all([yacht, weather_vector])
        self.Session.commit()

        route = self.create_route_instance(yacht.id)
        self.Session.add(route)
        self.Session.commit()

        route_point = self.create_route_point_instance(route.id, weather_vector.id)
        self.Session.add(route_point)
        self.Session.commit()

        forecast = self.create_weather_forecast_instance(route_point.id, weather_vector.id)
        self.Session.add(forecast)
        self.Session.commit()

        point_db = self.Session.query(RoutePoint).first()
        self.assertEqual(len(point_db.weather_forecasts), 1)
        self.assertEqual(point_db.weather_forecasts[0].wind_speed, 12.0)

    def create_yacht_instance(self) -> Yacht:
        return Yacht(
            name="Test Yacht",
            yacht_type=YachtType.SAILBOAT,
            length=12.5,
            beam=3.8
        )

    def create_route_instance(self, yacht_id) -> Route:
        return Route(
            user_id=uuid4(),
            yacht_id=yacht_id,
            description="Test Route"
        )

    def create_weather_vector_instance(self) -> WeatherVector:
        return WeatherVector(
            dir=270.0,
            speed=15.5
        )

    def create_route_point_instance(self, route_id, weather_vector_id) -> RoutePoint:
        return RoutePoint(
            route_id=route_id,
            seq_idx=1,
            x=18.6466,
            y=54.3520,
            weather_vector_id=weather_vector_id
        )

    def create_weather_forecast_instance(self, route_point_id, weather_vector_id) -> WeatherForecast:
        return WeatherForecast(
            route_point_id=route_point_id,
            forecast_timestamp=datetime.now() + timedelta(hours=6),
            wind_speed=12.0,
            wind_direction=280.0,
            temperature=18.5,
            humidity=65.0,
            desc="Partly cloudy",
            weather_vector_id=weather_vector_id
        )


class TestRouteSegments(DatabaseTest):

    def test_create_route_segment(self):
        yacht = self.create_yacht_instance()
        weather_vector = self.create_weather_vector_instance()
        self.Session.add_all([yacht, weather_vector])
        self.Session.commit()

        route = self.create_route_instance(yacht.id)
        self.Session.add(route)
        self.Session.commit()

        from_point = self.create_route_point_instance(route.id, weather_vector.id, seq_idx=1)
        to_point = self.create_route_point_instance(route.id, weather_vector.id, seq_idx=2)
        self.Session.add_all([from_point, to_point])
        self.Session.commit()

        segment = self.create_route_segment_instance(route.id, from_point.id, to_point.id)
        self.Session.add(segment)
        self.Session.commit()

        self.assertIsNotNone(segment.id)
        
        segment_db = self.Session.query(RouteSegments).first()
        self.assertEqual(segment_db.segment_order, 1)
        self.assertEqual(segment_db.sail_type, "genoa")

    def test_route_segment_relationships(self):
        yacht = self.create_yacht_instance()
        weather_vector = self.create_weather_vector_instance()
        self.Session.add_all([yacht, weather_vector])
        self.Session.commit()

        route = self.create_route_instance(yacht.id)
        self.Session.add(route)
        self.Session.commit()

        from_point = self.create_route_point_instance(route.id, weather_vector.id, seq_idx=1)
        to_point = self.create_route_point_instance(route.id, weather_vector.id, seq_idx=2)
        self.Session.add_all([from_point, to_point])
        self.Session.commit()

        segment = self.create_route_segment_instance(route.id, from_point.id, to_point.id)
        self.Session.add(segment)
        self.Session.commit()

        # Test relationships
        segment_db = self.Session.query(RouteSegments).first()
        self.assertEqual(segment_db.route.description, "Test Route")
        self.assertEqual(segment_db.from_point_rel.seq_idx, 1)
        self.assertEqual(segment_db.to_point_rel.seq_idx, 2)

        route_db = self.Session.query(Route).first()
        self.assertEqual(len(route_db.route_segments), 1)

    def test_multiple_segments_sequence(self):
        yacht = self.create_yacht_instance()
        weather_vector = self.create_weather_vector_instance()
        self.Session.add_all([yacht, weather_vector])
        self.Session.commit()

        route = self.create_route_instance(yacht.id)
        self.Session.add(route)
        self.Session.commit()

        point1 = self.create_route_point_instance(route.id, weather_vector.id, seq_idx=1)
        point2 = self.create_route_point_instance(route.id, weather_vector.id, seq_idx=2)
        point3 = self.create_route_point_instance(route.id, weather_vector.id, seq_idx=3)
        self.Session.add_all([point1, point2, point3])
        self.Session.commit()

        segment1 = self.create_route_segment_instance(route.id, point1.id, point2.id, segment_order=1)
        segment2 = self.create_route_segment_instance(route.id, point2.id, point3.id, segment_order=2)
        self.Session.add_all([segment1, segment2])
        self.Session.commit()

        route_db = self.Session.query(Route).first()
        self.assertEqual(len(route_db.route_segments), 2)

        segments_ordered = sorted(route_db.route_segments, key=lambda s: s.segment_order)
        self.assertEqual(segments_ordered[0].segment_order, 1)
        self.assertEqual(segments_ordered[1].segment_order, 2)

    def create_yacht_instance(self) -> Yacht:
        return Yacht(
            name="Test Yacht",
            yacht_type=YachtType.SAILBOAT,
            length=12.5,
            beam=3.8
        )

    def create_route_instance(self, yacht_id) -> Route:
        return Route(
            user_id=uuid4(),
            yacht_id=yacht_id,
            description="Test Route"
        )

    def create_weather_vector_instance(self) -> WeatherVector:
        return WeatherVector(
            dir=270.0,
            speed=15.5
        )

    def create_route_point_instance(self, route_id, weather_vector_id, seq_idx=1) -> RoutePoint:
        return RoutePoint(
            route_id=route_id,
            seq_idx=seq_idx,
            x=18.6466 + (seq_idx * 0.01),
            y=54.3520 + (seq_idx * 0.01),
            weather_vector_id=weather_vector_id
        )

    def create_route_segment_instance(self, route_id, from_point_id, to_point_id, segment_order=1) -> RouteSegments:
        return RouteSegments(
            route_id=route_id,
            from_point=from_point_id,
            to_point=to_point_id,
            segment_order=segment_order,
            recommended_course=045.0,
            estimated_time=30.0,  # 30 minutes
            sail_type="genoa",
            tack_type="bajdewind",
            maneuver_type="tack",
            distance_nm=2.5,
            bearing=045.0,
            wind_angle=45.0,
            current_effect=0.2
        )


class TestControlPoint(DatabaseTest):

    def test_create_control_point(self):
        yacht = self.create_yacht_instance()
        self.Session.add(yacht)
        self.Session.commit()

        route = self.create_route_instance(yacht.id)
        self.Session.add(route)
        self.Session.commit()

        control_point = self.create_control_point_instance(route.id)
        self.Session.add(control_point)
        self.Session.commit()

        self.assertIsNotNone(control_point.id)
        
        cp_db = self.Session.query(ControlPoint).filter_by(name="Start Buoy").first()
        self.assertIsNotNone(cp_db)
        self.assertEqual(cp_db.type, ControlPointType.BUOY)

    def test_control_point_route_relationship(self):
        yacht = self.create_yacht_instance()
        self.Session.add(yacht)
        self.Session.commit()

        route = self.create_route_instance(yacht.id)
        self.Session.add(route)
        self.Session.commit()

        control_point = self.create_control_point_instance(route.id)
        self.Session.add(control_point)
        self.Session.commit()

        route_db = self.Session.query(Route).first()
        self.assertEqual(len(route_db.control_points_rel), 1)
        self.assertEqual(route_db.control_points_rel[0].name, "Start Buoy")

    def create_yacht_instance(self) -> Yacht:
        return Yacht(
            name="Test Yacht",
            yacht_type=YachtType.SAILBOAT,
            length=12.5,
            beam=3.8
        )

    def create_route_instance(self, yacht_id) -> Route:
        return Route(
            user_id=uuid4(),
            yacht_id=yacht_id,
            description="Test Route"
        )

    def create_control_point_instance(self, route_id) -> ControlPoint:
        return ControlPoint(
            route_id=route_id,
            name="Start Buoy",
            x=18.6466,
            y=54.3520,
            width=10.0,
            type=ControlPointType.BUOY,
            desc="Starting point of the race"
        )


@pytest.fixture
def db_session():
    """Create a test database session"""
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    
    yield session
    
    session.close()


@pytest.fixture
def sample_yacht(db_session):
    """Create a sample yacht for testing"""
    yacht = Yacht(
        name="Test Yacht",
        yacht_type=YachtType.SAILBOAT,
        length=12.5,
        beam=3.8,
        has_spinnaker=True
    )
    db_session.add(yacht)
    db_session.commit()
    return yacht


@pytest.fixture
def sample_route(db_session, sample_yacht):
    """Create a sample route for testing"""
    route = Route(
        user_id=uuid4(),
        yacht_id=sample_yacht.id,
        description="Test Route",
    )
    db_session.add(route)
    db_session.commit()
    return route


def test_complex_route_with_fixtures(db_session, sample_yacht, sample_route):
    """Test creating a complex route with multiple components using fixtures"""

    weather_vector = WeatherVector(dir=270.0, speed=15.5)
    db_session.add(weather_vector)
    db_session.commit()

    point1 = RoutePoint(
        route_id=sample_route.id,
        seq_idx=1,
        x=18.6466,
        y=54.3520,
        weather_vector_id=weather_vector.id
    )
    point2 = RoutePoint(
        route_id=sample_route.id,
        seq_idx=2,
        x=18.6566,
        y=54.3620,
        weather_vector_id=weather_vector.id
    )
    db_session.add_all([point1, point2])
    db_session.commit()

    segment = RouteSegments(
        route_id=sample_route.id,
        from_point=point1.id,
        to_point=point2.id,
        segment_order=1,
        sail_type="genoa"
    )
    db_session.add(segment)
    db_session.commit()

    route_db = db_session.query(Route).filter_by(id=sample_route.id).first()
    assert len(route_db.route_points) == 2
    assert len(route_db.route_segments) == 1
    assert route_db.yacht.name == "Test Yacht"


if __name__ == '__main__':
    unittest.main()