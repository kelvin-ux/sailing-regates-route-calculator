# -*- coding: utf-8 -*-
from fastapi.responses import HTMLResponse
from pydantic import UUID4
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import APIRouter, Depends, HTTPException
from app.core.database import get_db as get_async_session
from app.services.db.services import MeshedAreaService

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

    route_api_url = f"/api/v1/routing/{meshed_area_id}/calculated-route"

    html = f"""<!DOCTYPE html>
<html lang="pl">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Route View - {meshed_area_id}</title>
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
        .legend {{
            background: rgba(255,255,255,0.05);
            padding: 12px;
            border-radius: 4px;
            margin: 15px 0;
            border: 1px solid rgba(255,255,255,0.1);
            font-size: 12px;
        }}
        .legend-item {{
            display: flex;
            align-items: center;
            margin: 6px 0;
        }}
        .legend-color {{
            width: 16px;
            height: 16px;
            border-radius: 3px;
            margin-right: 8px;
            border: 1px solid rgba(255,255,255,0.3);
        }}
        .legend-text {{
            font-size: 11px;
        }}
        .tack-legend {{
            background: rgba(255,255,255,0.03);
            padding: 10px;
            border-radius: 4px;
            margin: 10px 0;
            font-size: 11px;
        }}
        .segment-list {{
            max-height: 350px;
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
        }}
        .segment-item:hover {{
            background: rgba(79, 195, 247, 0.2);
            transform: translateX(3px);
        }}
        .segment-item.selected {{
            background: rgba(79, 195, 247, 0.3);
            border-left-color: #81c784;
        }}
        .segment-pos {{
            display: inline-block;
            padding: 2px 6px;
            border-radius: 3px;
            font-size: 10px;
            font-weight: 600;
            margin-right: 8px;
            color: white;
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
        .error {{
            background: rgba(244, 67, 54, 0.9);
            color: white;
            padding: 15px;
            border-radius: 4px;
            margin: 10px;
            font-size: 13px;
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
        .info-panel::-webkit-scrollbar,
        .segment-list::-webkit-scrollbar {{
            width: 6px;
        }}
        .info-panel::-webkit-scrollbar-track,
        .segment-list::-webkit-scrollbar-track {{
            background: rgba(255,255,255,0.05);
        }}
        .info-panel::-webkit-scrollbar-thumb,
        .segment-list::-webkit-scrollbar-thumb {{
            background: #4fc3f7;
            border-radius: 3px;
        }}
    </style>
</head>
<body>
    <div id="map"></div>
    <div class="legend-box">
        <div class="legend-title">Hals (Punkt zeglugi)</div>
        <div class="legend">
            <div class="legend-item">
                <div class="legend-color" style="background: #e74c3c;"></div>
                <div class="legend-text">Baksztag 110-160°</div>
            </div>
            <div class="legend-item">
                <div class="legend-color" style="background: #e67e22;"></div>
                <div class="legend-text">Polbaksztag 80-110°</div>
            </div>
            <div class="legend-item">
                <div class="legend-color" style="background: #f39c12;"></div>
                <div class="legend-text">Polwiatr 70-110°</div>
            </div>
            <div class="legend-item">
                <div class="legend-color" style="background: #27ae60;"></div>
                <div class="legend-text">Bajdewind 30-70°</div>
            </div>
            <div class="legend-item">
                <div class="legend-color" style="background: #3498db;"></div>
                <div class="legend-text">Kurs pelny 160-180°</div>
            </div>
            <div class="legend-item">
                <div class="legend-color" style="background: #888888;"></div>
                <div class="legend-text">Dead Zone 0-30°</div>
            </div>
        </div>
        <div class="legend-title" style="margin-top: 12px;">Zwroty</div>
        <div class="tack-legend">
            <div class="legend-item">
                <div class="legend-color" style="background: #9b59b6;"></div>
                <div class="legend-text">¬† Tack (gora 0°)</div>
            </div>
            <div class="legend-item">
                <div class="legend-color" style="background: #1abc9c;"></div>
                <div class="legend-text">¬‡ Jibe (dolem 180°)</div>
            </div>
        </div>
    </div>
    <div class="info-panel" id="infoPanel">
        <h2>Informacje o trasie</h2>
        <div id="routeStats"></div>
        <h3>Segmenty trasy</h3>
        <div class="segment-list" id="segmentList"></div>
    </div>
    <div class="loading" id="loading">
        <div class="loading-spinner"></div>
        <div>Wczytywanie danych trasy...</div>
    </div>
    <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
    <script>
        const MESHED_AREA_ID = '{meshed_area_id}';
        const ROUTE_API_URL = '{route_api_url}';

        let map;
        let routeLayer;
        let waypointMarkers = [];
        let segmentPolylines = [];
        let tackMarkers = [];
        let selectedSegmentIndex = null;

        const posColors = {{
            'dead-zone': '#888888',
            'close-hauled': '#e74c3c',
            'close-reach': '#e67e22',
            'beam-reach': '#f39c12',
            'broad-reach': '#27ae60',
            'running': '#3498db'
        }};

        function classifyHals(twa) {{
            const absTWA = Math.abs(twa);
            if (absTWA <= 30) return 'dead-zone';
            if (absTWA <= 70) return 'broad-reach';
            if (absTWA <= 110) return 'beam-reach';
            if (absTWA <= 160) return 'close-hauled';
            return 'running';
        }}

        function getPosEnglish(hals) {{
            const map = {{
                'dead-zone': 'dead-zone',
                'broad-reach': 'broad-reach',
                'beam-reach': 'beam-reach',
                'close-hauled': 'close-hauled',
                'running': 'running'
            }};
            return map[hals] || 'beam-reach';
        }}

        function getHalsPolish(hals) {{
            const map = {{
                'dead-zone': 'Dead Zone',
                'broad-reach': 'Bajdewind',
                'beam-reach': 'Polwiatr',
                'close-hauled': 'Baksztag',
                'running': 'Kurs pelny'
            }};
            return map[hals] || hals;
        }}

        function initMap() {{
            map = L.map('map').setView([54.5, 18.5], 10);
            L.tileLayer('https://{{s}}.basemaps.cartocdn.com/dark_all/{{z}}/{{x}}/{{y}}{{r}}.png', {{
                attribution: '&copy; OpenStreetMap, CartoDB',
                subdomains: 'abcd',
                maxZoom: 20
            }}).addTo(map);
        }}

        async function loadRoute() {{
            try {{
                const response = await fetch(ROUTE_API_URL);
                if (!response.ok) throw new Error(`HTTP ${{response.status}}`);
                const result = await response.json();
                const routeData = result.data;
                displayRoute(routeData);
                displayStats(routeData);
                displaySegments(routeData);
                document.getElementById('loading').style.display = 'none';
            }} catch (error) {{
                console.error('Error:', error);
                document.getElementById('loading').innerHTML = `<div class="error"><strong>Blad wczytywania trasy</strong><br>${{error.message}}</div>`;
            }}
        }}

        function displayRoute(routeData) {{
            const waypoints = routeData.route.waypoints_wgs84;
            const segments = routeData.route.segments;
            if (!waypoints || waypoints.length === 0) return;

            const latLngs = waypoints.map(wp => [wp[1], wp[0]]);
            routeLayer = L.polyline(latLngs, {{
                color: '#666',
                weight: 2,
                opacity: 0.3,
                dashArray: '5, 5'
            }}).addTo(map);

            segments.forEach((segment, idx) => {{
                const from = [segment.from.lat, segment.from.lon];
                const to = [segment.to.lat, segment.to.lon];
                const hals = classifyHals(segment.twa);
                const color = posColors[getPosEnglish(hals)];
                const polyline = L.polyline([from, to], {{
                    color: color,
                    weight: 4,
                    opacity: 0.8
                }}).addTo(map);
                polyline.on('click', () => selectSegment(idx));
                segmentPolylines.push(polyline);
            }});

            waypoints.forEach((wp, idx) => {{
                const color = idx === 0 ? '#4caf50' : (idx === waypoints.length - 1 ? '#f44336' : '#fff');
                const marker = L.circleMarker([wp[1], wp[0]], {{
                    radius: 6,
                    fillColor: color,
                    color: '#000',
                    weight: 2,
                    opacity: 1,
                    fillOpacity: 0.9
                }}).addTo(map);
                marker.bindPopup(`<strong>Wp ${{idx + 1}}</strong><br>Lat: ${{wp[1].toFixed(5)}}<br>Lon: ${{wp[0].toFixed(5)}}`);
                waypointMarkers.push(marker);
            }});

            markTacks(segments);
            map.fitBounds(routeLayer.getBounds(), {{ padding: [50, 50] }});
        }}

        function markTacks(segments) {{
            for (let i = 1; i < segments.length; i++) {{
                const prevSeg = segments[i - 1];
                const currSeg = segments[i];
                const prevTWA = prevSeg.twa;
                const currTWA = currSeg.twa;

                const signChange = (prevTWA > 0 && currTWA < 0) || (prevTWA < 0 && currTWA > 0);
                if (!signChange) continue;

                const prevAbsTWA = Math.abs(prevTWA);
                const currAbsTWA = Math.abs(currTWA);

                let tackType = null;
                let tackColor = null;
                let tackLabel = null;

                if (prevAbsTWA < 90 || currAbsTWA < 90) {{
                    tackType = 'tack';
                    tackColor = '#9b59b6';
                    tackLabel = 'TACK (gorÄ…)';
                }} else if (prevAbsTWA >= 90 && currAbsTWA >= 90) {{
                    tackType = 'jibe';
                    tackColor = '#1abc9c';
                    tackLabel = 'JIBE (dolem)';
                }}

                if (tackType) {{
                    const tackPoint = currSeg.from;
                    const marker = L.circleMarker([tackPoint.lat, tackPoint.lon], {{
                        radius: 10,
                        fillColor: tackColor,
                        color: '#fff',
                        weight: 3,
                        opacity: 1,
                        fillOpacity: 0.95
                    }}).addTo(map);

                    let popupHTML = `<div style="text-align: center; font-weight: bold; color: ${{tackColor}}; font-size: 14px;">${{tackLabel}}</div><hr style="margin: 5px 0; border: 1px solid ${{tackColor}};">
                    <div style="font-size: 12px; line-height: 1.5;">
                    <strong>Previous TWA:</strong> ${{prevTWA.toFixed(1)}}°<br>
                    <strong>Current TWA:</strong> ${{currTWA.toFixed(1)}}°<br>
                    <strong>Wind:</strong> ${{currSeg.wind_direction.toFixed(0)}}°<br>
                    <strong>Wind Speed:</strong> ${{currSeg.wind_speed_knots.toFixed(1)}} kt`;

                    if (tackType === 'tack') {{
                        popupHTML += `<hr style="margin: 5px 0;"><strong style="color: #9b59b6;">Tack - Zwrot przez sztag</strong><br><small>Przebija gora dead zone (0)</small>`;
                    }} else {{
                        popupHTML += `<hr style="margin: 5px 0;"><strong style="color: #1abc9c;">Jibe - Zwrot przez rufe</strong><br><small>Przebija dolem dead zone (180)</small>`;
                    }}

                    popupHTML += '</div>';
                    marker.bindPopup(popupHTML);
                    tackMarkers.push(marker);
                }}
            }}
        }}

        function displayStats(routeData) {{
            const route = routeData.route;
            const yacht = routeData.yacht;
            const html = `
                <div class="stat">
                    <span class="stat-label">Jacht:</span>
                    <span class="stat-value">${{yacht.name}}</span>
                </div>
                <div class="stat">
                    <span class="stat-label">Dystans:</span>
                    <span class="stat-value">${{route.total_distance_nm.toFixed(2)}} nm</span>
                </div>
                <div class="stat">
                    <span class="stat-label">Czas:</span>
                    <span class="stat-value">${{route.total_time_hours.toFixed(2)}} h</span>
                </div>
                <div class="stat">
                    <span class="stat-label">Sr. predkosc:</span>
                    <span class="stat-value">${{route.average_speed_knots.toFixed(2)}} kt</span>
                </div>
            `;
            document.getElementById('routeStats').innerHTML = html;
        }}

        function displaySegments(routeData) {{
            const segments = routeData.route.segments;
            const html = segments.map((seg, idx) => {{
                const hals = classifyHals(seg.twa);
                const color = posColors[getPosEnglish(hals)];
                const halsPl = getHalsPolish(hals);
                return `
                    <div class="segment-item" onclick="selectSegment(${{idx}})" style="border-left-color: ${{color}};">
                        <div style="margin-bottom: 6px;">
                            <span class="segment-pos" style="background: ${{color}};">${{halsPl}}</span>
                            <strong style="font-size: 11px;">#${{idx + 1}}</strong>
                        </div>
                        <div style="font-size: 11px; color: #b0b0b0; line-height: 1.4;">
                            ${{seg.distance_nm.toFixed(2)}} nm | ${{(seg.time_seconds / 3600).toFixed(2)}} h<br>
                            B:${{seg.bearing.toFixed(0)}}° TWA:${{seg.twa.toFixed(0)}}°<br>
                            Wind:${{seg.wind_speed_knots.toFixed(1)}}kt@${{seg.wind_direction.toFixed(0)}}°<br>
                            Waves:${{seg.wave_height_m.toFixed(1)}}m | ${{seg.boat_speed_knots.toFixed(1)}}kt
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
            loadRoute();
        }});
    </script>
</body>
</html>
    """

    return HTMLResponse(content=html, media_type="text/html; charset=utf-8")