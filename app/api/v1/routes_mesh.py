from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Path
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import UUID4
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db as get_async_session
from app.schemas.mesh import CreateRouteAndMeshIn, CreateRouteAndMeshOut
from app.services.mesh.mesh_builder import create_route_and_mesh
from app.services.mesh.map_data import build_map_geojson
from app.services.db.services import MeshedAreaService

from app.services.geodata.bathymetry import (
_bbox_wgs84_from_local_wkt, fetch_wcs_geotiff,contours_geojson_from_tif, label_points_along_lines, WcsRequest
)
router = APIRouter()


@router.post("/mesh", response_model=CreateRouteAndMeshOut, status_code=201)
async def create_route_and_mesh_ep(payload: CreateRouteAndMeshIn, session: AsyncSession = Depends(get_async_session)):
    try:
        return await create_route_and_mesh(session, payload)
    except Exception as e:
        raise HTTPException(400, str(e))

@router.get("/{meshed_area_id}/map")
async def get_map_geojson(meshed_area_id: UUID4, session: AsyncSession = Depends(get_async_session)):
    data = await build_map_geojson(session, meshed_area_id)
    return JSONResponse(data)

@router.get("/{meshed_area_id}/view", response_class=HTMLResponse)
async def view_mesh(meshed_area_id: UUID4):
    """
    Prosty podgląd siatki i korytarza na mapie:
    - OSM jako podstawa,
    - EMODnet Bathymetry (WMS) jako overlay,
    - OpenSeaMap seamarks jako overlay,
    - dane z /map.
    """
    html = f"""
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8" />
  <title>Route Mesh Viewer</title>
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
  <style>
    html, body, #map {{ height: 100%; margin: 0; }}
    .legend {{ background: white; padding: 6px 8px; font: 14px/16px Arial; }}
    .bathy-label div {{ font:11px/11px monospace;color:#002244;background:rgba(255,255,255,.65);padding:1px 2px;border-radius:2px }}
  </style>
</head>
<body>
<div id="map"></div>

<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script>
const map = L.map('map').setView([54.5, 18.8], 9);

const osmBase = L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{
  maxZoom: 19,
  attribution: '&copy; OpenStreetMap contributors'
}}).addTo(map);

// EMODnet Bathymetry (WMS)
const emodnet = L.tileLayer.wms('https://ows.emodnet-bathymetry.eu/wms', {{
  layers: 'emodnet:mean_multicolour',
  format: 'image/png',
  transparent: true,
  opacity: 0.65,
  attribution: '© EMODnet Bathymetry'
}});

// OpenSeaMap seamarks (kafle)
const seamarks = L.tileLayer('https://tiles.openseamap.org/seamark/{{z}}/{{x}}/{{y}}.png', {{
  opacity: 0.9,
  attribution: '© OpenSeaMap contributors'
}});

const overlays = {{
  "EMODnet Bathy": emodnet,
  "Seamarks": seamarks
}};

L.control.layers({{ "OSM": osmBase }}, overlays, {{ collapsed: false }}).addTo(map);

// Style naszych warstw
function styleMesh(feature) {{
  return {{ weight: 1, opacity: 0.85, color: '#2a53d6' }};
}}
function styleWater(feature) {{
  return {{ color: '#1e90ff', weight: 2, fillColor: '#1e90ff', fillOpacity: 0.10 }};
}}
function styleRoute(feature) {{
  return {{ color: '#ff5a36', weight: 3 }};
}}

fetch(`/api/v1/routes_mesh/{meshed_area_id}/map`)
  .then(r => r.json())
  .then(fc => {{
    const mesh = L.geoJSON(fc, {{
      filter: f => f.properties && f.properties.type === 'mesh_wire',
      style: styleMesh
    }}).addTo(map);

    const water = L.geoJSON(fc, {{
      filter: f => f.properties && f.properties.type === 'water_corridor',
      style: styleWater
    }}).addTo(map);

    const route = L.geoJSON(fc, {{
      filter: f => f.properties && f.properties.type === 'route',
      style: styleRoute
    }}).addTo(map);

    const pts = L.geoJSON(fc, {{
      filter: f => f.properties && f.properties.type === 'control_point',
      pointToLayer: (f, latlng) => L.circleMarker(latlng, {{
        radius: 5, weight: 2, color: '#222', fillColor: '#ffd200', fillOpacity: 0.9
      }}).bindTooltip('CP ' + f.properties.seq_idx)
    }}).addTo(map);

    const g = L.featureGroup([water, route, pts]);
    try {{ map.fitBounds(g.getBounds(), {{ padding: [20, 20] }}); }} catch(e) {{}}

    // Dołóż izobaty (linie + etykiety)
    fetch(`/api/v1/routes_mesh/{meshed_area_id}/contours?levels=1,2,3,5,10,20,50`)
      .then(r => r.json())
      .then(data => {{
        L.geoJSON(data.lines, {{
          style: f => ({{ color: '#0055cc', weight: 1, opacity: 0.7 }})
        }}).addTo(map);

        L.geoJSON(data.labels, {{
          pointToLayer: (f, latlng) => L.marker(latlng, {{
            icon: L.divIcon({{className:'bathy-label', html:`<div>${{f.properties.text}}</div>`}})
          }})
        }}).addTo(map);
      }});
  }})
  .catch(err => {{
    console.error(err);
    alert('Failed to load map data.');
  }});
</script>
</body>
</html>
    """
    return HTMLResponse(content=html)


# ==========================================================
# GET /{id}/contours – izobaty (linie + etykiety) z EMODnet
# ==========================================================
from app.services.geodata.bathymetry import (
    WcsRequest, fetch_wcs_geotiff, contours_geojson_from_tif,
    label_points_along_lines, bands_geojson_from_tif, _bbox_wgs84_from_local_wkt
)

@router.get("/{meshed_area_id}/contours")
async def get_contours(
    meshed_area_id: str,
    levels: str = "1,2,3,5,10,20,50",
    session: AsyncSession = Depends(get_async_session),
):
    svc = MeshedAreaService(session)
    m = await svc.get_entity_by_id(meshed_area_id, allow_none=False)

    epsg = int(m.crs_epsg or 4326)
    bbox_wgs = _bbox_wgs84_from_local_wkt(m.water_wkt, epsg, pad_m=0.0)

    cache_dir = Path("data/geodata/bathy/cache"); cache_dir.mkdir(parents=True, exist_ok=True)
    tif_path = fetch_wcs_geotiff(WcsRequest(bbox_wgs84=bbox_wgs, res_deg=0.001),
                                 cache_dir / f"bathy_{meshed_area_id}.tif")

    lvl = [float(x.strip()) for x in levels.split(",") if x.strip()]
    fc_bands  = bands_geojson_from_tif(tif_path, lvl)
    fc_lines  = contours_geojson_from_tif(tif_path, lvl)
    fc_labels = label_points_along_lines(fc_lines, step_m=1500.0)
    return {"bands": fc_bands, "lines": fc_lines, "labels": fc_labels}
