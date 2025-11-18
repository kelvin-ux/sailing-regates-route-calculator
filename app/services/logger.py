import logging
import os

# Ensure log directory exists
LOG_DIR = "logs"
os.makedirs(LOG_DIR, exist_ok=True)

# Log file paths
ROUTING_LOG_FILE_PATH = os.path.join(LOG_DIR, "routing.log")
WEATHER_LOG_FILE_PATH = os.path.join(LOG_DIR, "weather.log")

# Create routing logger
routing_logger = logging.getLogger("routing")
routing_logger.setLevel(logging.DEBUG)

# File handler for routing logs
routing_file_handler = logging.FileHandler(ROUTING_LOG_FILE_PATH, encoding='utf-8')
routing_file_handler.setLevel(logging.DEBUG)

# Log format for routing
formatter = logging.Formatter(
    "[%(asctime)s] [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
routing_file_handler.setFormatter(formatter)

# Add handler only once for routing logs
if not routing_logger.handlers:
    routing_logger.addHandler(routing_file_handler)

# Create weather logger
weather_logger = logging.getLogger("weather")
weather_logger.setLevel(logging.DEBUG)

# File handler for weather logs
weather_file_handler = logging.FileHandler(WEATHER_LOG_FILE_PATH, encoding='utf-8')
weather_file_handler.setLevel(logging.DEBUG)

# Log format for weather
weather_formatter = logging.Formatter(
    "[%(asctime)s] [%(levelname)s] [WEATHER] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
weather_file_handler.setFormatter(weather_formatter)

# Add handler only once for weather logs
if not weather_logger.handlers:
    weather_logger.addHandler(weather_file_handler)

# --- Helper functions ---

def log_weather(vertex_idx, weather_idx, message):
    weather_logger.debug(f"vertex={vertex_idx}, weather_idx={weather_idx}, {message}")

def log_edge(from_idx, to_idx, twa, boat_speed, wind, time_cost):
    routing_logger.debug(
        f"{from_idx}->{to_idx} | TWA={twa:.1f} | wind={wind:.2f} | boat_speed={boat_speed:.2f} | time_cost={time_cost}"
    )

def log_impassable(from_idx, to_idx, reason):
    routing_logger.debug(f"{from_idx}->{to_idx}: {reason}")

def log_info(msg):
    routing_logger.info(msg)

def log_debug(msg):
    routing_logger.debug(msg)

def log_error(msg):
    routing_logger.error(msg)