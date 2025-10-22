from __future__ import annotations

import json
import numpy as np
from pathlib import Path

from pydantic import UUID4
from pyproj import Transformer
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi import APIRouter
from fastapi import Depends
from fastapi import Query
from fastapi import HTTPException
from fastapi.responses import HTMLResponse
from fastapi.responses import JSONResponse

from app.core.database import get_db as get_async_session
from app.services.db.services import MeshedAreaService
from app.schemas.mesh import CreateRouteAndMeshIn
from app.schemas.mesh import CreateRouteAndMeshOut
from app.services.mesh.map_data import build_map_geojson
from app.services.mesh.mesh_builder import create_route_and_mesh
from app.services.geodata.bathymetry import _bbox_wgs84_from_local_wkt
from app.services.geodata.bathymetry import label_points_along_lines
from app.services.geodata.bathymetry import contours_geojson_from_tif
from app.services.geodata.bathymetry import fetch_wcs_geotiff
from app.services.geodata.bathymetry import WcsRequest

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
    from sqlalchemy import select
    from app.models.models import RoutePoint, WeatherForecast, RoutePointType
    from uuid import UUID
    from shapely import wkt
    from shapely.geometry import Point, LineString

    svc = MeshedAreaService(session)
    meshed = await svc.get_entity_by_id(meshed_area_id, allow_none=False)

    # Załaduj trasę dla określenia stref
    route_wkt_str = getattr(meshed, "route_wkt", None)
    route_geom = None
    if route_wkt_str:
        try:
            route_geom = wkt.loads(route_wkt_str)
        except Exception:
            pass

    if meshed.weather_points_json:
        weather_metadata = json.loads(meshed.weather_points_json)
        points = weather_metadata.get('points', [])

        features = []
        for p in points:
            props = {
                "index": p['idx'],
                "has_data": False,
                "route_point_id": p.get('route_point_id'),
            }

            # Określ strefę punktu
            point_geom = Point(p['x'], p['y'])
            zone = 'unknown'
            if route_geom and isinstance(route_geom, LineString):
                distance = route_geom.distance(point_geom)
                if distance <= 100:  # Na trasie lub bardzo blisko
                    zone = 'route'
                elif distance <= 500:
                    zone = 'near'
                elif distance <= 1500:
                    zone = 'mid'
                else:
                    zone = 'far'

            props['zone'] = zone

            # Pobierz najnowsze dane pogodowe dla tego punktu
            route_point_id_str = p.get('route_point_id')
            if route_point_id_str:
                try:
                    # Konwertuj string UUID na UUID
                    route_point_uuid = UUID(route_point_id_str) if isinstance(route_point_id_str,
                                                                              str) else route_point_id_str

                    query = (
                        select(WeatherForecast)
                        .where(WeatherForecast.route_point_id == route_point_uuid)
                        .order_by(WeatherForecast.forecast_timestamp.desc())
                        .limit(1)
                    )
                    result = await session.execute(query)
                    weather = result.scalar_one_or_none()

                    if weather:
                        props.update({
                            "has_data": True,
                            "wind_speed": float(weather.wind_speed) if weather.wind_speed is not None else 0.0,
                            "wind_direction": float(
                                weather.wind_direction) if weather.wind_direction is not None else 0.0,
                            "wind_gusts": float(weather.wind_gusts) if weather.wind_gusts is not None else 0.0,
                            "wave_height": float(weather.wave_height) if weather.wave_height is not None else 0.0,
                            "wave_direction": float(
                                weather.wave_direction) if weather.wave_direction is not None else 0.0,
                            "wave_period": float(weather.wave_period) if weather.wave_period is not None else 0.0,
                            "wind_wave_height": float(
                                weather.wind_wave_height) if weather.wind_wave_height is not None else 0.0,
                            "swell_wave_height": float(
                                weather.swell_wave_height) if weather.swell_wave_height is not None else 0.0,
                            "current_velocity": float(
                                weather.current_velocity) if weather.current_velocity is not None else 0.0,
                            "current_direction": float(
                                weather.current_direction) if weather.current_direction is not None else 0.0,
                            "temperature": float(weather.temperature) if weather.temperature is not None else 0.0,
                            "humidity": float(weather.humidity) if weather.humidity is not None else 0.0,
                            "pressure": float(weather.pressure) if weather.pressure is not None else 0.0,
                            "timestamp": weather.forecast_timestamp.isoformat() if weather.forecast_timestamp else None,
                        })
                except Exception as e:
                    print(f"Error fetching weather for point {p['idx']}: {e}")
                    import traceback
                    traceback.print_exc()

            features.append({
                "type": "Feature",
                "properties": props,
                "geometry": {
                    "type": "Point",
                    "coordinates": [p.get('lon', p['x']), p.get('lat', p['y'])]
                }
            })
    else:
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
                    "zone": "unknown",
                    "message": "No weather data. Use POST /api/v1/weather/{mesh_id}/fetch-weather to get data."
                },
                "geometry": {
                    "type": "Point",
                    "coordinates": [lon, lat]
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
    """Zwraca izobaty dla obszaru."""
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
        Map view
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
      border: 3px solid white;
      border-radius: 50%;
      width: 16px !important;
      height: 16px !important;
      cursor: pointer;
      transition: all 0.2s ease;
      box-shadow: 0 0 8px rgba(255, 51, 51, 0.4);
    }}

    .weather-point-route {{
      width: 14px !important;
      height: 14px !important;
      background: radial-gradient(circle, #ff8888, #ff4444);
    }}

    .weather-point-near {{
      width: 16px !important;
      height: 16px !important;
      background: radial-gradient(circle, #ff6b6b, #ff3333);
    }}

    .weather-point-mid {{
      width: 13px !important;
      height: 13px !important;
      background: radial-gradient(circle, #ff9999, #ff5555);
      opacity: 0.9;
    }}

    .weather-point-far {{
      width: 10px !important;
      height: 10px !important;
      background: radial-gradient(circle, #ffaaaa, #ff6666);
      opacity: 0.8;
    }}

    .weather-point:hover {{
      width: 20px !important;
      height: 20px !important;
      border: 4px solid white;
      box-shadow: 0 0 15px rgba(255, 51, 51, 0.8);
      transform: scale(1.1);
    }}

    .weather-point-nodata {{
      background: #999;
      opacity: 0.6;
      box-shadow: none;
    }}

    .weather-point-nodata:hover {{
      opacity: 0.9;
    }}

    .control-point {{
      background: #ffd700;
      border: 2px solid #000;
      border-radius: 50%;
      width: 14px !important;
      height: 14px !important;
      z-index: 900;
    }}

    .control-point-start {{
      background: #00ff00;
      border: 3px solid #006600;
      border-radius: 50%;
      width: 16px !important;
      height: 16px !important;
      z-index: 900;
      box-shadow: 0 0 10px rgba(0, 255, 0, 0.6);
    }}

    .control-point-stop {{
      background: #ff0000;
      border: 3px solid #660000;
      border-radius: 50%;
      width: 16px !important;
      height: 16px !important;
      z-index: 900;
      box-shadow: 0 0 10px rgba(255, 0, 0, 0.6);
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
      min-width: 250px;
      font-size: 13px;
      line-height: 1.5;
    }}

    .leaflet-popup-content strong {{
      color: #333;
      display: block;
      margin-top: 8px;
      margin-bottom: 2px;
      font-size: 14px;
      border-bottom: 1px solid #eee;
      padding-bottom: 2px;
    }}

    .leaflet-popup-content strong:first-child {{
      margin-top: 4px;
    }}

    .weather-popup .leaflet-popup-content-wrapper {{
      border-radius: 8px;
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
      pointToLayer: (f, ll) => {{
        const markerClass = f.properties?.marker_class || 'control-point';
        const pointType = f.properties?.point_type || 'control';

        let label = '';
        if (pointType === 'start' || pointType === 'START') {{
          label = 'START';
        }} else if (pointType === 'stop' || pointType === 'STOP') {{
          label = 'FINISH';
        }} else {{
          label = `CP ${{f.properties?.seq_idx || ''}}`;
        }}

        const marker = L.marker(ll, {{
          icon: L.divIcon({{
            className: markerClass,
            iconSize: markerClass.includes('start') || markerClass.includes('stop') ? [16, 16] : [14, 14],
            iconAnchor: markerClass.includes('start') || markerClass.includes('stop') ? [8, 8] : [7, 7]
          }})
        }});

        marker.bindPopup(`<b>${{label}}</b><br>Type: ${{pointType}}`);
        return marker;
      }}
    }}).addTo(map);

    // Dopasuj widok
    map.fitBounds(meshLayer.getBounds());

    // Statystyki
    const edges = data.features.find(f => f.properties?.type === 'mesh_wire')?.properties?.edges || 0;
    document.getElementById('stats').innerHTML = `Points: ${{edges}}`;
  }});

