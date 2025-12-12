from typing import Optional
from typing import Dict

import numpy as np

class WeatherDataValidator:
    @staticmethod
    def validate_weather_data(data: Dict) -> bool:
        required_fields = [
            'wind_speed_10m', 'wind_direction_10m',
            'wave_height', 'wave_direction', 'wave_period',
            'current_speed', 'current_direction'
        ]

        for field in required_fields:
            if field not in data:
                return False

            value = data[field]
            if value is None:
                return False

            if isinstance(value, (int, float)):
                if not np.isfinite(value):
                    return False

                if field == 'wind_speed_10m' and (value < 0 or value > 100):  # knots
                    return False
                if field == 'wave_height' and (value < 0 or value > 30):  # meters
                    return False
                if field == 'wave_period' and (value < 0 or value > 30):  # seconds
                    return False
                if 'direction' in field and (value < 0 or value >= 360):
                    return False
            else:
                return False

        return True

    @staticmethod
    def validate_depth(depth: Optional[float], min_depth: float = 3.0) -> bool:
        if depth is None:
            return False  # No depth data = not navigable
        if not np.isfinite(depth):
            return False
        return depth >= min_depth