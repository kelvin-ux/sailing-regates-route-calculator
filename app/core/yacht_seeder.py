import uuid
from typing import Dict, Any
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.models import Yacht, YachtType

YACHT_IDS = {
    "CLASS_40": "11111111-1111-1111-1111-11111111111a",
    "VOLVO_65": "22222222-2222-2222-2222-22222222222b",
    "OMEGA": "33333333-3333-3333-3333-33333333333c",
    "BAVARIA_46": "44444444-4444-4444-4444-44444444444d",
    "OYSTER_72": "55555555-5555-5555-5555-55555555555e",
    "TP_52": "66666666-6666-6666-6666-66666666666f",
    "IMOCA_60": "77777777-7777-7777-7777-77777777777a"
}


def _generate_simple_polars(max_speed: float) -> Dict[str, Any]:
    twa_angles = [0, 30, 52, 60, 75, 90, 110, 120, 135, 150, 180]
    wind_speeds = [4, 6, 8, 10, 12, 14, 16, 20, 25, 30]

    boat_speeds = []
    for twa in twa_angles:
        angle_speeds = []
        angle_factor = 1.0
        if twa < 40:
            angle_factor = 0.5  # Pod wiatr wolno
        elif twa < 90:
            angle_factor = 0.9  # Ostry bajdewind
        elif twa < 120:
            angle_factor = 1.0  # Półwiatr
        else:
            angle_factor = 0.85  # Z wiatrem

        for ws in wind_speeds:
            speed = min(max_speed, ws * 0.6 * angle_factor)
            if ws > 25: speed *= 0.9
            angle_speeds.append(round(speed, 2))
        boat_speeds.append(angle_speeds)

    return {
        "twa_angles": twa_angles,
        "wind_speeds": wind_speeds,
        "boat_speeds": boat_speeds
    }


PREDEFINED_YACHTS = [
    {
        "id": YACHT_IDS["CLASS_40"],
        "name": "Class 40 Racing",
        "yacht_type": YachtType.CLASS_40,
        "length": 40.0,
        "beam": 4.50,
        "draft": 3.00,
        "sail_number": "POL-40",
        "max_speed": 25.0,
        "max_wind_speed": 40.0,
        "polar_data": _generate_simple_polars(25.0),
        "amount_of_crew": 2,
        "tack_time": 30.0,
        "jibe_time": 25.0,
        "has_spinnaker": True,
        "has_genaker": True
    },
    {
        "id": YACHT_IDS["VOLVO_65"],
        "name": "Volvo Ocean 65",
        "yacht_type": YachtType.OPEN_60,
        "length": 65.0,
        "beam": 5.60,
        "draft": 4.78,
        "sail_number": "VO65-1",
        "max_speed": 35.0,
        "max_wind_speed": 50.0,
        "polar_data": _generate_simple_polars(35.0),
        "amount_of_crew": 10,
        "tack_time": 45.0,
        "jibe_time": 40.0,
        "has_spinnaker": True,
        "has_genaker": True
    },
    {
        "id": YACHT_IDS["OMEGA"],
        "name": "Omega Standard",
        "yacht_type": YachtType.OMEGA,
        "length": 20.3,
        "beam": 1.80,
        "draft": 0.20,
        "sail_number": "OMEGA-1",
        "max_speed": 7.0,
        "max_wind_speed": 20.0,
        "polar_data": _generate_simple_polars(7.0),
        "amount_of_crew": 3,
        "tack_time": 10.0,
        "jibe_time": 8.0,
        "has_spinnaker": True,
        "has_genaker": False
    },
    {
        "id": YACHT_IDS["BAVARIA_46"],
        "name": "Bavaria Cruiser 46",
        "yacht_type": YachtType.SAILBOAT,
        "length": 46.0,
        "beam": 4.35,
        "draft": 2.10,
        "sail_number": "BAV-46",
        "max_speed": 9.5,
        "max_wind_speed": 35.0,
        "polar_data": _generate_simple_polars(9.5),
        "amount_of_crew": 6,
        "tack_time": 60.0,
        "jibe_time": 90.0,
        "has_spinnaker": False,
        "has_genaker": False
    },
    {
        "id": YACHT_IDS["OYSTER_72"],
        "name": "Oyster 72",
        "yacht_type": YachtType.SAILBOAT,
        "length": 72.0,
        "beam": 5.85,
        "draft": 2.50,
        "sail_number": "OY-72",
        "max_speed": 12.0,
        "max_wind_speed": 40.0,
        "polar_data": _generate_simple_polars(12.0),
        "amount_of_crew": 8,
        "tack_time": 90.0,
        "jibe_time": 120.0,
        "has_spinnaker": True,
        "has_genaker": False
    },
    {
        "id": YACHT_IDS["TP_52"],
        "name": "TP52 Racing",
        "yacht_type": YachtType.SAILBOAT,
        "length": 52.0,
        "beam": 4.42,
        "draft": 3.50,
        "sail_number": "TP-52",
        "max_speed": 28.0,
        "max_wind_speed": 45.0,
        "polar_data": _generate_simple_polars(28.0),
        "amount_of_crew": 12,
        "tack_time": 20.0,
        "jibe_time": 15.0,
        "has_spinnaker": True,
        "has_genaker": True
    },
    {
        "id": YACHT_IDS["IMOCA_60"],
        "name": "IMOCA 60",
        "yacht_type": YachtType.OPEN_60,
        "length": 60.0,
        "beam": 5.85,
        "draft": 4.50,
        "sail_number": "IMOCA-60",
        "max_speed": 40.0,
        "max_wind_speed": 55.0,
        "polar_data": _generate_simple_polars(40.0),
        "amount_of_crew": 1,
        "tack_time": 120.0,
        "jibe_time": 100.0,
        "has_spinnaker": True,
        "has_genaker": True
    }
]


async def seed_yachts(session: AsyncSession):
    for yacht_data in PREDEFINED_YACHTS:
        yacht_id = uuid.UUID(yacht_data["id"])

        query = select(Yacht).where(Yacht.id == yacht_id)
        result = await session.execute(query)
        existing_yacht = result.scalar_one_or_none()

        if not existing_yacht:
            new_yacht = Yacht(**yacht_data)
            new_yacht.id = yacht_id
            session.add(new_yacht)


    await session.commit()