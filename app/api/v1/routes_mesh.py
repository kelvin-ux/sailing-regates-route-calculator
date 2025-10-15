from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Literal, Optional, Dict, Any, List
from datetime import datetime

import numpy as np
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import UUID4, BaseModel, Field
from pyproj import Transformer
from shapely import wkt as shapely_wkt
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db as get_async_session
from app.schemas.mesh import CreateRouteAndMeshIn, CreateRouteAndMeshOut
from app.services.db.services import MeshedAreaService
from app.services.geodata.bathymetry import (
    WcsRequest,
    fetch_wcs_geotiff,
    contours_geojson_from_tif,
    label_points_along_lines,
    _bbox_wgs84_from_local_wkt
)
from app.services.mesh.map_data import build_map_geojson
from app.services.mesh.mesh_builder import create_route_and_mesh

router = APIRouter()

@router.post("/mesh", response_model=CreateRouteAndMeshOut, status_code=201)
async def create_route_and_mesh_ep(
        payload: CreateRouteAndMeshIn,
        session: AsyncSession = Depends(get_async_session)
):
    """
    Tworzy trasę i mesh nawigacyjny.

    Przykładowe dane:
    ```json
    {
      "user_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
      "yacht_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
      "points": [
        {"lat": 54.52, "lon": 18.55},
        {"lat": 54.35, "lon": 18.65}
      ],
      "corridor_nm": 3.0,
      "ring1_m": 500,
      "ring2_m": 1500,
      "ring3_m": 3000,
      "area1": 3000,
      "area2": 15000,
      "area3": 60000
    }
    ```
    """
    try:
        return await create_route_and_mesh(session, payload)
    except Exception as e:
        raise HTTPException(400, str(e))


@router.get("/{meshed_area_id}/weather-points")
async def get_weather_points(
        meshed_area_id: UUID4,
        session: AsyncSession = Depends(get_async_session)
):
    """
    Zwraca punkty pogodowe jako GeoJSON do wyświetlenia na mapie.
    """
    svc = MeshedAreaService(session)
    meshed = await svc.get_entity_by_id(meshed_area_id, allow_none=False)

    weather_data = {}
    if hasattr(meshed, 'weather_data_json') and meshed.weather_data_json:
        weather_data = json.loads(meshed.weather_data_json)

    if not weather_data:
        nodes = np.array(json.loads(meshed.nodes_json))
        step = max(1, len(nodes) // 30)
        selected_indices = list(range(0, len(nodes), step))[:30]
        weather_points = nodes[selected_indices]

        transformer = Transformer.from_crs(meshed.crs_epsg, 4326, always_xy=True)

        features = []
        for i, point in enumerate(weather_points):
            x, y = float(point[0]), float(point[1])
            lon, lat = transformer.transform(x, y)

            features.append({
                "type": "Feature",
                "properties": {
                    "index": i,
                    "has_data": False
                },
                "geometry": {
                    "type": "Point",
                    "coordinates": [lon, lat]
                }
            })
    else:
        features = []
        for idx, data in weather_data.items():
            features.append({
                "type": "Feature",
                "properties": {
                    "index": int(idx),
                    "has_data": True,
                    "wind_speed": data.get("wind_speed"),
                    "wind_dir": data.get("wind_dir"),
                    "temp": data.get("temp"),
                    "pressure": data.get("pressure"),
                    "humidity": data.get("humidity"),
                    "description": data.get("description"),
                    "timestamp": data.get("timestamp")
                },
                "geometry": {
                    "type": "Point",
                    "coordinates": [
                        data["coords"]["lon"] if "coords" in data else 0,
                        data["coords"]["lat"] if "coords" in data else 0
                    ]
                }
            })

    return {
        "type": "FeatureCollection",
        "features": features
    }


@router.get("/{meshed_area_id}/map")
async def get_map_geojson(
        meshed_area_id: UUID4,
        session: AsyncSession = Depends(get_async_session)
):
    data = await build_map_geojson(session, meshed_area_id)
    return JSONResponse(data)


@router.get("/{meshed_area_id}/contours")
async def get_contours(
        meshed_area_id: UUID4,
        levels: str = Query("1,2,3,5,10,20,50"),
        session: AsyncSession = Depends(get_async_session)
):
    """Zwraca izobaty (linie głębokości) dla obszaru mesh."""
    svc = MeshedAreaService(session)
    m = await svc.get_entity_by_id(meshed_area_id, allow_none=False)

    epsg = int(m.crs_epsg or 4326)
    bbox_wgs = _bbox_wgs84_from_local_wkt(m.water_wkt, epsg, pad_m=0.0)

    cache_dir = Path("data/geodata/bathy/cache")
    cache_dir.mkdir(parents=True, exist_ok=True)

    tif_path = fetch_wcs_geotiff(
        WcsRequest(bbox_wgs84=bbox_wgs, res_deg=0.001),
        cache_dir / f"bathy_{meshed_area_id}.tif"
    )

    lvl = [float(x.strip()) for x in levels.split(",") if x.strip()]
    fc_lines = contours_geojson_from_tif(tif_path, lvl)
    fc_labels = label_points_along_lines(fc_lines, step_m=1500.0)

    return {"lines": fc_lines, "labels": fc_labels}


@router.get("/{meshed_area_id}/view", response_class=HTMLResponse)
async def view_mesh(meshed_area_id: UUID4):
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

    .info-box {{
      position: absolute;
      top: 10px;
      right: 10px;
      background: white;
      padding: 10px;
      border-radius: 5px;
      box-shadow: 0 0 15px rgba(0,0,0,0.2);
      z-index: 1000;
    }}

    .weather-point {{
      background: radial-gradient(circle, #ff6b6b, #ff3333);
      border: 2px solid white;
      border-radius: 50%;
      width: 12px !important;
      height: 12px !important;
    }}

    .weather-point-nodata {{
      background: #999;
      opacity: 0.5;
    }}

    .control-point {{
      background: #ffd700;
      border: 2px solid #000;
      border-radius: 50%;
      width: 10px !important;
      height: 10px !important;
    }}
  </style>
</head>
<body>
<div id="map"></div>
<div class="info-box">
  <h4>Mesh Info</h4>
  <div id="stats">Loading...</div>
  <hr>
  <label><input type="checkbox" id="toggle-mesh" checked> Mesh</label><br>
  <label><input type="checkbox" id="toggle-weather" checked> Weather</label><br>
  <label><input type="checkbox" id="toggle-bathymetry"> Bathymetry</label>
</div>

<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script>
const map = L.map('map').setView([54.5, 18.8], 10);

L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{
  maxZoom: 19,
  attribution: '© OpenStreetMap'
}}).addTo(map);

