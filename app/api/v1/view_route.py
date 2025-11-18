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
    """
    WyÅ›wietla interaktywnÄ… mapÄ™ z obliczonÄ… trasÄ… i warunkami pogodowymi.

    Features:
    - Wizualizacja trasy na mapie
    - Punkty waypoint z informacjami
    - Warunki pogodowe na segmentach (wiatr, fale)
    - SzczegÃ³Å‚y kaÅ¼dego segmentu (bearing, TWA, boat speed)
    - Podsumowanie trasy (czas, dystans, Å›rednia prÄ™dkoÅ›Ä‡)
    """

    # SprawdÅº czy meshed_area istnieje
    mesh_svc = MeshedAreaService(session)
    meshed = await mesh_svc.get_entity_by_id(meshed_area_id, allow_none=False)

    if not meshed:
        return HTMLResponse(
            content=f"<h1>Error 404</h1><p>Meshed area {meshed_area_id} not found</p>",
            status_code=404
        )

    # Pobierz dane trasy z weather points dla poczÄ…tkowych wspÃ³Å‚rzÄ™dnych
    route_api_url = f"/api/v1/routing/{meshed_area_id}/calculated-route"
    weather_api_url = f"/api/v1/mesh/{meshed_area_id}/weather-points"

    html = f"""
<!DOCTYPE html>
<html lang="pl">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Calculated Route View - {meshed_area_id}</title>

    <!-- Leaflet CSS -->
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
            max-width: 400px;
            max-height: 90vh;
            overflow-y: auto;
            z-index: 1000;
            box-shadow: 0 4px 12px rgba(0,0,0,0.5);
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
            font-size: 16px;
        }}

        .stat {{
            display: flex;
            justify-content: space-between;
            margin: 8px 0;
            padding: 8px;
            background: rgba(255,255,255,0.05);
            border-radius: 4px;
        }}

        .stat-label {{
            color: #b0b0b0;
            font-size: 14px;
        }}

        .stat-value {{
            color: #ffffff;
            font-weight: 600;
            font-size: 14px;
        }}

        .segment-list {{
            max-height: 300px;
            overflow-y: auto;
            margin-top: 10px;
        }}

        .segment-item {{
            background: rgba(255,255,255,0.05);
            padding: 10px;
            margin: 8px 0;
            border-radius: 4px;
            border-left: 3px solid #4fc3f7;
            cursor: pointer;
            transition: all 0.2s;
        }}

        .segment-item:hover {{
            background: rgba(79, 195, 247, 0.2);
            transform: translateX(5px);
        }}

        .segment-item.selected {{
            background: rgba(79, 195, 247, 0.3);
            border-left-color: #81c784;
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
        }}

        .wind-arrow {{
            color: #4fc3f7;
            font-weight: bold;
        }}

        .point-of-sail {{
            display: inline-block;
            padding: 2px 8px;
            border-radius: 3px;
            font-size: 12px;
            font-weight: 600;
        }}

        .point-of-sail.close-hauled {{ background: #f44336; }}
        .point-of-sail.beam-reach {{ background: #ff9800; }}
        .point-of-sail.broad-reach {{ background: #4caf50; }}
        .point-of-sail.running {{ background: #2196f3; }}

        /* Scrollbar styling */
        .info-panel::-webkit-scrollbar,
        .segment-list::-webkit-scrollbar {{
            width: 8px;
        }}

        .info-panel::-webkit-scrollbar-track,
        .segment-list::-webkit-scrollbar-track {{
            background: rgba(255,255,255,0.05);
            border-radius: 4px;
        }}

        .info-panel::-webkit-scrollbar-thumb,
        .segment-list::-webkit-scrollbar-thumb {{
            background: #4fc3f7;
            border-radius: 4px;
        }}
    </style>
</head>
<body>
    <div id="map"></div>

    <div class="info-panel" id="infoPanel">
        <h2>ðŸ“ Route Information</h2>
        <div id="routeStats"></div>

        <h3>ðŸ“Š Route Segments</h3>
        <div class="segment-list" id="segmentList"></div>
    </div>

    <div class="loading" id="loading">
        <div class="loading-spinner"></div>
        <div>Loading route data...</div>
    </div>

    <!-- Leaflet JS -->
    <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>

    <script>
        const MESHED_AREA_ID = '{meshed_area_id}';
        const ROUTE_API_URL = '{route_api_url}';
        const WEATHER_API_URL = '{weather_api_url}';

        let map;
        let routeLayer;
        let waypointMarkers = [];
        let segmentPolylines = [];
        let selectedSegmentIndex = null;

        // Initialize map
        function initMap() {{
            map = L.map('map').setView([54.5, 18.5], 10);

            // Dark theme map tiles
            L.tileLayer('https://{{s}}.basemaps.cartocdn.com/dark_all/{{z}}/{{x}}/{{y}}{{r}}.png', {{
                attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>',
                subdomains: 'abcd',
                maxZoom: 20
            }}).addTo(map);
        }}

        // Fetch and display route
        async function loadRoute() {{
            try {{
                const response = await fetch(ROUTE_API_URL);

                if (!response.ok) {{
                    throw new Error(`HTTP ${{response.status}}: ${{await response.text()}}`);
                }}

                const result = await response.json();
                const routeData = result.data;

                displayRoute(routeData);
                displayStats(routeData);
                displaySegments(routeData);

                document.getElementById('loading').style.display = 'none';

            }} catch (error) {{
                console.error('Error loading route:', error);
                document.getElementById('loading').innerHTML = `
                    <div class="error">
                        <strong>Error loading route</strong><br>
                        ${{error.message}}<br><br>
                        <small>Make sure you have run POST /${{MESHED_AREA_ID}}/calculate-route first</small>
                    </div>
                `;
            }}
        }}

        // Display route on map
        function displayRoute(routeData) {{
            const waypoints = routeData.route.waypoints_wgs84;
            const segments = routeData.route.segments;

            if (!waypoints || waypoints.length === 0) {{
                console.error('No waypoints in route data');
                return;
            }}

            // Convert waypoints to Leaflet LatLng
            const latLngs = waypoints.map(wp => [wp[1], wp[0]]);

            // Draw main route line
            routeLayer = L.polyline(latLngs, {{
                color: '#4fc3f7',
                weight: 4,
                opacity: 0.8
            }}).addTo(map);

            // Draw individual segments with colors based on conditions
            segments.forEach((segment, idx) => {{
                const from = [segment.from.lat, segment.from.lon];
                const to = [segment.to.lat, segment.to.lon];

                const color = getSegmentColor(segment);

                const polyline = L.polyline([from, to], {{
                    color: color,
                    weight: 6,
                    opacity: 0.7
                }}).addTo(map);

                polyline.on('click', () => selectSegment(idx));

                segmentPolylines.push(polyline);
            }});

            // Add waypoint markers
            waypoints.forEach((wp, idx) => {{
                const marker = L.circleMarker([wp[1], wp[0]], {{
                    radius: 6,
                    fillColor: idx === 0 ? '#4caf50' : (idx === waypoints.length - 1 ? '#f44336' : '#ffffff'),
                    color: '#000',
                    weight: 2,
                    opacity: 1,
                    fillOpacity: 0.9
                }}).addTo(map);

                marker.bindPopup(`
                    <strong>Waypoint ${{idx + 1}}</strong><br>
                    ${{wp[1].toFixed(5)}}, ${{wp[0].toFixed(5)}}
                `);

                waypointMarkers.push(marker);
            }});

            // Fit map to route bounds
            map.fitBounds(routeLayer.getBounds(), {{ padding: [50, 50] }});
        }}

        // Get segment color based on conditions
        function getSegmentColor(segment) {{
            const windSpeed = segment.wind_speed_knots;
            const twa = Math.abs(segment.twa);

            // Color based on wind speed and point of sail
            if (windSpeed > 25) return '#f44336'; // Strong wind - red
            if (twa < 45) return '#ff9800'; // Close hauled - orange
            if (twa > 150) return '#2196f3'; // Running - blue
            return '#4caf50'; // Good conditions - green
        }}

        // Display route statistics
        function displayStats(routeData) {{
            const route = routeData.route;
            const yacht = routeData.yacht;

            const html = `
                <div class="stat">
                    <span class="stat-label">ðŸš¤ Yacht:</span>
                    <span class="stat-value">${{yacht.name}}</span>
                </div>
                <div class="stat">
                    <span class="stat-label">ðŸ“ Distance:</span>
                    <span class="stat-value">${{route.total_distance_nm.toFixed(2)}} nm</span>
                </div>
                <div class="stat">
                    <span class="stat-label">â±ï¸ Time:</span>
                    <span class="stat-value">${{route.total_time_hours.toFixed(2)}} hours</span>
                </div>
                <div class="stat">
                    <span class="stat-label">ðŸƒ Avg Speed:</span>
                    <span class="stat-value">${{route.average_speed_knots.toFixed(2)}} knots</span>
                </div>
                <div class="stat">
                    <span class="stat-label">ðŸ“ Waypoints:</span>
                    <span class="stat-value">${{route.waypoints_count}}</span>
                </div>
                <div class="stat">
                    <span class="stat-label">âž¡ï¸ Segments:</span>
                    <span class="stat-value">${{route.segments_count}}</span>
                </div>
            `;

            document.getElementById('routeStats').innerHTML = html;
        }}

        // Display segment list
        function displaySegments(routeData) {{
            const segments = routeData.route.segments;

            const html = segments.map((seg, idx) => {{
                const windArrow = getWindArrow(seg.wind_direction);
                const posClass = seg.point_of_sail.replace(/\\s+/g, '-');

                return `
                    <div class="segment-item" onclick="selectSegment(${{idx}})">
                        <div style="display: flex; justify-content: space-between; margin-bottom: 5px;">
                            <strong>Segment ${{idx + 1}}</strong>
                            <span class="point-of-sail ${{posClass}}">${{seg.point_of_sail}}</span>
                        </div>
                        <div style="font-size: 12px; color: #b0b0b0;">
                            ðŸ“ ${{seg.distance_nm.toFixed(2)}} nm &nbsp;|&nbsp; 
                            â±ï¸ ${{(seg.time_seconds / 3600).toFixed(2)}} hrs<br>
                            ðŸ§­ Bearing: ${{seg.bearing.toFixed(0)}}Â° &nbsp;|&nbsp; 
                            TWA: ${{seg.twa.toFixed(0)}}Â°<br>
                            <span class="wind-arrow">${{windArrow}}</span> Wind: ${{seg.wind_speed_knots.toFixed(1)}} kt @ ${{seg.wind_direction.toFixed(0)}}Â°<br>
                            ðŸŒŠ Waves: ${{seg.wave_height_m.toFixed(1)}} m &nbsp;|&nbsp;
                            ðŸš¤ Speed: ${{seg.boat_speed_knots.toFixed(1)}} kt
                        </div>
                    </div>
                `;
            }}).join('');

            document.getElementById('segmentList').innerHTML = html;
        }}

        // Select segment
        function selectSegment(idx) {{
            // Deselect previous
            if (selectedSegmentIndex !== null) {{
                segmentPolylines[selectedSegmentIndex].setStyle({{ weight: 6, opacity: 0.7 }});
                document.querySelectorAll('.segment-item')[selectedSegmentIndex].classList.remove('selected');
            }}

            // Select new
            selectedSegmentIndex = idx;
            segmentPolylines[idx].setStyle({{ weight: 10, opacity: 1.0 }});
            document.querySelectorAll('.segment-item')[idx].classList.add('selected');

            // Zoom to segment
            const bounds = segmentPolylines[idx].getBounds();
            map.fitBounds(bounds, {{ padding: [100, 100] }});
        }}

        // Get wind direction arrow
        function getWindArrow(direction) {{
            const arrows = ['â†“', 'â†™', 'â†', 'â†–', 'â†‘', 'â†—', 'â†’', 'â†˜'];
            const index = Math.round(direction / 45) % 8;
            return arrows[index];
        }}

        // Initialize
        window.addEventListener('load', () => {{
            initMap();
            loadRoute();
        }});
    </script>
</body>
</html>
    """

    return HTMLResponse(content=html)