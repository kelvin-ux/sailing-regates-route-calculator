# -*- coding: utf-8 -*-
from fastapi.responses import HTMLResponse
from pydantic import UUID4
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import APIRouter, Depends, HTTPException
from app.core.database import get_db as get_async_session
from app.services.db.services import MeshedAreaService
from sqlalchemy import select
from app.models.models import RouteSegments, RoutePoint
import json

router = APIRouter()


@router.get("/{meshed_area_id}/route/view",
            response_class=HTMLResponse,
            description="Interactive map view of calculated sailing route")
async def view_calculated_route(
        meshed_area_id: UUID4,
        session: AsyncSession = Depends(get_async_session)
):
    mesh_svc = MeshedAreaService(session)
    meshed = await mesh_svc.get_entity_by_id(meshed_area_id, allow_none=False)

    if not meshed:
        return HTMLResponse(
            content=f"<h1>Error 404</h1><p>Meshed area {meshed_area_id} not found</p>",
            status_code=404,
            media_type="text/html; charset=utf-8"
        )

    # Pobierz zoptymalizowane segmenty z bazy danych
    segments_query = (
        select(RouteSegments)
        .where(RouteSegments.route_id == meshed.route_id)
        .order_by(RouteSegments.segment_order)
    )

    result = await session.execute(segments_query)
    db_segments = result.scalars().all()

    # Przygotuj dane segmentów do wyświetlenia
    segments_data = []
    for seg in db_segments:
        # Pobierz punkty początkowy i końcowy
        from_point = await session.get(RoutePoint, seg.from_point)
        to_point = await session.get(RoutePoint, seg.to_point)

        if from_point and to_point:
            segments_data.append({
                'order': seg.segment_order,
                'from': {'lat': from_point.y, 'lon': from_point.x},
                'to': {'lat': to_point.y, 'lon': to_point.x},
                'distance_nm': seg.distance_nm,
                'bearing': seg.bearing,
                'estimated_time_hours': seg.estimated_time / 60.0 if seg.estimated_time else 0,
                'recommended_course': seg.recommended_course,
                'wind_angle': seg.wind_angle,
                'sail_type': seg.sail_type,
                'tack_type': seg.tack_type,
                'maneuver_type': seg.maneuver_type,
                'boat_speed_knots': (seg.distance_nm / (
                            seg.estimated_time / 60.0)) if seg.estimated_time and seg.estimated_time > 0 else 0
            })

    # Jeśli nie ma segmentów w bazie, użyj danych z calculated_route_json
    if not segments_data and meshed.calculated_route_json:
        route_data = json.loads(meshed.calculated_route_json)
        # Fallback to raw segments
        if 'route' in route_data and 'segments' in route_data['route']:
            for idx, seg in enumerate(route_data['route']['segments']):
                segments_data.append({
                    'order': idx,
                    'from': {'lat': seg['from']['lat'], 'lon': seg['from']['lon']},
                    'to': {'lat': seg['to']['lat'], 'lon': seg['to']['lon']},
                    'distance_nm': seg['distance_nm'],
                    'bearing': seg['bearing'],
                    'estimated_time_hours': seg['time_seconds'] / 3600.0,
                    'wind_angle': seg.get('twa', 0),
                    'sail_type': 'unknown',
                    'tack_type': seg.get('point_of_sail', 'unknown'),
                    'maneuver_type': None,
                    'boat_speed_knots': seg.get('boat_speed_knots', 0)
                })

    # Przygotuj JSON dla JavaScript
    segments_json = json.dumps(segments_data)

    html = f"""<!DOCTYPE html>
<html lang="pl">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Optimized Route View - {meshed_area_id}</title>
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #1a1a1a;
            color: #e0e0e0;
        }}
        #map {{
            height: 100vh;
            width: 100%;
        }}
        .info-panel {{
            position: absolute;
            top: 10px;
            right: 10px;
            background: rgba(26, 26, 26, 0.95);
            padding: 20px;
            border-radius: 8px;
            max-width: 420px;
            max-height: 90vh;
            overflow-y: auto;
            z-index: 1000;
            box-shadow: 0 4px 12px rgba(0,0,0,0.5);
            border: 1px solid rgba(79, 195, 247, 0.3);
        }}
        .info-panel h2 {{
            color: #4fc3f7;
            margin-bottom: 15px;
            font-size: 18px;
            border-bottom: 2px solid #4fc3f7;
            padding-bottom: 8px;
        }}
        .info-panel h3 {{
            color: #81c784;
            margin-top: 15px;
            margin-bottom: 10px;
            font-size: 14px;
            text-transform: uppercase;
            letter-spacing: 1px;
        }}
        .stat {{
            display: flex;
            justify-content: space-between;
            margin: 8px 0;
            padding: 8px;
            background: rgba(255,255,255,0.05);
            border-radius: 4px;
            font-size: 13px;
        }}
        .stat-label {{
            color: #b0b0b0;
        }}
        .stat-value {{
            color: #ffffff;
            font-weight: 600;
        }}
        .segment-list {{
            max-height: 400px;
            overflow-y: auto;
            margin-top: 10px;
        }}
        .segment-item {{
            background: rgba(255,255,255,0.05);
            padding: 10px;
            margin: 6px 0;
            border-radius: 4px;
            cursor: pointer;
            transition: all 0.2s;
            border-left: 3px solid #666;
            font-size: 12px;
            position: relative;
        }}
        .segment-item:hover {{
            background: rgba(79, 195, 247, 0.2);
            transform: translateX(3px);
        }}
        .segment-item.selected {{
            background: rgba(79, 195, 247, 0.3);
            border-left-color: #81c784;
        }}
        .maneuver-badge {{
            position: absolute;
            top: 5px;
            right: 5px;
            padding: 2px 6px;
            border-radius: 3px;
            font-size: 10px;
            font-weight: 600;
            color: white;
            text-transform: uppercase;
        }}
        .maneuver-tack {{
            background: #9b59b6;
        }}
        .maneuver-jibe {{
            background: #1abc9c;
        }}
        .loading {{
            position: fixed;
            top: 50%;
            left: 50%;
            transform: translate(-50%, -50%);
            background: rgba(26, 26, 26, 0.95);
            padding: 30px;
            border-radius: 8px;
            text-align: center;
            z-index: 2000;
            border: 1px solid #4fc3f7;
        }}
        .loading-spinner {{
            border: 4px solid rgba(79, 195, 247, 0.3);
            border-top: 4px solid #4fc3f7;
            border-radius: 50%;
            width: 50px;
            height: 50px;
            animation: spin 1s linear infinite;
            margin: 0 auto 15px;
        }}
        @keyframes spin {{
            0% {{ transform: rotate(0deg); }}
            100% {{ transform: rotate(360deg); }}
        }}
        .legend-box {{
            position: absolute;
            bottom: 20px;
            left: 10px;
            background: rgba(26, 26, 26, 0.95);
            padding: 15px;
            border-radius: 8px;
            z-index: 1000;
            max-width: 300px;
            font-size: 12px;
            border: 1px solid rgba(79, 195, 247, 0.3);
        }}
        .legend-title {{
            color: #4fc3f7;
            font-weight: 600;
            margin-bottom: 8px;
            font-size: 13px;
        }}
    </style>
</head>
<body>
    <div id="map"></div>
    <div class="legend-box">
        <div class="legend-title">Optimized Segments</div>
        <div style="color: #aaa; font-size: 11px; margin-top: 8px;">
            Segments: {len(segments_data)}<br>
            Total Distance: {sum(s['distance_nm'] for s in segments_data):.1f} nm<br>
            Total Time: {sum(s['estimated_time_hours'] for s in segments_data):.1f} h
        </div>
    </div>
    <div class="info-panel" id="infoPanel">
        <h2>Optimized Route Info</h2>
        <div id="routeStats"></div>
        <h3>Route Segments ({len(segments_data)})</h3>
        <div class="segment-list" id="segmentList"></div>
    </div>
    <div class="loading" id="loading">
        <div class="loading-spinner"></div>
        <div>Loading route data...</div>
    </div>
    <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
    <script>
        const MESHED_AREA_ID = '{meshed_area_id}';
        const SEGMENTS_DATA = {segments_json};

        let map;
        let segmentPolylines = [];
        let maneuverMarkers = [];
        let selectedSegmentIndex = null;

        const tackColors = {{
            'close-hauled': '#e74c3c',
            'close reach': '#e67e22',
            'beam reach': '#f39c12',
            'broad reach': '#27ae60',
            'running': '#3498db',
            'dead run': '#2980b9',
            'no-go zone': '#888888'
        }};

        function initMap() {{
            map = L.map('map').setView([54.5, 18.5], 10);
            L.tileLayer('https://{{s}}.basemaps.cartocdn.com/dark_all/{{z}}/{{x}}/{{y}}{{r}}.png', {{
                attribution: '&copy; OpenStreetMap, CartoDB',
                subdomains: 'abcd',
                maxZoom: 20
            }}).addTo(map);
        }}

        function displayRoute() {{
            if (!SEGMENTS_DATA || SEGMENTS_DATA.length === 0) {{
                document.getElementById('loading').innerHTML = '<div style="color: red;">No segment data available</div>';
                return;
            }}

            const bounds = L.latLngBounds();

            // Draw segments
            SEGMENTS_DATA.forEach((segment, idx) => {{
                const from = [segment.from.lat, segment.from.lon];
                const to = [segment.to.lat, segment.to.lon];

                bounds.extend(from);
                bounds.extend(to);

                const color = tackColors[segment.tack_type] || '#666';
                const polyline = L.polyline([from, to], {{
                    color: color,
                    weight: 4,
                    opacity: 0.8
                }}).addTo(map);

                polyline.on('click', () => selectSegment(idx));
                segmentPolylines.push(polyline);

                // Add maneuver marker if present
                if (segment.maneuver_type) {{
                    const markerColor = segment.maneuver_type === 'TACK' ? '#9b59b6' : '#1abc9c';
                    const marker = L.circleMarker(to, {{
                        radius: 8,
                        fillColor: markerColor,
                        color: '#fff',
                        weight: 3,
                        opacity: 1,
                        fillOpacity: 0.95
                    }}).addTo(map);

                    marker.bindPopup(`
                        <strong style="color: ${{markerColor}};">${{segment.maneuver_type}}</strong><br>
                        After segment #${{idx + 1}}<br>
                        Course change: ${{segment.bearing.toFixed(0)}}°
                    `);

                    maneuverMarkers.push(marker);
                }}
            }});

            // Add start and end markers
            if (SEGMENTS_DATA.length > 0) {{
                const start = [SEGMENTS_DATA[0].from.lat, SEGMENTS_DATA[0].from.lon];
                const end = [SEGMENTS_DATA[SEGMENTS_DATA.length - 1].to.lat, SEGMENTS_DATA[SEGMENTS_DATA.length - 1].to.lon];

                L.circleMarker(start, {{
                    radius: 10,
                    fillColor: '#4caf50',
                    color: '#000',
                    weight: 2,
                    opacity: 1,
                    fillOpacity: 0.9
                }}).addTo(map).bindPopup('<strong>START</strong>');

                L.circleMarker(end, {{
                    radius: 10,
                    fillColor: '#f44336',
                    color: '#000',
                    weight: 2,
                    opacity: 1,
                    fillOpacity: 0.9
                }}).addTo(map).bindPopup('<strong>FINISH</strong>');
            }}

            map.fitBounds(bounds, {{ padding: [50, 50] }});
            displayStats();
            displaySegments();
            document.getElementById('loading').style.display = 'none';
        }}

        function displayStats() {{
            const totalDistance = SEGMENTS_DATA.reduce((sum, s) => sum + s.distance_nm, 0);
            const totalTime = SEGMENTS_DATA.reduce((sum, s) => sum + s.estimated_time_hours, 0);
            const avgSpeed = totalDistance / totalTime;

            const tackCount = SEGMENTS_DATA.filter(s => s.maneuver_type === 'TACK').length;
            const jibeCount = SEGMENTS_DATA.filter(s => s.maneuver_type === 'JIBE').length;

            const html = `
                <div class="stat">
                    <span class="stat-label">Total Distance:</span>
                    <span class="stat-value">${{totalDistance.toFixed(2)}} nm</span>
                </div>
                <div class="stat">
                    <span class="stat-label">Total Time:</span>
                    <span class="stat-value">${{totalTime.toFixed(2)}} h</span>
                </div>
                <div class="stat">
                    <span class="stat-label">Avg Speed:</span>
                    <span class="stat-value">${{avgSpeed.toFixed(2)}} kt</span>
                </div>
                <div class="stat">
                    <span class="stat-label">Segments:</span>
                    <span class="stat-value">${{SEGMENTS_DATA.length}}</span>
                </div>
                <div class="stat">
                    <span class="stat-label">Tacks:</span>
                    <span class="stat-value">${{tackCount}}</span>
                </div>
                <div class="stat">
                    <span class="stat-label">Jibes:</span>
                    <span class="stat-value">${{jibeCount}}</span>
                </div>
            `;
            document.getElementById('routeStats').innerHTML = html;
        }}

        function displaySegments() {{
            const html = SEGMENTS_DATA.map((seg, idx) => {{
                const maneuverBadge = seg.maneuver_type ? 
                    `<span class="maneuver-badge maneuver-${{seg.maneuver_type.toLowerCase()}}">${{seg.maneuver_type}}</span>` : '';

                const color = tackColors[seg.tack_type] || '#666';

                return `
                    <div class="segment-item" onclick="selectSegment(${{idx}})" style="border-left-color: ${{color}};">
                        ${{maneuverBadge}}
                        <div style="margin-bottom: 6px;">
                            <strong style="font-size: 11px;">Segment #${{idx + 1}}</strong>
                        </div>
                        <div style="font-size: 11px; color: #b0b0b0; line-height: 1.4;">
                            Distance: ${{seg.distance_nm.toFixed(2)}} nm<br>
                            Time: ${{seg.estimated_time_hours.toFixed(2)}} h<br>
                            Course: ${{seg.bearing.toFixed(0)}}°<br>
                            Speed: ${{seg.boat_speed_knots.toFixed(1)}} kt<br>
                            Tack: ${{seg.tack_type}}<br>
                            Sail: ${{seg.sail_type || 'N/A'}}
                        </div>
                    </div>
                `;
            }}).join('');
            document.getElementById('segmentList').innerHTML = html;
        }}

        function selectSegment(idx) {{
            if (selectedSegmentIndex !== null) {{
                segmentPolylines[selectedSegmentIndex].setStyle({{ weight: 4, opacity: 0.8 }});
                document.querySelectorAll('.segment-item')[selectedSegmentIndex].classList.remove('selected');
            }}
            selectedSegmentIndex = idx;
            segmentPolylines[idx].setStyle({{ weight: 6, opacity: 1.0 }});
            document.querySelectorAll('.segment-item')[idx].classList.add('selected');
            const bounds = segmentPolylines[idx].getBounds();
            map.fitBounds(bounds, {{ padding: [100, 100] }});
        }}

        window.addEventListener('load', () => {{
            initMap();
            displayRoute();
        }});
    </script>
</body>
</html>
    """

    return HTMLResponse(content=html, media_type="text/html; charset=utf-8")