from __future__ import annotations
import zipfile
from pathlib import Path
from typing import Tuple

import geopandas as gpd
import requests

OSM_LAND_URL = "https://osmdata.openstreetmap.de/download/land-polygons-split-4326.zip"

def ensure_land_polygons(cache_dir: Path) -> Path:
    """
    Pobiera i rozpakowuje land-polygons. Zwraca ścieżkę do pliku .gpkg.
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    zip_path = cache_dir / "land-polygons-split-4326.zip"
    gpkg_path = cache_dir / "land_polygons.gpkg"

    if not zip_path.exists():
        r = requests.get(OSM_LAND_URL, timeout=90)
        r.raise_for_status()
        zip_path.write_bytes(r.content)

    if not gpkg_path.exists():
        extract_dir = cache_dir / "tmp_land"
        extract_dir.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(extract_dir)

        shp_files = list(extract_dir.rglob("*.shp"))
        if not shp_files:
            raise RuntimeError(
                f"Nie znaleziono pliku .shp po rozpakowaniu {zip_path}. "
                f"Sprawdź zawartość {extract_dir}"
            )

        gdf = gpd.read_file(shp_files[0])
        if gdf.crs is None:
            gdf = gdf.set_crs(4326)
        gdf.to_file(gpkg_path, driver="GPKG")

    return gpkg_path

def land_in_bbox(gpkg_path: Path, bbox_wgs84: Tuple[float, float, float, float]) -> gpd.GeoDataFrame:
    """
    Zwraca ląd przycięty do bboxu --> bbox = (south, west, north, east)
    """
    gdf = gpd.read_file(gpkg_path)
    west, east = bbox_wgs84[1], bbox_wgs84[3]
    south, north = bbox_wgs84[0], bbox_wgs84[2]
    gdf = gdf.cx[west:east, south:north].explode(ignore_index=True)
    return gdf
