from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
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

@router.get("/mesh/{mesh_id}/view", response_class=HTMLResponse, include_in_schema=True)
async def view_mesh(mesh_id: UUID4):
    html = r"""<!doctype html>
<html>
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>Mesh preview</title>
  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
  <style>
    html, body, #map { height: 100%; margin: 0; }
    .legend { position:absolute; top:10px; right:10px; background:#fff; padding:8px 10px; border-radius:10px; box-shadow:0 2px 8px rgba(0,0,0,.15); z-index:1000; font:14px/1.2 system-ui, sans-serif; }
    .legend h4 { margin:0 0 6px 0; font-size:14px; }
    .legend label { display:block; margin:4px 0; white-space:nowrap; }
    #err { position:absolute; left:10px; bottom:10px; background:#fff3f3; color:#900; padding:8px 10px; border-radius:8px; box-shadow:0 2px 6px rgba(0,0,0,.1); display:none; }
  </style>
</head>
<body>
  <div id="map"></div>
  <div class="legend">
    <h4>Warstwy</h4>
    <label><input type="checkbox" id="chkMesh" checked> Mesh</label>
    <label><input type="checkbox" id="chkWater" checked> Korytarz</label>
    <label><input type="checkbox" id="chkRoute" checked> Trasa</label>
    <label><input type="checkbox" id="chkPts" checked> Punkty</label>
  </div>
  <div id="err"></div>

  <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
  <script>
    const map = L.map('map', { preferCanvas: true });
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', { maxZoom: 19, attribution: '&copy; OpenStreetMap contributors' }).addTo(map);
    map.setView([54.45, 18.70], 9);

    const url = new URL(window.location.pathname.replace('/view','/map'), window.location.origin).toString();
    const showErr = (msg) => { const el = document.getElementById('err'); el.textContent = msg; el.style.display = 'block'; console.error(msg); };

    fetch(url).then(r => { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); }).then(fc => {
      if (!fc || !fc.features) throw new Error('Brak danych GeoJSON');

      const mesh = L.geoJSON(fc, { filter: f => f.properties?.type === 'mesh_wire', style: { color: '#555', weight: 0.6, opacity: 0.8 } });
      const water = L.geoJSON(fc, { filter: f => f.properties?.type === 'water_corridor', style: { color: '#3388ff', weight: 1, fillOpacity: 0.05 } });
      const route = L.geoJSON(fc, { filter: f => f.properties?.type === 'route', style: { color: '#ff3b30', weight: 3 } });
      const points = L.geoJSON(fc, { filter: f => f.properties?.type === 'control_point', pointToLayer: (f, latlng) => L.circleMarker(latlng, { radius: 6, weight: 2, fillOpacity: 0.9 }) });

      const toggles = { chkMesh: mesh, chkWater: water, chkRoute: route, chkPts: points };
      for (const id in toggles) { const el = document.getElementById(id); if (el.checked) toggles[id].addTo(map); el.addEventListener('change', e => e.target.checked ? toggles[id].addTo(map) : map.removeLayer(toggles[id])); }

      const layers = [mesh, water, route, points].filter(l => l.getLayers().length);
      if (layers.length) { const b = L.featureGroup(layers).getBounds(); if (b.isValid()) map.fitBounds(b, { padding: [20, 20] }); }
      else showErr('Brak rozpoznanych warstw (mesh/korytarz/trasa/punkty)');
    }).catch(err => showErr('Błąd wczytywania danych: ' + err.message));

    map.on('tileerror', e => showErr('Tile error: ' + (e && e.error ? e.error.message : 'unknown')));
  </script>
</body>
</html>"""
    return HTMLResponse(html)