// Funkcja do załadowania punktów pogodowych
function loadWeatherPoints() {{
  console.log('Loading weather points for mesh:', MESH_ID);

  fetch(`/api/v1/routes_mesh/${{MESH_ID}}/weather-points`)
    .then(r => r.json())
    .then(data => {{
      console.log('Weather points data received:', data);

      if (weatherLayer) {{
        map.removeLayer(weatherLayer);
      }}

      weatherLayer = L.geoJSON(data, {{
        pointToLayer: (f, ll) => {{
          const p = f.properties;
          const hasData = p.has_data;
          const zone = p.zone || 'unknown';

          console.log(`Point #${{p.index}}: has_data=${{hasData}}, zone=${{zone}}`, p);

          let popup = `<b>Weather Point #${{p.index}}</b><br>`;
          popup += `<small style="color: #666;">Zone: ${{zone}}</small><br>`;
          popup += `<div style="max-height: 300px; overflow-y: auto;">`;

          if (hasData) {{
            popup += `<strong>Wind</strong><br>`;
            popup += `&nbsp;&nbsp;Speed: ${{p.wind_speed?.toFixed(1) || 'N/A'}} m/s<br>`;
            popup += `&nbsp;&nbsp;Direction: ${{p.wind_direction?.toFixed(0) || 'N/A'}}°<br>`;
            popup += `&nbsp;&nbsp;Gusts: ${{p.wind_gusts?.toFixed(1) || 'N/A'}} m/s<br>`;
            popup += `<br><strong>Waves</strong><br>`;
            popup += `&nbsp;&nbsp;Height: ${{p.wave_height?.toFixed(2) || 'N/A'}} m<br>`;
            popup += `&nbsp;&nbsp;Direction: ${{p.wave_direction?.toFixed(0) || 'N/A'}}°<br>`;
            popup += `&nbsp;&nbsp;Period: ${{p.wave_period?.toFixed(1) || 'N/A'}} s<br>`;
            popup += `&nbsp;&nbsp;Wind waves: ${{p.wind_wave_height?.toFixed(2) || 'N/A'}} m<br>`;
            popup += `&nbsp;&nbsp;Swell: ${{p.swell_wave_height?.toFixed(2) || 'N/A'}} m<br>`;
            popup += `<br><strong>Current</strong><br>`;
            popup += `&nbsp;&nbsp;Velocity: ${{p.current_velocity?.toFixed(2) || 'N/A'}} m/s<br>`;
            popup += `&nbsp;&nbsp;Direction: ${{p.current_direction?.toFixed(0) || 'N/A'}}°<br>`;
            popup += `<br><strong>Atmosphere</strong><br>`;
            popup += `&nbsp;&nbsp;Temp: ${{p.temperature?.toFixed(1) || 'N/A'}}°C<br>`;
            popup += `&nbsp;&nbsp;Humidity: ${{p.humidity?.toFixed(0) || 'N/A'}}%<br>`;
            popup += `&nbsp;&nbsp;Pressure: ${{p.pressure?.toFixed(1) || 'N/A'}} hPa<br>`;
            popup += `<br><small style="color: #666;">${{p.timestamp || 'N/A'}}</small>`;
          }} else {{
            popup += '<em style="color: #999;">No weather data available</em><br>';
            popup += '<small>Click "Fetch Weather Data" button to get data</small>';
          }}

          popup += `</div>`;

          // Wybierz klasę CSS w zależności od strefy i dostępności danych
          let markerClass = 'weather-point';
          if (!hasData) {{
            markerClass += ' weather-point-nodata';
          }} else {{
            if (zone === 'route') {{
              markerClass += ' weather-point-route';
            }} else if (zone === 'near') {{
              markerClass += ' weather-point-near';
            }} else if (zone === 'mid') {{
              markerClass += ' weather-point-mid';
            }} else if (zone === 'far') {{
              markerClass += ' weather-point-far';
            }}
          }}

          // Rozmiar zależy od strefy
          let iconSize = 16;
          if (zone === 'route') iconSize = 14;
          else if (zone === 'near') iconSize = 16;
          else if (zone === 'mid') iconSize = 13;
          else if (zone === 'far') iconSize = 10;

          const marker = L.marker(ll, {{
            icon: L.divIcon({{
              className: markerClass,
              iconSize: [iconSize, iconSize],
              iconAnchor: [iconSize/2, iconSize/2]
            }})
          }});

          marker.bindPopup(popup, {{
            maxWidth: 300,
            className: 'weather-popup'
          }});

          // Dodaj event listener na kliknięcie - automatyczne otwieranie popupu
          marker.on('click', function(e) {{
            marker.openPopup();
          }});

          return marker;
        }}
      }}).addTo(map);

      const count = data.features?.length || 0;
      const hasData = data.features?.filter(f => f.properties.has_data).length || 0;
      console.log(`Weather points loaded: ${{count}} total, ${{hasData}} with data`);

      document.getElementById('stats').innerHTML += `<br>Weather: ${{count}} points (${{hasData}} with data)`;
    }})
    .catch(err => {{
      console.error('Error loading weather points:', err);
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
        ✓ Success!<br>
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
    statusDiv.innerHTML = `<small style="color: red;">✗ Error: ${{error.message}}</small>`;
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