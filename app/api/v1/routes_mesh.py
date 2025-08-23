from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import UUID4
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db as get_async_session
from app.schemas.mesh import CreateRouteAndMeshIn, CreateRouteAndMeshOut
from app.services.mesh.mesh_builder import create_route_and_mesh
from app.services.mesh.map_data import build_map_geojson

router = APIRouter()


@router.post("/mesh", response_model=CreateRouteAndMeshOut, status_code=201)
async def create_route_and_mesh_ep(payload: CreateRouteAndMeshIn, session: AsyncSession = Depends(get_async_session)):
    try:
        return await create_route_and_mesh(session, payload)
    except Exception as e:
        raise HTTPException(400, str(e))

@router.get("/mesh/{mesh_id}/map")
async def mesh_map_ep(mesh_id: UUID4, session: AsyncSession = Depends(get_async_session)):
    return await build_map_geojson(session, mesh_id)

@router.get("/{meshed_area_id}/map")
async def get_map_geojson(meshed_area_id: UUID4, session: AsyncSession = Depends(get_async_session)):
    data = await build_map_geojson(session, meshed_area_id)
    return JSONResponse(data)

@router.get("/{meshed_area_id}/view", response_class=HTMLResponse)
async def view_mesh(meshed_area_id: UUID4, mode: Literal["full", "points", "nodes"] = "nodes"):
    """
    mode=nodes  -> TYLKO węzły triangulacji
    mode=points -> TYLKO punkty kontrolne
    mode=full   -> wszystko (route + mesh_wire + control_point)
    """
    html = f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <title>Mesh view</title>
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <link rel="stylesheet"
    href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"
    integrity="sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY="
    crossorigin=""/>
  <style>
    html, body, #map {{ height: 100%; margin: 0; background: #fff; }}
    .legend {{ position:absolute; top:10px; left:10px; z-index:1000;
               background:#fff; padding:6px 8px; border-radius:4px;
               box-shadow:0 1px 4px rgba(0,0,0,.25); font:12px/1.2 Arial; }}
  </style>
</head>
<body>
<div id="map"></div>
<div class="legend">
  Tryb: <b>{mode}</b> —
  <a href="?mode=nodes">nodes</a> |
  <a href="?mode=points">points</a> |
  <a href="?mode=full">full</a>
</div>

<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"
 integrity="sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo=" crossorigin=""></script>
<script>
const MODE = "{mode}";
const MAP_URL = "/api/v1/routes_mesh/{meshed_area_id}/map";

const map = L.map('map');
L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{
  maxZoom: 18,
  attribution: '&copy; OpenStreetMap contributors'
}}).addTo(map);

fetch(MAP_URL).then(r => r.json()).then(fc => {{
  const bounds = [];
  const ctrlPts = [];
  let routeDrawn = false;

  (fc.features || []).forEach(f => {{
    const t = f.properties && f.properties.type;

    // --- MODE: nodes ---
    if (MODE === 'nodes') {{
      if (t === 'mesh_nodes' && f.geometry?.type === 'MultiPoint') {{
        const coords = f.geometry.coordinates || [];
        coords.forEach(([lon, lat]) => {{
          const m = L.circleMarker([lat, lon], {{
            radius: 1,
            weight: 0.5,
            color: '#828ba1',
            fillColor: '#828ba1',
            fillOpacity: 0.6
          }}).addTo(map);
          bounds.push([lat, lon]);
        }});
      }}
      return;
    }}

    // --- MODE: points (TYLKO punkty kontrolne) ---
    if (MODE === 'points') {{
      if (t === 'control_point' && f.geometry?.type === 'Point') {{
        const [lon, lat] = f.geometry.coordinates;
        L.circleMarker([lat, lon], {{
          radius: 3, weight: 1,
          color: '#D21F3C', fillColor: '#D21F3C', fillOpacity: 1
        }}).addTo(map);
        bounds.push([lat, lon]);
      }}
      return;
    }}

    // --- MODE: full ---
    if (t === 'control_point' && f.geometry?.type === 'Point') {{
      const [lon, lat] = f.geometry.coordinates;
      ctrlPts.push([lat, lon]);
      L.circleMarker([lat, lon], {{
        radius: 3, weight: 1,
        color: '#D21F3C', fillColor: '#D21F3C', fillOpacity: 1
      }}).addTo(map);
      bounds.push([lat, lon]);
      return;
    }}

    if (t === 'route' && f.geometry?.type === 'LineString') {{
      const ll = f.geometry.coordinates.map(([lon, lat]) => [lat, lon]);
      L.polyline(ll, {{ weight: 2, color: '#000' }}).addTo(map);
      ll.forEach(p => bounds.push(p));
      routeDrawn = true;
      return;
    }}

    if (t === 'mesh_wire' && f.geometry?.type === 'MultiLineString') {{
      const lines = f.geometry.coordinates.map(seg => seg.map(([lon, lat]) => [lat, lon]));
      L.polyline(lines, {{ weight: 0.5, opacity: 0.35, color: '#000' }}).addTo(map);
      lines.flat().forEach(p => bounds.push(p));
      return;
    }}
  }});

  if (MODE === 'full' && !routeDrawn && ctrlPts.length >= 2) {{
    L.polyline(ctrlPts, {{ weight: 3, dashArray: '6,4', color: '#000' }}).addTo(map);
    ctrlPts.forEach(p => bounds.push(p));
  }}

  if (bounds.length) {{
    map.fitBounds(bounds, {{ padding: [20,20] }});
  }} else {{
    map.setView([54.5, 18.7], 9);
  }}
}}).catch(err => {{
  console.error("map fetch error", err);
  map.setView([54.5, 18.7], 9);
}});
</script>
</body>
</html>"""
    return HTMLResponse(html)

@router.get("/{meshed_area_id}/view/points", response_class=HTMLResponse)
async def view_mesh_points(meshed_area_id: UUID4):
    return await view_mesh(meshed_area_id, mode="points")

@router.get("/{meshed_area_id}/view/nodes", response_class=HTMLResponse)
async def view_mesh_nodes(meshed_area_id: UUID4):
    return await view_mesh(meshed_area_id, mode="nodes")

