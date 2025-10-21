from __future__ import annotations
from pathlib import Path
import geopandas as gpd
from shapely.geometry import Polygon, MultiPolygon
from shapely.ops import unary_union
from pyproj import CRS
from .corridor import corridor_bbox_wgs84, _to_proj
from .osm_land import ensure_land_polygons, land_in_bbox

def water_polygon_in_corridor(corridor_xy: Polygon, local_crs: CRS, data_dir: Path) -> Polygon:
    """
    Wylicza poligon akwenu = korytarz - ląd.
    """

    gpkg = ensure_land_polygons(data_dir / "geodata")
    bbox = corridor_bbox_wgs84(corridor_xy, local_crs)
    land_wgs = land_in_bbox(gpkg, bbox)

    land_xy = land_wgs.to_crs(local_crs)
    land_union = unary_union(land_xy.geometry.values)

    water_xy = corridor_xy.difference(land_union)
    if isinstance(water_xy, MultiPolygon):
        water_xy = max(list(water_xy.geoms), key=lambda p: p.area)
    return water_xy
