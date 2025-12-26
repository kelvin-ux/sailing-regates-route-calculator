'use client';

import { useEffect, useRef } from 'react';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';

// Segment colors - cycle through for visual distinction
const SEGMENT_COLORS = [
  '#22c55e', // green
  '#3b82f6', // blue
  '#f97316', // orange
  '#8b5cf6', // purple
  '#06b6d4', // cyan
  '#ec4899', // pink
  '#eab308', // yellow
  '#ef4444', // red
];

// Control point type from backend
type ControlPointType = 'START' | 'WAYPOINT' | 'MARK' | 'GATE' | 'FINISH';

interface ControlPoint {
  lat: number;
  lon: number;
  type: ControlPointType;
  width?: number;
  desc?: string;
}

// Helper: calculate bearing between two points
const calculateBearing = (lat1: number, lon1: number, lat2: number, lon2: number): number => {
  const dLon = (lon2 - lon1) * Math.PI / 180;
  const lat1Rad = lat1 * Math.PI / 180;
  const lat2Rad = lat2 * Math.PI / 180;

  const y = Math.sin(dLon) * Math.cos(lat2Rad);
  const x = Math.cos(lat1Rad) * Math.sin(lat2Rad) - Math.sin(lat1Rad) * Math.cos(lat2Rad) * Math.cos(dLon);

  let bearing = Math.atan2(y, x) * 180 / Math.PI;
  return (bearing + 360) % 360;
};

// Helper: calculate distance between two points in nm
const calculateDistanceNm = (lat1: number, lon1: number, lat2: number, lon2: number): number => {
  const R = 3440.065; // Earth radius in nautical miles
  const dLat = (lat2 - lat1) * Math.PI / 180;
  const dLon = (lon2 - lon1) * Math.PI / 180;
  const a = Math.sin(dLat/2) * Math.sin(dLat/2) +
            Math.cos(lat1 * Math.PI / 180) * Math.cos(lat2 * Math.PI / 180) *
            Math.sin(dLon/2) * Math.sin(dLon/2);
  const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1-a));
  return R * c;
};

// ============================================
// CONTROL POINT ICONS
// ============================================
const createControlPointIcon = (type: ControlPointType) => {
  const configs: Record<ControlPointType, { bg: string; border: string; size: number; icon?: string }> = {
    'START': { bg: '#22c55e', border: '#16a34a', size: 22, icon: '▶' },
    'FINISH': { bg: '#ef4444', border: '#dc2626', size: 22, icon: '🏁' },
    'WAYPOINT': { bg: '#3b82f6', border: '#2563eb', size: 16 },
    'MARK': { bg: '#f97316', border: '#ea580c', size: 18, icon: '◆' },
    'GATE': { bg: '#8b5cf6', border: '#7c3aed', size: 20, icon: '⛳' }
  };

  const cfg = configs[type];
  const hasIcon = cfg.icon && (type === 'FINISH' || type === 'GATE');

  return L.divIcon({
    className: 'control-point-marker',
    html: `<div style="
      background: ${cfg.bg}; 
      border: 3px solid ${cfg.border}; 
      border-radius: ${type === 'MARK' ? '4px' : '50%'}; 
      width: ${cfg.size}px; 
      height: ${cfg.size}px; 
      box-shadow: 0 3px 10px rgba(0,0,0,0.4);
      display: flex;
      align-items: center;
      justify-content: center;
      color: white;
      font-size: ${cfg.size * 0.5}px;
      ${type === 'MARK' ? 'transform: rotate(45deg);' : ''}
    ">${hasIcon ? cfg.icon : ''}</div>`,
    iconSize: [cfg.size, cfg.size],
    iconAnchor: [cfg.size/2, cfg.size/2]
  });
};

// ============================================
// MANEUVER ICONS (Tack, Jibe, Course Change)
// ============================================

// Tack icon - sail boat turning through the wind (bow through wind)
// Red with sail symbol
const tackIcon = L.divIcon({
  className: 'tack-marker',
  html: `<div style="
    width: 28px; height: 28px; 
    background: linear-gradient(135deg, #ef4444 0%, #dc2626 100%);
    border-radius: 50%; 
    border: 3px solid white;
    box-shadow: 0 3px 10px rgba(239,68,68,0.5);
    display: flex; align-items: center; justify-content: center;
    color: white; font-size: 14px; font-weight: bold;
  ">⛵</div>`,
  iconSize: [28, 28],
  iconAnchor: [14, 14]
});