let meshLayer, weatherLayer, bathyLayer;

// Załaduj dane mesh
fetch('/api/v1/routes_mesh/{meshed_area_id}/map')
  .then(r => r.json())
  .then(data => {{
    // Mesh
    meshLayer = L.geoJSON(data, {{
      filter: f => f.properties?.type === 'mesh_wire',
      style: {{ color: '#2a53d6', weight: 1, opacity: 0.6 }}
    }}).addTo(map);

    // Korytarz wodny
    L.geoJSON(data, {{
      filter: f => f.properties?.type === 'water_corridor',
      style: {{ color: '#1e90ff', weight: 2, fillOpacity: 0.1 }}
    }}).addTo(map);

    // Trasa
    L.geoJSON(data, {{
      filter: f => f.properties?.type === 'route',
      style: {{ color: '#ff3333', weight: 3 }}
    }}).addTo(map);

    // Punkty kontrolne
    L.geoJSON(data, {{
      filter: f => f.properties?.type === 'control_point',
      pointToLayer: (f, ll) => L.marker(ll, {{
        icon: L.divIcon({{
          className: 'control-point',
          iconSize: [10, 10]
        }})
      }})
    }}).addTo(map);

    // Dopasuj widok
    map.fitBounds(meshLayer.getBounds());

    // Statystyki
    const edges = data.features.find(f => f.properties?.type === 'mesh_wire')?.properties?.edges || 0;
    document.getElementById('stats').innerHTML = `Points: ${{edges}}`;
  }});

// Załaduj punkty pogodowe
fetch('/api/v1/routes_mesh/{meshed_area_id}/weather-points')
  .then(r => r.json())
  .then(data => {{
    weatherLayer = L.geoJSON(data, {{
      pointToLayer: (f, ll) => {{
        const p = f.properties;
        const hasData = p.has_data;

        let popup = `<b>Weather Point #${{p.index}}</b><br>`;
        if (hasData) {{
          popup += `Wind: ${{p.wind_speed}} m/s @ ${{p.wind_dir}}°<br>`;
          popup += `Temp: ${{p.temp}}°C<br>`;
          popup += `Pressure: ${{p.pressure}} hPa<br>`;
          popup += `Humidity: ${{p.humidity}}%<br>`;
          popup += `${{p.description || ''}}`;
        }} else {{
          popup += '<em>No data - generate weather first</em>';
        }}

        return L.marker(ll, {{
          icon: L.divIcon({{
            className: hasData ? 'weather-point' : 'weather-point weather-point-nodata',
            iconSize: [12, 12]
          }})
        }}).bindPopup(popup);
      }}
    }}).addTo(map);

    // Update stats
    const count = data.features?.length || 0;
    document.getElementById('stats').innerHTML += `<br>Weather: ${{count}} points`;
  }});

// Izobaty
fetch('/api/v1/routes_mesh/{meshed_area_id}/contours?levels=2,5,10,20')
  .then(r => r.json())
  .then(data => {{
    bathyLayer = L.layerGroup();

    if (data.lines) {{
      L.geoJSON(data.lines, {{
        style: {{ color: '#0055cc', weight: 1, opacity: 0.7 }}
      }}).addTo(bathyLayer);
    }}

    if (data.labels) {{
      L.geoJSON(data.labels, {{
        pointToLayer: (f, ll) => L.marker(ll, {{
          icon: L.divIcon({{
            html: `<div style="background:white;padding:2px;border:1px solid #0055cc;font-size:10px">${{f.properties.text}}m</div>`,
            iconSize: [30, 15]
          }})
        }})
      }}).addTo(bathyLayer);
    }}
  }}).catch(() => {{}});

// Toggle controls
document.getElementById('toggle-mesh').onchange = e => {{
  if (e.target.checked) map.addLayer(meshLayer);
  else map.removeLayer(meshLayer);
}};

document.getElementById('toggle-weather').onchange = e => {{
  if (e.target.checked && weatherLayer) map.addLayer(weatherLayer);
  else if (weatherLayer) map.removeLayer(weatherLayer);
}};

document.getElementById('toggle-bathymetry').onchange = e => {{
  if (e.target.checked && bathyLayer) map.addLayer(bathyLayer);
  else if (bathyLayer) map.removeLayer(bathyLayer);
}};
</script>
</body>
</html>
    """
    return HTMLResponse(content=html)