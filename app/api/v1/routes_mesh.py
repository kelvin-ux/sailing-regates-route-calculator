from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import UUID4
from pyproj import Transformer
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
      "yacht_id": "3fa85f64-5717-4562-b3fc-2c963f66afa7",
      "points": [
        {
          "lat": 54.520,
          "lon": 18.550,
          "timestamp": null
        },
        {
          "lat": 54.400,
          "lon": 18.700,
          "timestamp": null
        },
        {
          "lat": 54.350,
          "lon": 18.900,
          "timestamp": null
        }
      ],
      "corridor_nm": 3.0,
      "ring1_m": 500,
      "ring2_m": 1500,
      "ring3_m": 3000,
      "area1": 3000,
      "area2": 15000,
      "area3": 60000,
      "shoreline_avoid_m": 300,
      "enable_weather_optimization": true,
      "max_weather_points": 40,
      "weather_grid_km": 5.0,
      "weather_clustering_method": "kmeans"
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

    UWAGA: Ten endpoint pokazuje punkty pogodowe z danymi lub bez.
    Aby pobrać aktualne dane pogodowe, użyj:
    POST /api/v1/weather/{meshed_area_id}/fetch-weather
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
                    "has_data": False,
                    "message": "No weather data. Use POST /api/v1/weather/{mesh_id}/fetch-weather to get data."
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
                    "wind_direction": data.get("wind_direction"),
                    "wind_gusts": data.get("wind_gusts"),
                    "wave_height": data.get("wave_height"),
                    "wave_direction": data.get("wave_direction"),
                    "wave_period": data.get("wave_period"),
                    "wind_wave_height": data.get("wind_wave_height"),
                    "swell_wave_height": data.get("swell_wave_height"),
                    "current_velocity": data.get("current_velocity"),
                    "current_direction": data.get("current_direction"),
                    "temperature": data.get("temperature"),
                    "humidity": data.get("humidity"),
                    "pressure": data.get("pressure"),
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
    """
    Interactive map viewer for mesh with weather data.

    Shows:
    - Navigation mesh
    - Route and control points
    - Weather points (if data fetched)
    - Bathymetry contours
    """
    html = f"""
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8" />
  <title>Route Mesh Viewer with Weather</title>
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
      max-width: 300px;
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

    .fetch-weather-btn {{
      background: #4CAF50;
      color: white;
      border: none;
      padding: 8px 16px;
      border-radius: 4px;
      cursor: pointer;
      margin-top: 10px;
      width: 100%;
    }}

    .fetch-weather-btn:hover {{
      background: #45a049;
    }}

    .fetch-weather-btn:disabled {{
      background: #cccccc;
      cursor: not-allowed;
    }}

    .leaflet-popup-content {{
      min-width: 220px;
      font-size: 13px;
    }}

    .leaflet-popup-content strong {{
      color: #333;
      display: block;
      margin-top: 8px;
      margin-bottom: 2px;
    }}
  </style>
</head>
<body>
<div id="map"></div>
<div class="info-box">
  <h4>Mesh Info</h4>
  <div id="stats">Loading...</div>
  <button id="fetch-weather-btn" class="fetch-weather-btn">Fetch Weather Data</button>
  <div id="weather-status"></div>
  <hr>
  <label><input type="checkbox" id="toggle-mesh" checked> Mesh</label><br>
  <label><input type="checkbox" id="toggle-weather" checked> Weather</label><br>
  <label><input type="checkbox" id="toggle-bathymetry"> Bathymetry</label>
</div>

<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script>
const MESH_ID = '{meshed_area_id}';
const map = L.map('map').setView([54.5, 18.8], 10);

L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{
  maxZoom: 19,
  attribution: '© OpenStreetMap'
}}).addTo(map);

let meshLayer, weatherLayer, bathyLayer;

// Załaduj dane mesh
fetch(`/api/v1/routes_mesh/${{MESH_ID}}/map`)
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

// Funkcja do załadowania punktów pogodowych
function loadWeatherPoints() {{
  fetch(`/api/v1/routes_mesh/${{MESH_ID}}/weather-points`)
    .then(r => r.json())
    .then(data => {{
      if (weatherLayer) {{
        map.removeLayer(weatherLayer);
      }}

      weatherLayer = L.geoJSON(data, {{
        pointToLayer: (f, ll) => {{
          const p = f.properties;
          const hasData = p.has_data;

          let popup = `<b>Weather Point #${{p.index}}</b><br>`;
          if (hasData) {{
            popup += ` <strong>Wind</strong><br>`;
            popup += `  -Speed: ${{p.wind_speed?.toFixed(1)}} m/s<br>`;
            popup += `  -Direction: ${{p.wind_direction?.toFixed(0)}}°<br>`;
            popup += `  -Gusts: ${{p.wind_gusts?.toFixed(1)}} m/s<br>`;
            popup += ` <strong>Waves</strong><br>`;
            popup += `  -Height: ${{p.wave_height?.toFixed(2)}} m<br>`;
            popup += `  -Direction: ${{p.wave_direction?.toFixed(0)}}°<br>`;
            popup += `  -Period: ${{p.wave_period?.toFixed(1)}} s<br>`;
            popup += `  -Wind waves: ${{p.wind_wave_height?.toFixed(2)}} m<br>`;
            popup += `  -Swell: ${{p.swell_wave_height?.toFixed(2)}} m<br>`;
            popup += ` <strong>Current</strong><br>`;
            popup += `  -Velocity: ${{p.current_velocity?.toFixed(2)}} m/s<br>`;
            popup += `  -Direction: ${{p.current_direction?.toFixed(0)}}°<br>`;
            popup += ` <strong>Atmosphere</strong><br>`;
            popup += `  -Temp: ${{p.temperature?.toFixed(1)}}°C<br>`;
            popup += `  -Humidity: ${{p.humidity?.toFixed(0)}}%<br>`;
            popup += `  -Pressure: ${{p.pressure?.toFixed(1)}} hPa<br>`;
            popup += `<br><small>${{p.timestamp || 'N/A'}}</small>`;
          }} else {{
            popup += '<em>${{"No weather data"}}</em>';
          }}

          return L.marker(ll, {{
            icon: L.divIcon({{
              className: hasData ? 'weather-point' : 'weather-point weather-point-nodata',
              iconSize: [12, 12]
            }})
          }}).bindPopup(popup);
        }}
      }}).addTo(map);

      const count = data.features?.length || 0;
      const hasData = data.features?.some(f => f.properties.has_data);
      document.getElementById('stats').innerHTML += `<br>Weather: ${{count}} points ${{hasData ? '(with data)' : '(no data)'}}`;
    }});
}}

// Inicjalne załadowanie punktów pogodowych
loadWeatherPoints();

// Fetch weather button
document.getElementById('fetch-weather-btn').addEventListener('click', async function() {{
  const btn = this;
  const statusDiv = document.getElementById('weather-status');

  btn.disabled = true;
  btn.textContent = 'Fetching Weather...';
  statusDiv.innerHTML = '<small style="color: blue;">⏳ Fetching from Open-Meteo API...</small>';

  try {{
    const response = await fetch(`/api/v1/weather/${{MESH_ID}}/fetch-weather`, {{
      method: 'POST'
    }});

    if (!response.ok) {{
      throw new Error(`HTTP error! status: ${{response.status}}`);
    }}

    const result = await response.json();

    statusDiv.innerHTML = `
      <small style="color: green;">
        Success!<br>
        Points: ${{result.total_points}}<br>
        Successful: ${{result.successful}}<br>
        Cache hits: ${{result.cache_hits}}<br>
        API calls: ${{result.api_calls}}
      </small>
    `;

    // Przeładuj punkty pogodowe
    loadWeatherPoints();

  }} catch (error) {{
    console.error('Error fetching weather:', error);
    statusDiv.innerHTML = `<small style="color: red;"> Error: ${{error.message}}</small>`;
  }} finally {{
    btn.disabled = false;
    btn.textContent = 'Fetch Weather Data';
  }}
}});

// Izobaty
fetch(`/api/v1/routes_mesh/${{MESH_ID}}/contours?levels=2,5,10,20`)
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