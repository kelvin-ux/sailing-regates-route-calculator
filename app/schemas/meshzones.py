from dataclasses import dataclass

from typing import List


@dataclass
class MeshZones:
    """
    radii_m: [r1, r2, r3]  (metry od linii trasy: near, mid, far)
    max_area_m2: [a1, a2, a3]
    """
    radii_m: List[float]
    max_area_m2: List[float]

    def __post_init__(self):
        r = self.radii_m
        a = self.max_area_m2
        if len(r) != 3 or len(a) != 3:
            raise ValueError("MeshZones.radii_m i max_area_m2 muszą mieć długość 3.")
        if not (r[0] > 0 and r[1] > r[0] and r[2] > r[1]):
            raise ValueError("radii_m muszą być rosnące i dodatnie (r1 < r2 < r3).")
        if not (a[0] > 0 and a[1] >= a[0] and a[2] >= a[1]):
            raise ValueError("max_area_m2 muszą być dodatnie i niemalejące (a1 <= a2 <= a3).")