// Jibe icon - sail boat turning with wind behind (stern through wind)
// Purple with different symbol
const jibeIcon = L.divIcon({
  className: 'jibe-marker',
  html: `<div style="
    width: 28px; height: 28px; 
    background: linear-gradient(135deg, #8b5cf6 0%, #7c3aed 100%);
    border-radius: 50%; 
    border: 3px solid white;
    box-shadow: 0 3px 10px rgba(139,92,246,0.5);
    display: flex; align-items: center; justify-content: center;
    color: white; font-size: 16px; font-weight: bold;
  ">↻</div>`,
  iconSize: [28, 28],
  iconAnchor: [14, 14]
});

// Course change icon - orange diamond for simple direction change
const courseChangeIcon = L.divIcon({
  className: 'course-change-marker',
  html: `<div style="
    width: 18px; height: 18px; 
    background: linear-gradient(135deg, #f97316 0%, #ea580c 100%);
    transform: rotate(45deg); 
    border: 2px solid white;
    box-shadow: 0 2px 8px rgba(249,115,22,0.5);
  "></div>`,
  iconSize: [18, 18],
  iconAnchor: [9, 9]
});

// Calculated route start/end icons
const calcStartIcon = L.divIcon({
  className: 'calc-marker',
  html: `<div style="
    background: linear-gradient(135deg, #22c55e 0%, #16a34a 100%); 
    border: 4px solid white; 
    border-radius: 50%; 
    width: 26px; height: 26px; 
    box-shadow: 0 3px 12px rgba(34,197,94,0.5);
    display: flex; align-items: center; justify-content: center;
    color: white; font-size: 12px;
  ">▶</div>`,
  iconSize: [26, 26],
  iconAnchor: [13, 13]
});

const calcEndIcon = L.divIcon({
  className: 'calc-marker',
  html: `<div style="
    background: linear-gradient(135deg, #ef4444 0%, #dc2626 100%); 
    border: 4px solid white; 
    border-radius: 50%; 
    width: 26px; height: 26px; 
    box-shadow: 0 3px 12px rgba(239,68,68,0.5);
    display: flex; align-items: center; justify-content: center;
    color: white; font-size: 14px;
  ">🏁</div>`,
  iconSize: [26, 26],
  iconAnchor: [13, 13]
});

// Types from backend
interface BackendSegment {
  from: { lat: number; lon: number };
  to: { lat: number; lon: number };
  bearing: number;
  distance_nm: number;
  time_seconds: number;
  boat_speed_knots: number;
  wind_speed_knots: number;
  wind_direction: number;
  twa: number;
  point_of_sail: string;
  wave_height_m: number;
}

interface ManeuverPoint {
  lat: number;
  lon: number;
  type: 'tack' | 'jibe' | 'course_change';
  twa_before?: number;
  twa_after?: number;
  bearing_before: number;
  bearing_after: number;
  bearing_change: number;
}

interface CalculatedRouteData {
  waypoints: [number, number][];
  segments?: BackendSegment[];
  variantIndex: number;
}

interface SailingMapProps {
  controlPoints: ControlPoint[];
  onMapClick: (lat: number, lng: number) => void;
  calculatedRoutes?: CalculatedRouteData[];
  isRouteCalculated?: boolean;
}

// Helper: get point of sail in Polish
const getPointOfSailPL = (pos: string): string => {
  const map: Record<string, string> = {
    'in_irons': 'W wiatr (martwa strefa)',
    'close_hauled': 'Ostro',
    'close_reach': 'Polwiatr ostry',
    'beam_reach': 'Polwiatr',
    'broad_reach': 'Baksztag',
    'running': 'Z wiatrem',
    'dead_run': 'Fordewind'
  };
  return map[pos] || pos;
};

// Helper: format time
const formatTime = (seconds: number): string => {
  if (!seconds || seconds <= 0) return '-';
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  if (h > 0) return `${h}h ${m}m`;
  return `${m}m`;
};

