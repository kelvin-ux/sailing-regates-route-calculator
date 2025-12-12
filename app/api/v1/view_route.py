from fastapi.responses import HTMLResponse
from pydantic import UUID4
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import APIRouter, Depends, HTTPException, Query
from app.core.database import get_db as get_async_session
from app.services.db.services import MeshedAreaService
from sqlalchemy import select
from app.models.models import RouteSegments, RoutePoint, RouteVariant
import json
from typing import Optional, List

router = APIRouter()

VARIANT_COLORS = [
    '#FF6B6B',  # Red
    '#4ECDC4',  # Teal
    '#45B7D1',  # Blue
    '#96CEB4',  # Green
    '#FFEAA7',  # Yellow
    '#DDA0DD',  # Plum
    '#98D8C8',  # Mint
    '#F7DC6F',  # Gold
    '#BB8FCE',  # Purple
    '#85C1E9',  # Light Blue
]


@router.get("/{meshed_area_id}/route/view", response_class=HTMLResponse)
async def view_calculated_route(
        meshed_area_id: UUID4,
        show_all_variants: bool = Query(False, description="Show all route variants"),
        session: AsyncSession = Depends(get_async_session)
):
    """
    Visualize calculated routes on a map.

    If show_all_variants=true, displays all calculated variants.
    Otherwise, displays only selected variants (or best if none selected).
    """
    mesh_svc = MeshedAreaService(session)
    meshed = await mesh_svc.get_entity_by_id(meshed_area_id, allow_none=False)

    if not meshed:
        return HTMLResponse(
            content=f"<h1>Error 404</h1><p>Meshed area {meshed_area_id} not found</p>",
            status_code=404,
            media_type="text/html; charset=utf-8"
        )

    # Get route variants
    if show_all_variants:
        variants_query = (
            select(RouteVariant)
            .where(RouteVariant.meshed_area_id == meshed_area_id)
            .order_by(RouteVariant.variant_order)
        )
    else:
        variants_query = (
            select(RouteVariant)
            .where(RouteVariant.meshed_area_id == meshed_area_id)
            .where(RouteVariant.is_selected == True)
            .order_by(RouteVariant.variant_order)
        )

    result = await session.execute(variants_query)
    variants = result.scalars().all()

    # If no selected variants, get the best one
    if not variants:
        best_query = (
            select(RouteVariant)
            .where(RouteVariant.meshed_area_id == meshed_area_id)
            .where(RouteVariant.is_best == True)
            .limit(1)
        )
        result = await session.execute(best_query)
        best_variant = result.scalar_one_or_none()
        if best_variant:
            variants = [best_variant]

    all_variants_query = (
        select(RouteVariant)
        .where(RouteVariant.meshed_area_id == meshed_area_id)
        .order_by(RouteVariant.variant_order)
    )
    result = await session.execute(all_variants_query)
    all_variants = result.scalars().all()

    variants_data = []
    for idx, variant in enumerate(variants):
        waypoints = json.loads(variant.waypoints_json)
        segments = json.loads(variant.segments_json)

        maneuvers = []
        for i, seg in enumerate(segments):
            if i > 0:
                prev_seg = segments[i - 1]
                prev_twa = prev_seg.get('twa', 0)
                curr_twa = seg.get('twa', 0)

                if (prev_twa > 0 and curr_twa < 0) or (prev_twa < 0 and curr_twa > 0):
                    maneuver_type = None
                    if abs(prev_twa) < 90 or abs(curr_twa) < 90:
                        maneuver_type = 'tack'
                    elif abs(prev_twa) > 120 and abs(curr_twa) > 120:
                        maneuver_type = 'jibe'

                    if maneuver_type:
                        maneuvers.append({
                            'type': maneuver_type,
                            'lat': seg['from']['lat'],
                            'lon': seg['from']['lon'],
                            'segment_idx': i,
                            'prev_twa': prev_twa,
                            'new_twa': curr_twa
                        })

        variants_data.append({
            'id': str(variant.id),
            'order': variant.variant_order,
            'departure_time': variant.departure_time.isoformat() if variant.departure_time else None,
            'waypoints': waypoints,
            'segments': segments,
            'maneuvers': maneuvers,
            'total_time_hours': variant.total_time_hours,
            'total_distance_nm': variant.total_distance_nm,
            'average_speed_knots': variant.average_speed_knots,
            'avg_wind_speed': variant.avg_wind_speed,
            'avg_wave_height': variant.avg_wave_height,
            'tacks_count': variant.tacks_count,
            'jibes_count': variant.jibes_count,
            'is_best': variant.is_best,
            'is_selected': variant.is_selected,
            'color': VARIANT_COLORS[idx % len(VARIANT_COLORS)]
        })

    all_variants_data = [
        {
            'id': str(v.id),
            'order': v.variant_order,
            'departure_time': v.departure_time.isoformat() if v.departure_time else None,
            'total_time_hours': v.total_time_hours,
            'total_distance_nm': v.total_distance_nm,
            'is_best': v.is_best,
            'is_selected': v.is_selected
        }
        for v in all_variants
    ]

    variants_json = json.dumps(variants_data)
    all_variants_json = json.dumps(all_variants_data)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Multi-Variant Route View - {meshed_area_id}</title>
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
        .control-panel {{
            position: absolute;
            top: 10px;
            right: 10px;
            background: rgba(26, 26, 26, 0.95);
            padding: 15px;
            border-radius: 8px;
            max-width: 380px;
            max-height: 90vh;
            overflow-y: auto;
            z-index: 1000;
            box-shadow: 0 4px 12px rgba(0,0,0,0.5);
            border: 1px solid rgba(79, 195, 247, 0.3);
        }}
        .control-panel h2 {{
            color: #4fc3f7;
            margin-bottom: 15px;
            font-size: 16px;
            border-bottom: 2px solid #4fc3f7;
            padding-bottom: 8px;
        }}
        .control-panel h3 {{
            color: #81c784;
            margin-top: 12px;
            margin-bottom: 8px;
            font-size: 13px;
            text-transform: uppercase;
            letter-spacing: 1px;
        }}
        .variant-selector {{
            margin: 10px 0;
        }}
        .variant-checkbox {{
            display: flex;
            align-items: center;
            padding: 8px;
            margin: 4px 0;
            background: rgba(255,255,255,0.05);
            border-radius: 4px;
            cursor: pointer;
            transition: background 0.2s;
        }}
        .variant-checkbox:hover {{
            background: rgba(79, 195, 247, 0.2);
        }}
        .variant-checkbox.selected {{
            background: rgba(79, 195, 247, 0.3);
        }}
        .variant-checkbox input {{
            margin-right: 10px;
            cursor: pointer;
        }}
        .variant-color {{
            width: 16px;
            height: 16px;
            border-radius: 50%;
            margin-right: 10px;
            border: 2px solid white;
        }}
        .variant-info {{
            flex: 1;
            font-size: 12px;
        }}
        .variant-info .time {{
            font-weight: bold;
            color: #fff;
        }}
        .variant-info .stats {{
            color: #aaa;
            font-size: 11px;
        }}
        .best-badge {{
            background: #4caf50;
            color: white;
            padding: 2px 6px;
            border-radius: 3px;
            font-size: 10px;
            margin-left: 6px;
        }}
        .btn {{
            display: block;
            width: 100%;
            padding: 10px;
            margin: 5px 0;
            border: none;
            border-radius: 4px;
            cursor: pointer;
            font-size: 13px;
            transition: background 0.2s;
        }}
        .btn-primary {{
            background: #4fc3f7;
            color: #000;
        }}
        .btn-primary:hover {{
            background: #29b6f6;
        }}
        .btn-secondary {{
            background: #555;
            color: #fff;
        }}
        .btn-secondary:hover {{
            background: #666;
        }}
        .comparison-box {{
            margin-top: 15px;
            padding: 10px;
            background: rgba(255,255,255,0.05);
            border-radius: 4px;
            font-size: 12px;
        }}
        .summary-row {{
            display: flex;
            justify-content: space-between;
            padding: 4px 0;
        }}
        .summary-label {{
            color: #aaa;
        }}
        .summary-value {{
            color: #fff;
            font-weight: bold;
        }}
        .legend {{
            position: absolute;
            bottom: 20px;
            left: 10px;
            background: rgba(26, 26, 26, 0.95);
            padding: 10px 15px;
            border-radius: 8px;
            z-index: 1000;
            max-height: 200px;
            overflow-y: auto;
            border: 1px solid rgba(79, 195, 247, 0.3);
        }}
        .legend h4 {{
            color: #4fc3f7;
            margin-bottom: 8px;
            font-size: 12px;
        }}
        .legend-item {{
            display: flex;
            align-items: center;
            margin: 4px 0;
            font-size: 11px;
        }}
        .legend-color {{
            width: 20px;
            height: 4px;
            margin-right: 8px;
            border-radius: 2px;
        }}
        #loading {{
            position: absolute;
            top: 50%;
            left: 50%;
            transform: translate(-50%, -50%);
            background: rgba(0,0,0,0.8);
            padding: 20px 40px;
            border-radius: 8px;
            z-index: 2000;
        }}
        .segment-popup {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            font-size: 12px;
            min-width: 220px;
        }}
        .segment-popup h4 {{
            margin-bottom: 8px;
            padding-bottom: 6px;
            border-bottom: 1px solid #ddd;
        }}
        .segment-popup .row {{
            display: flex;
            justify-content: space-between;
            margin: 3px 0;
        }}
        .segment-popup .label {{
            color: #666;
        }}
        .segment-popup .value {{
            font-weight: bold;
        }}
        .option-checkbox {{
            display: flex;
            align-items: center;
            padding: 6px 0;
            font-size: 12px;
            cursor: pointer;
        }}
        .option-checkbox input {{
            margin-right: 8px;
        }}
        .maneuver-legend {{
            margin-top: 8px;
            padding-top: 8px;
            border-top: 1px solid #333;
        }}
        .maneuver-item {{
            display: flex;
            align-items: center;
            font-size: 11px;
            margin: 4px 0;
        }}
        .maneuver-icon {{
            width: 16px;
            height: 16px;
            border-radius: 50%;
            margin-right: 8px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 10px;
            font-weight: bold;
            color: #000;
        }}
        .tack-icon {{
            background: #2196F3;
        }}
        .jibe-icon {{
            background: #FF9800;
        }}
    </style>
