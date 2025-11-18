import logging
import os

# Ensure log directory exists
LOG_DIR = "logs"
os.makedirs(LOG_DIR, exist_ok=True)

LOG_FILE_PATH = os.path.join(LOG_DIR, "routing.log")

# Create logger
logger = logging.getLogger("routing")
logger.setLevel(logging.DEBUG)

# File handler
file_handler = logging.FileHandler(LOG_FILE_PATH, encoding='utf-8')
file_handler.setLevel(logging.DEBUG)

# Log format
formatter = logging.Formatter(
    "[%(asctime)s] [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
file_handler.setFormatter(formatter)

# Add handler only once
if not logger.handlers:
    logger.addHandler(file_handler)

# --- Helper functions ---

def log_weather(vertex_idx, weather_idx, message):
    logger.debug(f"[WEATHER] vertex={vertex_idx}, weather_idx={weather_idx}, {message}")

def log_edge(from_idx, to_idx, twa, boat_speed, wind):
    logger.debug(
        f"[EDGE] {from_idx}->{to_idx} | TWA={twa:.1f} | wind={wind:.2f} | boat_speed={boat_speed:.2f}"
    )

def log_impassable(from_idx, to_idx, reason):
    logger.debug(f"[IMPASSABLE] {from_idx}->{to_idx}: {reason}")

def log_info(msg):
    logger.info(msg)

def log_debug(msg):
    logger.debug(msg)

def log_error(msg):
    logger.error(msg)
