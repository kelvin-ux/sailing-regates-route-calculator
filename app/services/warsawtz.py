from zoneinfo import ZoneInfo
from datetime import datetime
WARSAW_TZ = ZoneInfo("Europe/Warsaw")

def now_warsaw() -> datetime:
    return datetime.now(ZoneInfo("Europe/Warsaw"))

def parse_datetime_warsaw(value):
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace('Z', '+00:00'))

    if value.tzinfo is None:
        value = value.replace(tzinfo=WARSAW_TZ)

    return value.astimezone(WARSAW_TZ)