</head>
<body>
    <div id="map"></div>
    <div id="loading">Loading routes...</div>

    <div class="control-panel">
        <h2>Route Variants</h2>
        <div id="variantSelector" class="variant-selector"></div>

        <button class="btn btn-primary" onclick="applySelection()">Apply Selection</button>
        <button class="btn btn-secondary" onclick="selectAll()">Select All</button>
        <button class="btn btn-secondary" onclick="selectNone()">Clear Selection</button>

        <h3>Display Options</h3>
        <label class="option-checkbox">
            <input type="checkbox" id="showManeuvers" checked onchange="toggleManeuvers()">
            Show Tacks & Jibes
        </label>

        <h3>Comparison</h3>
        <div id="comparisonBox" class="comparison-box"></div>
    </div>

    <div class="legend">
        <h4>Route Variants</h4>
        <div id="legendContent"></div>
        <div class="maneuver-legend" id="maneuverLegend">
            <div class="maneuver-item">
                <div class="maneuver-icon tack-icon">T</div>
                <span>Tack (przez sztag)</span>
            </div>
            <div class="maneuver-item">
                <div class="maneuver-icon jibe-icon">J</div>
                <span>Jibe (przez rufę)</span>
            </div>
        </div>
    </div>

    <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
    <script>
        const MESHED_AREA_ID = "{meshed_area_id}";
        const VARIANTS_DATA = {variants_json};
        const ALL_VARIANTS = {all_variants_json};
        const COLORS = {json.dumps(VARIANT_COLORS)};

        let map;
        let routeLayers = {{}};
        let segmentLayers = {{}};
        let markerLayers = {{}};
        let maneuverLayers = {{}};
        let showManeuvers = true;

        function initMap() {{
            map = L.map('map').setView([54.5, 18.5], 10);

            L.tileLayer('https://{{s}}.basemaps.cartocdn.com/dark_all/{{z}}/{{x}}/{{y}}{{r}}.png', {{
                attribution: '&copy; OpenStreetMap, CartoDB',
                maxZoom: 20
            }}).addTo(map);
        }}

        function formatTime(hours) {{
            const h = Math.floor(hours);
            const m = Math.round((hours - h) * 60);
            return `${{h}}h ${{m}}m`;
        }}

        function formatDepartureTime(isoString) {{
            if (!isoString) return 'N/A';
            const date = new Date(isoString);
            return date.toLocaleString('en-GB', {{
                month: 'short',
                day: 'numeric',
                hour: '2-digit',
                minute: '2-digit'
            }});
        }}

        function getPointOfSailEmoji(pos) {{
            switch(pos) {{
                case 'close_hauled': return '⛵↗';
                case 'beam_reach': return '⛵→';
                case 'broad_reach': return '⛵↘';
                case 'running': return '⛵↓';
                default: return '⛵';
            }}
        }}

        function populateVariantSelector() {{
            const container = document.getElementById('variantSelector');
            container.innerHTML = '';

            ALL_VARIANTS.forEach((variant, idx) => {{
                const color = COLORS[idx % COLORS.length];
                const isDisplayed = VARIANTS_DATA.some(v => v.id === variant.id);

                const div = document.createElement('div');
                div.className = `variant-checkbox ${{isDisplayed ? 'selected' : ''}}`;
                div.innerHTML = `
                    <input type="checkbox" id="variant_${{variant.id}}" value="${{variant.id}}" 
                           ${{isDisplayed ? 'checked' : ''}}>
                    <div class="variant-color" style="background: ${{color}};"></div>
                    <div class="variant-info">
                        <div class="time">
                            ${{formatDepartureTime(variant.departure_time)}}
                            ${{variant.is_best ? '<span class="best-badge">BEST</span>' : ''}}
                        </div>
                        <div class="stats">
                            ${{formatTime(variant.total_time_hours)}} · 
                            ${{variant.total_distance_nm.toFixed(1)}} nm
                        </div>
                    </div>
                `;

                div.addEventListener('click', (e) => {{
                    if (e.target.type !== 'checkbox') {{
                        const checkbox = div.querySelector('input[type="checkbox"]');
                        checkbox.checked = !checkbox.checked;
                    }}
                    div.classList.toggle('selected', div.querySelector('input').checked);
                    updateComparison();
                }});

                container.appendChild(div);
            }});
        }}

        function displayRoutes() {{
            // Clear existing layers
            Object.values(routeLayers).forEach(layer => map.removeLayer(layer));
            Object.values(segmentLayers).forEach(layers => layers.forEach(l => map.removeLayer(l)));
            Object.values(markerLayers).forEach(layer => map.removeLayer(layer));
            Object.values(maneuverLayers).forEach(layers => layers.forEach(l => map.removeLayer(l)));

            routeLayers = {{}};
            segmentLayers = {{}};
            markerLayers = {{}};
            maneuverLayers = {{}};

            const bounds = L.latLngBounds();
            const legendContent = document.getElementById('legendContent');
            legendContent.innerHTML = '';

            VARIANTS_DATA.forEach((variant, idx) => {{
                const color = variant.color || COLORS[idx % COLORS.length];
                segmentLayers[variant.id] = [];
                maneuverLayers[variant.id] = [];

                // Draw each segment separately for individual popups
                if (variant.segments && variant.segments.length > 0) {{
                    variant.segments.forEach((seg, segIdx) => {{
                        const segCoords = [
                            [seg.from.lat, seg.from.lon],
                            [seg.to.lat, seg.to.lon]
                        ];

                        const segmentLine = L.polyline(segCoords, {{
                            color: color,
                            weight: 4,
                            opacity: 0.8,
                            dashArray: idx > 0 ? '10, 5' : null
                        }}).addTo(map);

                        // Segment popup with detailed info
                        segmentLine.bindPopup(`
                            <div class="segment-popup">
                                <h4 style="color: ${{color}};">Segment #${{segIdx + 1}} / ${{variant.segments.length}}</h4>
                                <div class="row">
                                    <span class="label">Bearing:</span>
                                    <span class="value">${{seg.bearing?.toFixed(0) || 'N/A'}}°</span>
                                </div>
                                <div class="row">
                                    <span class="label">Distance:</span>
                                    <span class="value">${{seg.distance_nm?.toFixed(2) || 'N/A'}} nm</span>
                                </div>
                                <div class="row">
                                    <span class="label">Time:</span>
                                    <span class="value">${{seg.time_seconds ? formatTime(seg.time_seconds / 3600) : 'N/A'}}</span>
                                </div>
                                <div class="row">
                                    <span class="label">Boat Speed:</span>
                                    <span class="value">${{seg.boat_speed_knots?.toFixed(1) || 'N/A'}} kt</span>
                                </div>
                                <hr style="margin: 6px 0; border-color: #ddd;">
                                <div class="row">
                                    <span class="label">Wind:</span>
                                    <span class="value">${{seg.wind_speed_knots?.toFixed(1) || 'N/A'}} kt @ ${{seg.wind_direction?.toFixed(0) || 'N/A'}}°</span>
                                </div>
                                <div class="row">
                                    <span class="label">TWA:</span>
                                    <span class="value">${{seg.twa?.toFixed(0) || 'N/A'}}°</span>
                                </div>
                                <div class="row">
                                    <span class="label">Point of Sail:</span>
                                    <span class="value">${{seg.point_of_sail || 'N/A'}} ${{getPointOfSailEmoji(seg.point_of_sail)}}</span>
                                </div>
                                <div class="row">
                                    <span class="label">Wave Height:</span>
                                    <span class="value">${{seg.wave_height_m?.toFixed(2) || 'N/A'}} m</span>
                                </div>
                            </div>
                        `);

                        segmentLayers[variant.id].push(segmentLine);
                        segCoords.forEach(c => bounds.extend(c));
                    }});
                }} else {{
                    // Fallback to waypoints if no segments
                    const coords = variant.waypoints.map(wp => [wp[1], wp[0]]);
                    const polyline = L.polyline(coords, {{
                        color: color,
                        weight: 4,
                        opacity: 0.8,
                        dashArray: idx > 0 ? '10, 5' : null
                    }}).addTo(map);

                    routeLayers[variant.id] = polyline;
                    coords.forEach(c => bounds.extend(c));
                }}

                // Add maneuver markers (tacks and jibes)
                if (variant.maneuvers && variant.maneuvers.length > 0) {{
                    variant.maneuvers.forEach((maneuver, mIdx) => {{
                        const isTack = maneuver.type === 'tack';
                        const markerColor = isTack ? '#2196F3' : '#FF9800';
                        const markerLabel = isTack ? 'T' : 'J';
                        const maneuverName = isTack ? 'Tack (przez sztag)' : 'Jibe (przez rufę)';

                        const icon = L.divIcon({{
                            className: 'maneuver-marker',
                            html: `<div style="
                                width: 20px; 
                                height: 20px; 
                                background: ${{markerColor}}; 
                                border-radius: 50%; 
                                border: 2px solid white;
                                display: flex;
                                align-items: center;
                                justify-content: center;
                                font-size: 11px;
                                font-weight: bold;
                                color: #000;
                                box-shadow: 0 2px 4px rgba(0,0,0,0.3);
                            ">${{markerLabel}}</div>`,
                            iconSize: [20, 20],
                            iconAnchor: [10, 10]
                        }});

                        const marker = L.marker([maneuver.lat, maneuver.lon], {{ icon: icon }});

                        marker.bindPopup(`
                            <div class="segment-popup">
                                <h4 style="color: ${{markerColor}};">${{maneuverName}}</h4>
                                <div class="row">
                                    <span class="label">Variant:</span>
                                    <span class="value">#${{variant.order + 1}}</span>
                                </div>
                                <div class="row">
                                    <span class="label">At segment:</span>
                                    <span class="value">#${{maneuver.segment_idx}}</span>
                                </div>
                                <div class="row">
                                    <span class="label">TWA before:</span>
                                    <span class="value">${{maneuver.prev_twa?.toFixed(0) || 'N/A'}}°</span>
                                </div>
                                <div class="row">
                                    <span class="label">TWA after:</span>
                                    <span class="value">${{maneuver.new_twa?.toFixed(0) || 'N/A'}}°</span>
                                </div>
                            </div>
                        `);

                        if (showManeuvers) {{
                            marker.addTo(map);
                        }}
                        maneuverLayers[variant.id].push(marker);
                    }});
                }}

                // Add markers for start/end
                const coords = variant.waypoints.map(wp => [wp[1], wp[0]]);
                if (coords.length > 0) {{
                    const startMarker = L.circleMarker(coords[0], {{
                        radius: 10,
                        fillColor: '#4caf50',
                        color: '#fff',
                        weight: 3,
                        fillOpacity: 0.9
                    }}).addTo(map);
                    startMarker.bindPopup('<b>START</b>');

                    const endMarker = L.circleMarker(coords[coords.length - 1], {{
                        radius: 10,
                        fillColor: '#f44336',
                        color: '#fff',
                        weight: 3,
                        fillOpacity: 0.9
                    }}).addTo(map);
                    endMarker.bindPopup('<b>FINISH</b>');

                    markerLayers[variant.id + '_start'] = startMarker;
                    markerLayers[variant.id + '_end'] = endMarker;
                }}

                // Add to legend
                const legendItem = document.createElement('div');
                legendItem.className = 'legend-item';
                legendItem.innerHTML = `
                    <div class="legend-color" style="background: ${{color}};"></div>
                    <span>Variant #${{variant.order + 1}} ${{variant.is_best ? '(Best)' : ''}}</span>
                `;
                legendContent.appendChild(legendItem);
            }});

            if (VARIANTS_DATA.length > 0) {{
                map.fitBounds(bounds, {{ padding: [50, 50] }});
            }}

            document.getElementById('loading').style.display = 'none';
            updateComparison();
        }}

        function toggleManeuvers() {{
            showManeuvers = document.getElementById('showManeuvers').checked;

            Object.values(maneuverLayers).forEach(markers => {{
                markers.forEach(marker => {{
                    if (showManeuvers) {{
                        marker.addTo(map);
                    }} else {{
                        map.removeLayer(marker);
                    }}
                }});
            }});

            document.getElementById('maneuverLegend').style.display = showManeuvers ? 'block' : 'none';
        }}

        function updateComparison() {{
            const selected = [];
            document.querySelectorAll('#variantSelector input:checked').forEach(cb => {{
                const variant = ALL_VARIANTS.find(v => v.id === cb.value);
                if (variant) selected.push(variant);
            }});

            const box = document.getElementById('comparisonBox');

            if (selected.length === 0) {{
                box.innerHTML = '<p style="color: #666; font-size: 11px;">Select variants to compare</p>';
                return;
            }}

            const fastest = selected.reduce((a, b) => a.total_time_hours < b.total_time_hours ? a : b);
            const shortest = selected.reduce((a, b) => a.total_distance_nm < b.total_distance_nm ? a : b);

            box.innerHTML = `
                <div class="summary-row">
                    <span class="summary-label">Selected:</span>
                    <span class="summary-value">${{selected.length}} variant(s)</span>
                </div>
                <div class="summary-row">
                    <span class="summary-label">Fastest:</span>
                    <span class="summary-value">Variant #${{fastest.order + 1}} (${{formatTime(fastest.total_time_hours)}})</span>
                </div>
                <div class="summary-row">
                    <span class="summary-label">Shortest:</span>
                    <span class="summary-value">Variant #${{shortest.order + 1}} (${{shortest.total_distance_nm.toFixed(1)}} nm)</span>
                </div>
                <div class="summary-row">
                    <span class="summary-label">Time diff:</span>
                    <span class="summary-value">${{formatTime(Math.max(...selected.map(v => v.total_time_hours)) - Math.min(...selected.map(v => v.total_time_hours)))}}</span>
                </div>
            `;
        }}

        function selectAll() {{
            document.querySelectorAll('#variantSelector input').forEach(cb => {{
                cb.checked = true;
                cb.closest('.variant-checkbox').classList.add('selected');
            }});
            updateComparison();
        }}

        function selectNone() {{
            document.querySelectorAll('#variantSelector input').forEach(cb => {{
                cb.checked = false;
                cb.closest('.variant-checkbox').classList.remove('selected');
            }});
            updateComparison();
        }}

        async function applySelection() {{
            const selectedIds = [];
            document.querySelectorAll('#variantSelector input:checked').forEach(cb => {{
                selectedIds.push(cb.value);
            }});

            try {{
                const response = await fetch(`/api/v1/routing/${{MESHED_AREA_ID}}/variants/select`, {{
                    method: 'POST',
                    headers: {{
                        'Content-Type': 'application/json'
                    }},
                    body: JSON.stringify(selectedIds)
                }});

                if (response.ok) {{
                    // Reload page to show updated selection
                    window.location.reload();
                }} else {{
                    alert('Failed to update selection');
                }}
            }} catch (error) {{
                console.error('Error:', error);
                alert('Error updating selection');
            }}
        }}

        window.addEventListener('load', () => {{
            initMap();
            populateVariantSelector();
            displayRoutes();
        }});
    </script>
