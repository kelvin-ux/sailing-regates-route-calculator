from typing import Dict
from typing import Tuple
from dataclasses import dataclass


@dataclass
class SailingConditions:
    """
    Warunki żeglarskie w jednostkach morskich:
    - prędkości w węzłach (knots)
    - kierunki w stopniach (0-360)
    - wysokości fal w metrach
    """
    wind_speed: float  # knots
    wind_direction: float  # degrees (0-360, where 0 is North)
    wave_height: float  # meters
    wave_direction: float  # degrees
    wave_period: float  # seconds
    current_velocity: float  # knots
    current_direction: float  # degrees

    @classmethod
    def from_weather_data(cls, weather_data: Dict) -> 'SailingConditions':
        """
        Create SailingConditions from Marine API (open-meteo.com/v1/marine)
        Konwertuje m/s na węzły gdzie potrzeba.
        """
        required_fields = {
            "wind_speed_10m": "wind_speed",
            "wind_direction_10m": "wind_direction",
            "wave_height": "wave_height",
            "wave_direction": "wave_direction",
            "wave_period": "wave_period",
            "current_speed": "current_velocity",
            "current_direction": "current_direction"
        }

        missing = [api_key for api_key in required_fields if api_key not in weather_data]
        if missing:
            raise ValueError(f"Missing required marine API fields: {', '.join(missing)}")

        mapped = {}
        for api_key, model_key in required_fields.items():
            value = float(weather_data[api_key])

            # Konwersja m/s -> knots dla prędkości
            if model_key in ["wind_speed", "current_velocity"]:
                value = value * 1.94384  # m/s to knots

            mapped[model_key] = value

        # Normalize angles to 0–360°
        mapped["wind_direction"] %= 360
        mapped["wave_direction"] %= 360
        mapped["current_direction"] %= 360

        return cls(**mapped)


@dataclass
class NavigationState:
    """State of yacht at a navigation point"""
    position: Tuple[float, float]  # (x, y) in local coordinates
    heading: float  # degrees (0-360)
    speed: float  # knots
    tack: str  # 'port' or 'starboard'