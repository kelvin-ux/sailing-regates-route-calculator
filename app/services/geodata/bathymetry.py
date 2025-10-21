from __future__ import annotations

from dataclasses import dataclass
import numpy as np
import requests
import rasterio

from pathlib import Path
from typing import Iterable
from typing import List
from typing import Tuple
from typing import Dict
from typing import Any
from rasterio.features import shapes as rio_shapes
from shapely import wkt
from shapely.geometry import shape
from shapely.geometry import mapping
from shapely.geometry import Polygon
from shapely.geometry import MultiPolygon
from shapely.geometry import LineString
from shapely.ops import transform as shp_transform
from pyproj import CRS
from pyproj import Transformer


EMODNET_WCS = "https://ows.emodnet-bathymetry.eu/wcs"
EMODNET_COVERAGE = "emodnet:mean"

@dataclass
class WcsRequest:
    bbox_wgs84: Tuple[float, float, float, float]
    res_deg: float = 0.001  # ~110 m
    format: str = "image/tiff"

def _bbox_wgs84_from_local_wkt(water_wkt: str, epsg_local: int, pad_m: float = 0.0) -> Tuple[float, float, float, float]:
    local = CRS.from_epsg(epsg_local)
    wgs84 = CRS.from_epsg(4326)
    to_wgs = Transformer.from_crs(local, wgs84, always_xy=True).transform
    geom_local = wkt.loads(water_wkt)
    if pad_m and pad_m > 0:
        geom_local = geom_local.buffer(pad_m)
    geom_wgs = shp_transform(to_wgs, geom_local)
    minx, miny, maxx, maxy = geom_wgs.bounds
    return (minx, miny, maxx, maxy)

def fetch_wcs_geotiff(req: WcsRequest, out_path: Path) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if out_path.exists():
        return out_path
    params = {
        "service": "WCS", "version": "1.0.0", "request": "GetCoverage",
        "coverage": EMODNET_COVERAGE, "crs": "EPSG:4326",
        "bbox": f"{req.bbox_wgs84[1]},{req.bbox_wgs84[0]},{req.bbox_wgs84[3]},{req.bbox_wgs84[2]}".replace(",",","),
        "BBOX": f"{req.bbox_wgs84[0]},{req.bbox_wgs84[1]},{req.bbox_wgs84[2]},{req.bbox_wgs84[3]}",
        "format": req.format,
        "resx": req.res_deg, "resy": req.res_deg,
    }
    r = requests.get(EMODNET_WCS, params=params, timeout=90)
    r.raise_for_status()
    with open(out_path, "wb") as f:
        f.write(r.content)
    return out_path

def shallow_mask_from_tif(tif_path: Path, epsg_target: int, threshold_m: float) -> MultiPolygon | Polygon | None:
    with rasterio.open(tif_path) as ds:
        arr = ds.read(1).astype("float32")
        nodata = ds.nodata
        if np.nanmin(arr) < 0:
            arr = np.abs(arr)
        if nodata is not None:
            arr = np.where(arr == nodata, np.nan, arr)
        mask = np.where(np.isnan(arr), 0, (arr < threshold_m).astype("uint8"))
        results = []
        for geom, val in rio_shapes(mask, mask=mask.astype(bool), transform=ds.transform):
            if int(val) != 1:
                continue
            results.append(shape(geom))
        if not results:
            return None
        shp_wgs = MultiPolygon([g for g in results if isinstance(g, (Polygon, MultiPolygon))]).buffer(0)
        to_local = Transformer.from_crs(ds.crs, CRS.from_epsg(epsg_target), always_xy=True).transform
        shp_local = shp_transform(to_local, shp_wgs)
        shp_local = shp_local.buffer(10).buffer(-10)
        return shp_local

def contours_geojson_from_tif(tif_path: Path, levels: Iterable[float]) -> Dict[str, Any]:
    """
    Generuje GeoJSON z izobatami w CRS rastra (WGS84).
    Robimy to poprzez 'marching squares' rasterio+numpy
    """
    features = []
    with rasterio.open(tif_path) as ds:
        arr = ds.read(1).astype("float32")
        nodata = ds.nodata
        if nodata is not None:
            arr = np.where(arr == nodata, np.nan, arr)
        if np.nanmin(arr) < 0:
            arr = np.abs(arr)
        for lvl in sorted(levels):
            # maska: bliskie poziomu (okno tolerancji  - 0.15 m)
            tol = max(0.15, 0.01 * lvl)
            band = np.where(np.isnan(arr), 0, ((arr >= (lvl - tol)) & (arr <= (lvl + tol))).astype("uint8"))
            for geom, val in rio_shapes(band, mask=band.astype(bool), transform=ds.transform):
                if int(val) != 1:
                    continue
                poly = shape(geom)
                if isinstance(poly, Polygon):
                    lines = [poly.exterior] + list(poly.interiors)
                else:
                    lines = []
                for ln in lines:
                    ls = LineString(ln.coords)
                    if ls.length < 1e-5:
                        continue
                    features.append({
                        "type": "Feature",
                        "properties": {"type": "isobath", "level": float(lvl)},
                        "geometry": mapping(ls)
                    })
    return {"type": "FeatureCollection", "features": features}

def label_points_along_lines(fc: Dict[str, Any], step_m: float = 1500.0) -> Dict[str, Any]:
    def _densify(ls: LineString, every: float) -> List[Tuple[float, float]]:
        n = max(1, int(ls.length // every))
        return [ls.interpolate(i * ls.length / n).coords[0] for i in range(n + 1)]
    labels = []
    for f in fc.get("features", []):
        if f.get("properties", {}).get("type") != "isobath":
            continue
        geom = shape(f["geometry"])
        if not isinstance(geom, LineString):
            continue
        for x, y in _densify(geom, step_m):
            labels.append({
                "type": "Feature",
                "properties": {"type": "isobath_label", "text": str(f["properties"]["level"])},
                "geometry": {"type": "Point", "coordinates": [x, y]}
            })
    return {"type": "FeatureCollection", "features": labels}

def bands_geojson_from_tif(tif_path: Path, levels: List[float]) -> Dict[str, Any]:
    """
    Zwraca poligony pasm głębokości (levels definiuje granice: [0,1,2,3,5,10,...]).
    Każda cecha ma props: band_min, band_max.
    """
    features = []
    with rasterio.open(tif_path) as ds:
        arr = ds.read(1).astype("float32")
        nodata = ds.nodata
        if nodata is not None:
            arr = np.where(arr == nodata, np.nan, arr)
        if np.nanmin(arr) < 0:
            arr = np.abs(arr)
        lev = sorted(set([float(x) for x in levels if x is not None]))
        if lev[0] > 0: lev = [0.0] + lev
        for i in range(len(lev)-1):
            lo, hi = lev[i], lev[i+1]
            band = np.where(np.isnan(arr), 0, ((arr >= lo) & (arr < hi)).astype("uint8"))
            for geom, val in rio_shapes(band, mask=band.astype(bool), transform=ds.transform):
                if int(val) != 1: continue
                poly = shape(geom)
                if not isinstance(poly, (Polygon, MultiPolygon)): continue
                features.append({
                    "type": "Feature",
                    "properties": {"type": "depth_band", "band_min": lo, "band_max": hi},
                    "geometry": mapping(poly)
                })
    return {"type": "FeatureCollection", "features": features}