</body>
</html>
    """

    return HTMLResponse(content=html, media_type="text/html; charset=utf-8")


@router.get("/{meshed_area_id}/route/compare", response_class=HTMLResponse)
async def compare_route_variants(
        meshed_area_id: UUID4,
        variant_ids: str = Query(..., description="Comma-separated variant IDs to compare"),
        session: AsyncSession = Depends(get_async_session)
):
    """
    Compare specific route variants side by side.

    Example: /compare?variant_ids=uuid1,uuid2,uuid3
    """
    ids = [UUID4(id.strip()) for id in variant_ids.split(',') if id.strip()]

    if not ids:
        raise HTTPException(400, "No variant IDs provided")

    if len(ids) > 5:
        raise HTTPException(400, "Maximum 5 variants can be compared at once")

    variants = []
    for variant_id in ids:
        query = select(RouteVariant).where(RouteVariant.id == variant_id)
        result = await session.execute(query)
        variant = result.scalar_one_or_none()
        if variant:
            variants.append(variant)

    if not variants:
        raise HTTPException(404, "No variants found with provided IDs")

    # Prepare comparison data
    variants_data = []
    for idx, variant in enumerate(variants):
        waypoints = json.loads(variant.waypoints_json)
        segments = json.loads(variant.segments_json)

        variants_data.append({
            'id': str(variant.id),
            'order': variant.variant_order,
            'departure_time': variant.departure_time.isoformat() if variant.departure_time else None,
            'waypoints': waypoints,
            'segments': segments,
            'total_time_hours': variant.total_time_hours,
            'total_distance_nm': variant.total_distance_nm,
            'average_speed_knots': variant.average_speed_knots,
            'avg_wind_speed': variant.avg_wind_speed,
            'avg_wave_height': variant.avg_wave_height,
            'tacks_count': variant.tacks_count,
            'jibes_count': variant.jibes_count,
            'is_best': variant.is_best,
            'color': VARIANT_COLORS[idx % len(VARIANT_COLORS)]
        })

    variants_json = json.dumps(variants_data)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Route Comparison - {len(variants)} Variants</title>
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #1a1a1a; color: #e0e0e0; display: flex; }}
        #map {{ height: 100vh; flex: 1; }}
        .sidebar {{
            width: 350px;
            background: #222;
            padding: 20px;
            overflow-y: auto;
            border-left: 1px solid #333;
        }}
        .sidebar h2 {{ color: #4fc3f7; margin-bottom: 20px; }}
        .comparison-table {{
            width: 100%;
            border-collapse: collapse;
            font-size: 12px;
        }}
        .comparison-table th, .comparison-table td {{
            padding: 8px;
            text-align: left;
            border-bottom: 1px solid #333;
        }}
        .comparison-table th {{ color: #aaa; font-weight: normal; }}
        .comparison-table td {{ color: #fff; }}
        .variant-header {{
            display: flex;
            align-items: center;
            margin-bottom: 4px;
        }}
        .variant-dot {{
            width: 12px;
            height: 12px;
            border-radius: 50%;
            margin-right: 8px;
        }}
        .best {{ color: #4caf50; font-weight: bold; }}
        .winner {{ background: rgba(76, 175, 80, 0.2); }}
        .segment-popup {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            font-size: 12px;
            min-width: 220px;
        }}
        .segment-popup h4 {{
            margin-bottom: 8px;
            padding-bottom: 6px;
            border-bottom: 1px solid #ddd;
        }}
        .segment-popup .row {{
            display: flex;
            justify-content: space-between;
            margin: 3px 0;
        }}
        .segment-popup .label {{
            color: #666;
        }}
        .segment-popup .value {{
            font-weight: bold;
        }}
    </style>
</head>
<body>
    <div id="map"></div>
    <div class="sidebar">
        <h2>Route Comparison</h2>
        <table class="comparison-table" id="comparisonTable">
            <!-- Populated by JavaScript -->
        </table>
    </div>

    <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
    <script>
        const VARIANTS = {variants_json};

        function formatTime(hours) {{
            const h = Math.floor(hours);
            const m = Math.round((hours - h) * 60);
            return `${{h}}h ${{m}}m`;
        }}

        function initMap() {{
            const map = L.map('map').setView([54.5, 18.5], 10);
            L.tileLayer('https://{{s}}.basemaps.cartocdn.com/dark_all/{{z}}/{{x}}/{{y}}{{r}}.png', {{
                attribution: '&copy; OpenStreetMap, CartoDB',
                maxZoom: 20
            }}).addTo(map);

            const bounds = L.latLngBounds();

            VARIANTS.forEach((variant, idx) => {{
                // Draw each segment separately
                if (variant.segments && variant.segments.length > 0) {{
                    variant.segments.forEach((seg, segIdx) => {{
                        const segCoords = [
                            [seg.from.lat, seg.from.lon],
                            [seg.to.lat, seg.to.lon]
                        ];

                        const segmentLine = L.polyline(segCoords, {{
                            color: variant.color,
                            weight: 4,
                            opacity: 0.8,
                            dashArray: idx > 0 ? '10, 5' : null
                        }}).addTo(map);

                        segmentLine.bindPopup(`
                            <div class="segment-popup">
                                <h4 style="color: ${{variant.color}};">Variant #${{variant.order + 1}} - Seg #${{segIdx + 1}}</h4>
                                <div class="row">
                                    <span class="label">Bearing:</span>
                                    <span class="value">${{seg.bearing?.toFixed(0) || 'N/A'}}°</span>
                                </div>
                                <div class="row">
                                    <span class="label">Distance:</span>
                                    <span class="value">${{seg.distance_nm?.toFixed(2) || 'N/A'}} nm</span>
                                </div>
                                <div class="row">
                                    <span class="label">Boat Speed:</span>
                                    <span class="value">${{seg.boat_speed_knots?.toFixed(1) || 'N/A'}} kt</span>
                                </div>
                                <div class="row">
                                    <span class="label">Wind:</span>
                                    <span class="value">${{seg.wind_speed_knots?.toFixed(1) || 'N/A'}} kt</span>
                                </div>
                                <div class="row">
                                    <span class="label">TWA:</span>
                                    <span class="value">${{seg.twa?.toFixed(0) || 'N/A'}}°</span>
                                </div>
                            </div>
                        `);

                        segCoords.forEach(c => bounds.extend(c));
                    }});
                }} else {{
                    const coords = variant.waypoints.map(wp => [wp[1], wp[0]]);
                    L.polyline(coords, {{
                        color: variant.color,
                        weight: 4,
                        opacity: 0.8,
                        dashArray: idx > 0 ? '10, 5' : null
                    }}).addTo(map);
                    coords.forEach(c => bounds.extend(c));
                }}
            }});

            if (VARIANTS.length > 0) {{
                map.fitBounds(bounds, {{ padding: [50, 50] }});
            }}
        }}

        function buildComparisonTable() {{
            const table = document.getElementById('comparisonTable');
            const metrics = [
                {{ key: 'total_time_hours', label: 'Duration', format: v => formatTime(v), best: 'min' }},
                {{ key: 'total_distance_nm', label: 'Distance (nm)', format: v => v.toFixed(2), best: 'min' }},
                {{ key: 'average_speed_knots', label: 'Avg Speed (kt)', format: v => v.toFixed(1), best: 'max' }},
                {{ key: 'avg_wind_speed', label: 'Avg Wind (kt)', format: v => v?.toFixed(1) || 'N/A', best: null }},
                {{ key: 'avg_wave_height', label: 'Avg Waves (m)', format: v => v?.toFixed(2) || 'N/A', best: 'min' }},
                {{ key: 'tacks_count', label: 'Tacks', format: v => v, best: 'min' }},
                {{ key: 'jibes_count', label: 'Jibes', format: v => v, best: 'min' }}
            ];

            // Header row
            let html = '<tr><th></th>';
            VARIANTS.forEach((v, idx) => {{
                html += `<th>
                    <div class="variant-header">
                        <div class="variant-dot" style="background: ${{v.color}};"></div>
                        Variant #${{v.order + 1}}
                    </div>
                    ${{v.is_best ? '<span class="best">★ Best</span>' : ''}}
                </th>`;
            }});
            html += '</tr>';

            // Metric rows
            metrics.forEach(metric => {{
                html += `<tr><th>${{metric.label}}</th>`;

                const values = VARIANTS.map(v => v[metric.key]);
                let bestIdx = -1;
                if (metric.best === 'min') {{
                    bestIdx = values.indexOf(Math.min(...values.filter(v => v !== null && v !== undefined)));
                }} else if (metric.best === 'max') {{
                    bestIdx = values.indexOf(Math.max(...values.filter(v => v !== null && v !== undefined)));
                }}

                VARIANTS.forEach((v, idx) => {{
                    const isBest = idx === bestIdx && metric.best;
                    html += `<td class="${{isBest ? 'winner' : ''}}">${{metric.format(v[metric.key])}}</td>`;
                }});

                html += '</tr>';
            }});

            table.innerHTML = html;
        }}

        window.addEventListener('load', () => {{
            initMap();
            buildComparisonTable();
        }});
    </script>
</body>
</html>
    """

    return HTMLResponse(content=html, media_type="text/html; charset=utf-8")