export default function SailingMap({
  controlPoints,
  onMapClick,
  calculatedRoutes = [],
  isRouteCalculated = false
}: SailingMapProps) {
  const mapRef = useRef<L.Map | null>(null);
  const mapContainerRef = useRef<HTMLDivElement>(null);
  const markersLayerRef = useRef<L.LayerGroup | null>(null);
  const inputRouteLayerRef = useRef<L.Polyline | null>(null);
  const calculatedRoutesLayerRef = useRef<L.LayerGroup | null>(null);

  // Initialize map
  useEffect(() => {
    if (!mapContainerRef.current || mapRef.current) return;

    const map = L.map(mapContainerRef.current, {
      center: [54.5, 18.8],
      zoom: 10,
      zoomControl: true
    });

    // Base layer (OpenStreetMap)
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      attribution: '© OpenStreetMap contributors',
      maxZoom: 19
    }).addTo(map);

    // Sea/nautical layer
    L.tileLayer('https://tiles.openseamap.org/seamark/{z}/{x}/{y}.png', {
      attribution: '© OpenSeaMap contributors',
      maxZoom: 19,
      opacity: 0.7
    }).addTo(map);

    // Layers for markers and routes
    markersLayerRef.current = L.layerGroup().addTo(map);
    calculatedRoutesLayerRef.current = L.layerGroup().addTo(map);

    mapRef.current = map;

    return () => {
      map.remove();
      mapRef.current = null;
    };
  }, []);

  // Handle map clicks - only when route NOT calculated
  useEffect(() => {
    if (!mapRef.current) return;

    const handleClick = (e: L.LeafletMouseEvent) => {
      if (!isRouteCalculated) {
        onMapClick(e.latlng.lat, e.latlng.lng);
      }
    };

    mapRef.current.on('click', handleClick);

    return () => {
      mapRef.current?.off('click', handleClick);
    };
  }, [onMapClick, isRouteCalculated]);

  // Update input control points (when placing points before calculation)
  useEffect(() => {
    if (!mapRef.current || !markersLayerRef.current) return;

    markersLayerRef.current.clearLayers();

    if (inputRouteLayerRef.current) {
      inputRouteLayerRef.current.remove();
      inputRouteLayerRef.current = null;
    }

    if (controlPoints.length === 0) return;

    // Draw control points even when route is calculated (to show waypoints on route)
    controlPoints.forEach((point, index) => {
      const icon = createControlPointIcon(point.type);

      // Build popup content
      const typeLabels: Record<ControlPointType, string> = {
        'START': 'START',
        'FINISH': 'META',
        'WAYPOINT': `Punkt ${index + 1}`,
        'MARK': `Boja ${index}`,
        'GATE': `Bramka ${index}`
      };

      let popupContent = `<b>${typeLabels[point.type]}</b>`;
      if (point.desc) {
        popupContent += `<br/><i>${point.desc}</i>`;
      }
      if (point.width) {
        popupContent += `<br/>Szer: ${point.width}m`;
      }
      popupContent += `<br/><span style="font-size:10px;color:#666;">
        ${point.lat.toFixed(5)}, ${point.lon.toFixed(5)}
      </span>`;

      const marker = L.marker([point.lat, point.lon], { icon })
        .bindPopup(popupContent);

      markersLayerRef.current?.addLayer(marker);
    });

    // Draw dashed line between control points (only before calculation)
    if (!isRouteCalculated && controlPoints.length >= 2) {
      const coords: [number, number][] = controlPoints.map(p => [p.lat, p.lon]);
      inputRouteLayerRef.current = L.polyline(coords, {
        color: '#3b82f6',
        weight: 3,
        opacity: 0.6,
        dashArray: '8, 12'
      }).addTo(mapRef.current);
    }

    // Fit bounds to show all control points
    if (controlPoints.length > 0 && !isRouteCalculated) {
      const bounds = L.latLngBounds(controlPoints.map(p => [p.lat, p.lon]));
      mapRef.current.fitBounds(bounds, { padding: [50, 50], maxZoom: 12 });
    }
  }, [controlPoints, isRouteCalculated]);

  // Update calculated routes
  useEffect(() => {
    if (!mapRef.current || !calculatedRoutesLayerRef.current) return;

    calculatedRoutesLayerRef.current.clearLayers();

    if (!calculatedRoutes || calculatedRoutes.length === 0) return;

    calculatedRoutes.forEach((routeData, routeIndex) => {
      const { waypoints, segments } = routeData;

      if (!waypoints || waypoints.length < 2) return;

      const maneuverPoints: ManeuverPoint[] = [];

      // If we have segments from backend with TWA data
      if (segments && segments.length > 1) {
        // Draw segments with backend data
        let colorIndex = 0;

        for (let i = 0; i < segments.length; i++) {
          const seg = segments[i];
          const prevSeg = i > 0 ? segments[i - 1] : null;

          // Detect maneuvers between segments
          if (prevSeg) {
            const prevTwa = prevSeg.twa;
            const currTwa = seg.twa;
            const twaSignChanged = (prevTwa > 0 && currTwa < 0) || (prevTwa < 0 && currTwa > 0);

            let bearingChange = Math.abs(seg.bearing - prevSeg.bearing);
            if (bearingChange > 180) bearingChange = 360 - bearingChange;

            if (twaSignChanged) {
              // TWA sign changed - it's either tack or jibe
              if (Math.abs(prevTwa) < 90 || Math.abs(currTwa) < 90) {
                // Tack - through the wind at top (close to 0°)
                maneuverPoints.push({
                  lat: seg.from.lat,
                  lon: seg.from.lon,
                  type: 'tack',
                  twa_before: prevTwa,
                  twa_after: currTwa,
                  bearing_before: prevSeg.bearing,
                  bearing_after: seg.bearing,
                  bearing_change: bearingChange
                });
                colorIndex = (colorIndex + 1) % SEGMENT_COLORS.length;
              } else if (Math.abs(prevTwa) > 120 && Math.abs(currTwa) > 120) {
                // Jibe - through the wind at bottom (close to 180°)
                maneuverPoints.push({
                  lat: seg.from.lat,
                  lon: seg.from.lon,
                  type: 'jibe',
                  twa_before: prevTwa,
                  twa_after: currTwa,
                  bearing_before: prevSeg.bearing,
                  bearing_after: seg.bearing,
                  bearing_change: bearingChange
                });
                colorIndex = (colorIndex + 1) % SEGMENT_COLORS.length;
              }
            } else if (bearingChange > 10) {
              // Just a course change (no tack/jibe)
              maneuverPoints.push({
                lat: seg.from.lat,
                lon: seg.from.lon,
                type: 'course_change',
                twa_before: prevTwa,
                twa_after: currTwa,
                bearing_before: prevSeg.bearing,
                bearing_after: seg.bearing,
                bearing_change: bearingChange
              });
              colorIndex = (colorIndex + 1) % SEGMENT_COLORS.length;
            }
          }

          // Draw segment line
          const color = SEGMENT_COLORS[colorIndex];
          const segmentLine = L.polyline(
            [[seg.from.lat, seg.from.lon], [seg.to.lat, seg.to.lon]],
            {
              color: color,
              weight: routeIndex === 0 ? 5 : 3,
              opacity: routeIndex === 0 ? 1 : 0.7
            }
          );

          // Popup with segment details
          const popupContent = `
            <div style="font-size: 12px; min-width: 180px;">
              <div style="font-weight: bold; margin-bottom: 6px; border-bottom: 1px solid #ddd; padding-bottom: 4px; color: ${color};">
                Segment ${i + 1}
              </div>
              <div style="display: grid; grid-template-columns: auto 1fr; gap: 4px 8px;">
                <div style="color: #666;">Kurs:</div>
                <div style="font-weight: 500;">${seg.bearing.toFixed(0)}°</div>
                <div style="color: #666;">TWA:</div>
                <div style="font-weight: 500;">${seg.twa.toFixed(0)}°</div>
                <div style="color: #666;">Hals:</div>
                <div style="font-weight: 500;">${getPointOfSailPL(seg.point_of_sail)}</div>
                <div style="color: #666;">Dystans:</div>
                <div style="font-weight: 500;">${seg.distance_nm.toFixed(2)} nm</div>
                <div style="color: #666;">Czas:</div>
                <div style="font-weight: 500;">${formatTime(seg.time_seconds)}</div>
                <div style="color: #666;">Predkosc:</div>
                <div style="font-weight: 500;">${seg.boat_speed_knots.toFixed(1)} kt</div>
                <div style="color: #666;">Wiatr:</div>
                <div style="font-weight: 500;">${seg.wind_speed_knots.toFixed(1)} kt / ${seg.wind_direction.toFixed(0)}°</div>
                <div style="color: #666;">Fale:</div>
                <div style="font-weight: 500;">${seg.wave_height_m.toFixed(2)} m</div>
              </div>
            </div>
          `;

          segmentLine.bindPopup(popupContent);
          calculatedRoutesLayerRef.current?.addLayer(segmentLine);
        }
      } else {
        // Fallback: generate segments from waypoints only (no TWA data)
        let colorIndex = 0;
        let prevBearing: number | null = null;

        for (let i = 0; i < waypoints.length - 1; i++) {
          const from = waypoints[i];
          const to = waypoints[i + 1];
          const bearing = calculateBearing(from[0], from[1], to[0], to[1]);
          const distance = calculateDistanceNm(from[0], from[1], to[0], to[1]);

          // Check for course change
          if (prevBearing !== null) {
            let bearingChange = Math.abs(bearing - prevBearing);
            if (bearingChange > 180) bearingChange = 360 - bearingChange;

            if (bearingChange > 10) {
              maneuverPoints.push({
                lat: from[0],
                lon: from[1],
                type: 'course_change',
                bearing_before: prevBearing,
                bearing_after: bearing,
                bearing_change: bearingChange
              });
              colorIndex = (colorIndex + 1) % SEGMENT_COLORS.length;
            }
          }
          prevBearing = bearing;

          const color = SEGMENT_COLORS[colorIndex];
          const segmentLine = L.polyline([from, to], {
            color: color,
            weight: routeIndex === 0 ? 5 : 3,
            opacity: routeIndex === 0 ? 1 : 0.7
          });

          const popupContent = `
            <div style="font-size: 12px; min-width: 140px;">
              <div style="font-weight: bold; margin-bottom: 6px; border-bottom: 1px solid #ddd; padding-bottom: 4px; color: ${color};">
                Segment ${i + 1}
              </div>
              <div style="display: grid; grid-template-columns: auto 1fr; gap: 4px 8px;">
                <div style="color: #666;">Kurs:</div>
                <div style="font-weight: 500;">${bearing.toFixed(0)}°</div>
                <div style="color: #666;">Dystans:</div>
                <div style="font-weight: 500;">${distance.toFixed(2)} nm</div>
              </div>
              <div style="margin-top: 8px; font-size: 10px; color: #999;">
                Brak danych pogodowych
              </div>
            </div>
          `;

          segmentLine.bindPopup(popupContent);
          calculatedRoutesLayerRef.current?.addLayer(segmentLine);
        }
      }

      // Draw maneuver points
      maneuverPoints.forEach((mp, mpIdx) => {
        let icon = courseChangeIcon;
        let title = 'Zmiana kursu';
        let color = '#f59e0b';

        if (mp.type === 'tack') {
          icon = tackIcon;
          title = 'Zwrot (tack)';
          color = '#ef4444';
        } else if (mp.type === 'jibe') {
          icon = jibeIcon;
          title = 'Przelozenie (jibe)';
          color = '#8b5cf6';
        }

        const marker = L.marker([mp.lat, mp.lon], {
          icon: icon,
          zIndexOffset: 500
        });

        let popupContent = `
          <div style="font-size: 12px; min-width: 160px;">
            <div style="font-weight: bold; margin-bottom: 6px; color: ${color}; border-bottom: 1px solid #ddd; padding-bottom: 4px;">
              ${title} #${mpIdx + 1}
            </div>
            <div style="display: grid; grid-template-columns: auto 1fr; gap: 4px 8px;">
              <div style="color: #666;">Kurs przed:</div>
              <div style="font-weight: 500;">${mp.bearing_before.toFixed(0)}°</div>
              <div style="color: #666;">Kurs po:</div>
              <div style="font-weight: 500;">${mp.bearing_after.toFixed(0)}°</div>
              <div style="color: #666;">Zmiana:</div>
              <div style="font-weight: 500; color: ${color};">${mp.bearing_change.toFixed(0)}°</div>
        `;

        if (mp.twa_before !== undefined && mp.twa_after !== undefined) {
          popupContent += `
              <div style="color: #666;">TWA przed:</div>
              <div style="font-weight: 500;">${mp.twa_before.toFixed(0)}°</div>
              <div style="color: #666;">TWA po:</div>
              <div style="font-weight: 500;">${mp.twa_after.toFixed(0)}°</div>
          `;
        }

        popupContent += `
              <div style="color: #666;">Pozycja:</div>
              <div style="font-size: 10px;">${mp.lat.toFixed(4)}, ${mp.lon.toFixed(4)}</div>
            </div>
          </div>
        `;

        marker.bindPopup(popupContent);
        calculatedRoutesLayerRef.current?.addLayer(marker);
      });

      // Start/End markers
      if (waypoints.length > 0) {
        const startPoint = waypoints[0];
        const startMarker = L.marker([startPoint[0], startPoint[1]], {
          icon: calcStartIcon,
          zIndexOffset: 1000
        }).bindPopup('<b>START</b>');
        calculatedRoutesLayerRef.current?.addLayer(startMarker);

        const endPoint = waypoints[waypoints.length - 1];
        const endMarker = L.marker([endPoint[0], endPoint[1]], {
          icon: calcEndIcon,
          zIndexOffset: 1000
        }).bindPopup('<b>META</b>');
        calculatedRoutesLayerRef.current?.addLayer(endMarker);
      }
    });

    // Fit bounds
    const allPoints = calculatedRoutes.flatMap(r => r.waypoints || []);
    if (allPoints.length > 0) {
      const bounds = L.latLngBounds(allPoints);
      mapRef.current.fitBounds(bounds, { padding: [50, 50], maxZoom: 12 });
    }
  }, [calculatedRoutes]);

  const cursorStyle = isRouteCalculated ? 'default' : 'crosshair';

  return (
    <div
      ref={mapContainerRef}
      className="absolute inset-0 z-0"
      style={{ cursor: cursorStyle }}
    />
  );
}