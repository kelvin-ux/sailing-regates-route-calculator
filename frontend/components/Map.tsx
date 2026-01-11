'use client';

import { useEffect, useRef, useCallback, useState } from 'react';
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
  point_of_sail?: string;
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

// Animation state
interface AnimationState {
  position: [number, number];
  bearing: number;
  progress: number;
}

interface SailingMapProps {
  controlPoints: ControlPoint[];
  onMapClick: (lat: number, lng: number) => void;
  calculatedRoutes?: CalculatedRouteData[];
  isRouteCalculated?: boolean;
  // Animation props
  animationState?: AnimationState | null;
  showWindBarbs?: boolean;
  activeSegmentIndex?: number;
  followBoat?: boolean;
}

// ============================================
// SVG GENERATORS FOR LEAFLET MARKERS
// ============================================

// Wind color based on speed
const getWindColor = (speed: number): string => {
  if (speed < 5) return '#94a3b8';
  if (speed < 10) return '#22c55e';
  if (speed < 15) return '#3b82f6';
  if (speed < 20) return '#f59e0b';
  if (speed < 30) return '#f97316';
  return '#ef4444';
};

// Wind Barb SVG generator
const createWindBarbSvg = (speed: number, direction: number, size: number = 40): string => {
  const roundedSpeed = Math.round(speed / 5) * 5;
  const color = getWindColor(speed);
  
  // Cisza
  if (roundedSpeed < 3) {
    return `
      <svg width="${size}" height="${size}" viewBox="0 0 40 40">
        <circle cx="20" cy="20" r="6" fill="none" stroke="${color}" stroke-width="2"/>
        <circle cx="20" cy="20" r="2" fill="${color}"/>
      </svg>
    `;
  }
  
  const pennants = Math.floor(roundedSpeed / 50);
  const fullBarbs = Math.floor((roundedSpeed % 50) / 10);
  const halfBarbs = Math.floor((roundedSpeed % 10) / 5);
  
  let elements = '';
  let yOffset = 4;
  
  // Punkt bazowy
  elements += `<circle cx="20" cy="36" r="3" fill="${color}"/>`;
  // Trzon
  elements += `<line x1="20" y1="36" x2="20" y2="4" stroke="${color}" stroke-width="2" stroke-linecap="round"/>`;
  
  // Flagi (50 kt)
  for (let i = 0; i < pennants; i++) {
    elements += `<polygon points="20,${yOffset} 32,${yOffset + 4} 20,${yOffset + 8}" fill="${color}"/>`;
    yOffset += 8;
  }
  
  // Długie kreski (10 kt)
  for (let i = 0; i < fullBarbs; i++) {
    elements += `<line x1="20" y1="${yOffset + 2}" x2="32" y2="${yOffset - 2}" stroke="${color}" stroke-width="2" stroke-linecap="round"/>`;
    yOffset += 6;
  }
  
  // Krótkie kreski (5 kt)
  for (let i = 0; i < halfBarbs; i++) {
    elements += `<line x1="20" y1="${yOffset + 2}" x2="26" y2="${yOffset - 1}" stroke="${color}" stroke-width="2" stroke-linecap="round"/>`;
    yOffset += 5;
  }
  
  return `
    <svg width="${size}" height="${size}" viewBox="0 0 40 40" 
         style="transform: rotate(${direction}deg); transform-origin: center;">
      ${elements}
    </svg>
  `;
};

// Animated yacht SVG - dziób na GÓRZE (0°), rotacja = bearing
const createYachtSvg = (bearing: number, twa?: number): string => {
  // Kolor kadłuba w zależności od TWA
  let hullColor = '#3b82f6'; // blue default
  if (twa !== undefined) {
    const absTwa = Math.abs(twa);
    if (absTwa < 30) hullColor = '#ef4444';      // martwa strefa - red
    else if (absTwa < 50) hullColor = '#f97316'; // ostro - orange
    else if (absTwa < 110) hullColor = '#22c55e'; // półwiatr - green (najlepszy)
    else if (absTwa < 150) hullColor = '#3b82f6'; // baksztag - blue
    else hullColor = '#8b5cf6';                   // fordewind - purple
  }
  
  // SVG łódki z dziobem na górze (północ = 0°)
  // bearing określa kierunek ruchu, więc obracamy o bearing stopni
  return `
    <svg width="48" height="48" viewBox="0 0 48 48" 
         style="transform: rotate(${bearing}deg); transform-origin: center; filter: drop-shadow(2px 2px 3px rgba(0,0,0,0.3));">
      <!-- Kadłub - dziób na górze -->
      <path d="M24 4 L34 40 Q24 46 14 40 Z" 
            fill="${hullColor}" 
            stroke="#1e3a8a" 
            stroke-width="1.5"/>
      
      <!-- Żagiel główny -->
      <path d="M24 8 Q33 20 24 36" 
            fill="white" 
            stroke="#94a3b8" 
            stroke-width="1"/>
      
      <!-- Fok -->
      <path d="M24 8 Q17 16 21 26" 
            fill="#f8fafc" 
            stroke="#94a3b8" 
            stroke-width="0.5"/>
      
      <!-- Maszt -->
      <line x1="24" y1="6" x2="24" y2="38" stroke="#1f2937" stroke-width="2"/>
      
      <!-- Bandera na szczycie masztu -->
      <polygon points="24,4 24,8 30,6" fill="#ef4444"/>
    </svg>
  `;
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

// Maneuver icons
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

// Helper functions
const calculateBearing = (lat1: number, lon1: number, lat2: number, lon2: number): number => {
  const dLon = (lon2 - lon1) * Math.PI / 180;
  const lat1Rad = lat1 * Math.PI / 180;
  const lat2Rad = lat2 * Math.PI / 180;
  const y = Math.sin(dLon) * Math.cos(lat2Rad);
  const x = Math.cos(lat1Rad) * Math.sin(lat2Rad) - Math.sin(lat1Rad) * Math.cos(lat2Rad) * Math.cos(dLon);
  let bearing = Math.atan2(y, x) * 180 / Math.PI;
  return (bearing + 360) % 360;
};

const calculateDistanceNm = (lat1: number, lon1: number, lat2: number, lon2: number): number => {
  const R = 3440.065;
  const dLat = (lat2 - lat1) * Math.PI / 180;
  const dLon = (lon2 - lon1) * Math.PI / 180;
  const a = Math.sin(dLat/2) * Math.sin(dLat/2) +
            Math.cos(lat1 * Math.PI / 180) * Math.cos(lat2 * Math.PI / 180) *
            Math.sin(dLon/2) * Math.sin(dLon/2);
  const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1-a));
  return R * c;
};

// Haversine distance in meters
const haversineDistance = (lat1: number, lon1: number, lat2: number, lon2: number): number => {
  const R = 6371000;
  const dLat = (lat2 - lat1) * Math.PI / 180;
  const dLon = (lon2 - lon1) * Math.PI / 180;
  const a = Math.sin(dLat/2) * Math.sin(dLat/2) +
            Math.cos(lat1 * Math.PI / 180) * Math.cos(lat2 * Math.PI / 180) *
            Math.sin(dLon/2) * Math.sin(dLon/2);
  const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1-a));
  return R * c;
};

// Distance from point to line segment
const pointToSegmentDistance = (
  px: number, py: number,
  x1: number, y1: number,
  x2: number, y2: number
): number => {
  const dx = x2 - x1;
  const dy = y2 - y1;
  const lengthSq = dx * dx + dy * dy;
  
  if (lengthSq === 0) {
    return haversineDistance(px, py, x1, y1);
  }
  
  let t = ((px - x1) * dx + (py - y1) * dy) / lengthSq;
  t = Math.max(0, Math.min(1, t));
  
  const nearestX = x1 + t * dx;
  const nearestY = y1 + t * dy;
  
  return haversineDistance(px, py, nearestX, nearestY);
};

const getPointOfSailPL = (pos: string): string => {
  const map: Record<string, string> = {
    'in_irons': 'W wiatr (martwa strefa)',
    'close_hauled': 'Ostro',
    'close_reach': 'Półwiatr ostry',
    'beam_reach': 'Półwiatr',
    'broad_reach': 'Baksztag',
    'running': 'Z wiatrem',
    'dead_run': 'Fordewind'
  };
  return map[pos] || pos;
};

const formatTime = (seconds: number): string => {
  if (!seconds || seconds <= 0) return '-';
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  if (h > 0) return `${h}h ${m}m`;
  return `${m}m`;
};

// ============================================
// WIND GRID GENERATOR - siatka wokół trasy
// ============================================
interface WindGridPoint {
  lat: number;
  lon: number;
  windSpeed: number;
  windDirection: number;
}

const generateWindGrid = (
  segments: BackendSegment[],
  gridSpacingNm: number = 0.5 // ~1km spacing
): WindGridPoint[] => {
  if (!segments || segments.length === 0) return [];
  
  // Znajdź bounding box trasy
  let minLat = Infinity, maxLat = -Infinity;
  let minLon = Infinity, maxLon = -Infinity;
  
  for (const seg of segments) {
    minLat = Math.min(minLat, seg.from.lat, seg.to.lat);
    maxLat = Math.max(maxLat, seg.from.lat, seg.to.lat);
    minLon = Math.min(minLon, seg.from.lon, seg.to.lon);
    maxLon = Math.max(maxLon, seg.from.lon, seg.to.lon);
  }
  
  // Padding wokół trasy (~2nm)
  const paddingLat = 0.033;
  const paddingLon = 0.05;
  minLat -= paddingLat;
  maxLat += paddingLat;
  minLon -= paddingLon;
  maxLon += paddingLon;
  
  // Konwersja spacing z nm na stopnie
  const latStep = gridSpacingNm / 60;
  const avgLat = (minLat + maxLat) / 2;
  const lonStep = gridSpacingNm / (60 * Math.cos(avgLat * Math.PI / 180));
  
  const gridPoints: WindGridPoint[] = [];
  const maxDistanceFromRoute = 4000; // 4km max od trasy
  
  // Generuj siatkę
  for (let lat = minLat; lat <= maxLat; lat += latStep) {
    for (let lon = minLon; lon <= maxLon; lon += lonStep) {
      // Znajdź najbliższy segment
      let minDist = Infinity;
      let closestSeg: BackendSegment | null = null;
      
      for (const seg of segments) {
        const dist = pointToSegmentDistance(
          lat, lon,
          seg.from.lat, seg.from.lon,
          seg.to.lat, seg.to.lon
        );
        
        if (dist < minDist) {
          minDist = dist;
          closestSeg = seg;
        }
      }
      
      // Tylko punkty blisko trasy
      if (closestSeg && minDist < maxDistanceFromRoute) {
        gridPoints.push({
          lat,
          lon,
          windSpeed: closestSeg.wind_speed_knots,
          windDirection: closestSeg.wind_direction
        });
      }
    }
  }
  
  return gridPoints;
};

// ============================================
// MAIN COMPONENT
// ============================================
export default function SailingMap({
  controlPoints,
  onMapClick,
  calculatedRoutes = [],
  isRouteCalculated = false,
  animationState = null,
  showWindBarbs = true,
  activeSegmentIndex,
  followBoat = true
}: SailingMapProps) {
  const mapRef = useRef<L.Map | null>(null);
  const mapContainerRef = useRef<HTMLDivElement>(null);
  const markersLayerRef = useRef<L.LayerGroup | null>(null);
  const inputRouteLayerRef = useRef<L.Polyline | null>(null);
  const calculatedRoutesLayerRef = useRef<L.LayerGroup | null>(null);
  const windBarbsLayerRef = useRef<L.LayerGroup | null>(null);
  const animatedYachtRef = useRef<L.Marker | null>(null);
  const userInteractingRef = useRef<boolean>(false);
  const interactionTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Initialize map
  useEffect(() => {
    if (!mapContainerRef.current || mapRef.current) return;

    const map = L.map(mapContainerRef.current, {
      center: [54.5, 18.8],
      zoom: 10,
      zoomControl: true
    });

    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      attribution: '© OpenStreetMap contributors',
      maxZoom: 19
    }).addTo(map);

    L.tileLayer('https://tiles.openseamap.org/seamark/{z}/{x}/{y}.png', {
      attribution: '© OpenSeaMap contributors',
      maxZoom: 19,
      opacity: 0.7
    }).addTo(map);

    markersLayerRef.current = L.layerGroup().addTo(map);
    calculatedRoutesLayerRef.current = L.layerGroup().addTo(map);
    windBarbsLayerRef.current = L.layerGroup().addTo(map);

    // Wykryj interakcję użytkownika - wyłącz auto-follow na chwilę
    const handleInteractionStart = () => {
      userInteractingRef.current = true;
      if (interactionTimeoutRef.current) {
        clearTimeout(interactionTimeoutRef.current);
      }
    };

    const handleInteractionEnd = () => {
      // Po 3 sekundach wróć do auto-follow
      interactionTimeoutRef.current = setTimeout(() => {
        userInteractingRef.current = false;
      }, 3000);
    };

    map.on('mousedown', handleInteractionStart);
    map.on('touchstart', handleInteractionStart);
    map.on('wheel', handleInteractionStart);
    map.on('mouseup', handleInteractionEnd);
    map.on('touchend', handleInteractionEnd);
    map.on('zoomend', handleInteractionEnd);
    map.on('moveend', handleInteractionEnd);

    mapRef.current = map;

    return () => {
      if (interactionTimeoutRef.current) {
        clearTimeout(interactionTimeoutRef.current);
      }
      map.remove();
      mapRef.current = null;
    };
  }, []);

  // Handle map clicks
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

  // Update control points
  useEffect(() => {
    if (!mapRef.current || !markersLayerRef.current) return;

    markersLayerRef.current.clearLayers();

    if (inputRouteLayerRef.current) {
      inputRouteLayerRef.current.remove();
      inputRouteLayerRef.current = null;
    }

    if (controlPoints.length === 0) return;

    controlPoints.forEach((point, index) => {
      const icon = createControlPointIcon(point.type);
      const typeLabels: Record<ControlPointType, string> = {
        'START': 'START',
        'FINISH': 'META',
        'WAYPOINT': `Punkt ${index + 1}`,
        'MARK': `Boja ${index}`,
        'GATE': `Bramka ${index}`
      };

      let popupContent = `<b>${typeLabels[point.type]}</b>`;
      if (point.desc) popupContent += `<br/><i>${point.desc}</i>`;
      if (point.width) popupContent += `<br/>Szer: ${point.width}m`;
      popupContent += `<br/><span style="font-size:10px;color:#666;">${point.lat.toFixed(5)}, ${point.lon.toFixed(5)}</span>`;

      const marker = L.marker([point.lat, point.lon], { icon }).bindPopup(popupContent);
      markersLayerRef.current?.addLayer(marker);
    });

    if (!isRouteCalculated && controlPoints.length >= 2) {
      const coords: [number, number][] = controlPoints.map(p => [p.lat, p.lon]);
      inputRouteLayerRef.current = L.polyline(coords, {
        color: '#3b82f6',
        weight: 3,
        opacity: 0.6,
        dashArray: '8, 12'
      }).addTo(mapRef.current);
    }

    if (controlPoints.length > 0 && !isRouteCalculated) {
      const bounds = L.latLngBounds(controlPoints.map(p => [p.lat, p.lon]));
      mapRef.current.fitBounds(bounds, { padding: [50, 50], maxZoom: 12 });
    }
  }, [controlPoints, isRouteCalculated]);

  // Update calculated routes and wind barbs
  useEffect(() => {
    if (!mapRef.current || !calculatedRoutesLayerRef.current || !windBarbsLayerRef.current) return;

    calculatedRoutesLayerRef.current.clearLayers();
    windBarbsLayerRef.current.clearLayers();

    if (!calculatedRoutes || calculatedRoutes.length === 0) return;

    calculatedRoutes.forEach((routeData, routeIndex) => {
      const { waypoints, segments } = routeData;
      if (!waypoints || waypoints.length < 2) return;

      const maneuverPoints: ManeuverPoint[] = [];

      if (segments && segments.length > 1) {
        let colorIndex = 0;

        // === WIND BARBS GRID - wokół trasy ===
        if (showWindBarbs && routeIndex === 0) {
          const windGrid = generateWindGrid(segments, 0.6);
          
          for (const point of windGrid) {
            const windBarbIcon = L.divIcon({
              className: 'wind-barb-marker',
              html: createWindBarbSvg(point.windSpeed, point.windDirection, 32),
              iconSize: [32, 32],
              iconAnchor: [16, 16]
            });

            const windMarker = L.marker([point.lat, point.lon], { 
              icon: windBarbIcon,
              interactive: true,
              zIndexOffset: 50
            });

            windMarker.bindPopup(`
              <div style="font-size: 11px; text-align: center; padding: 4px;">
                <b style="color: ${getWindColor(point.windSpeed)};">Wiatr</b><br/>
                <span style="font-size: 14px; font-weight: bold;">${point.windSpeed.toFixed(0)} kt</span><br/>
                <span style="color: #666;">${point.windDirection.toFixed(0)}°</span>
              </div>
            `);

            windBarbsLayerRef.current?.addLayer(windMarker);
          }
        }

        for (let i = 0; i < segments.length; i++) {
          const seg = segments[i];
          const prevSeg = i > 0 ? segments[i - 1] : null;

          // Detect maneuvers
          if (prevSeg) {
            const prevTwa = prevSeg.twa;
            const currTwa = seg.twa;
            const twaSignChanged = (prevTwa > 0 && currTwa < 0) || (prevTwa < 0 && currTwa > 0);

            let bearingChange = Math.abs(seg.bearing - prevSeg.bearing);
            if (bearingChange > 180) bearingChange = 360 - bearingChange;

            if (twaSignChanged) {
              if (Math.abs(prevTwa) < 90 || Math.abs(currTwa) < 90) {
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

          // Draw segment
          const isActive = activeSegmentIndex === i;
          const color = SEGMENT_COLORS[colorIndex];
          const segmentLine = L.polyline(
            [[seg.from.lat, seg.from.lon], [seg.to.lat, seg.to.lon]],
            {
              color: isActive ? '#facc15' : color,
              weight: isActive ? 7 : (routeIndex === 0 ? 4 : 3),
              opacity: routeIndex === 0 ? 0.9 : 0.7
            }
          );

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
                <div style="font-weight: 500;">${getPointOfSailPL(seg.point_of_sail || '')}</div>
                <div style="color: #666;">Dystans:</div>
                <div style="font-weight: 500;">${seg.distance_nm.toFixed(2)} nm</div>
                <div style="color: #666;">Czas:</div>
                <div style="font-weight: 500;">${formatTime(seg.time_seconds)}</div>
                <div style="color: #666;">Prędkość:</div>
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
        // Fallback without segments
        let colorIndex = 0;
        let prevBearing: number | null = null;

        for (let i = 0; i < waypoints.length - 1; i++) {
          const from = waypoints[i];
          const to = waypoints[i + 1];
          const bearing = calculateBearing(from[0], from[1], to[0], to[1]);
          const distance = calculateDistanceNm(from[0], from[1], to[0], to[1]);

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
            weight: routeIndex === 0 ? 4 : 3,
            opacity: routeIndex === 0 ? 0.9 : 0.7
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
          title = 'Przełożenie (jibe)';
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

    // Fit bounds - tylko gdy nie ma animacji (żeby nie resetować zooma)
    if (!animationState) {
      const allPoints = calculatedRoutes.flatMap(r => r.waypoints || []);
      if (allPoints.length > 0) {
        const bounds = L.latLngBounds(allPoints);
        mapRef.current.fitBounds(bounds, { padding: [50, 50], maxZoom: 12 });
      }
    }
  }, [calculatedRoutes, showWindBarbs, activeSegmentIndex, animationState]);

  // Update animated yacht position
  useEffect(() => {
    if (!mapRef.current) return;

    if (!animationState) {
      // Remove yacht if no animation
      if (animatedYachtRef.current) {
        animatedYachtRef.current.remove();
        animatedYachtRef.current = null;
      }
      return;
    }

    const { position, bearing } = animationState;
    
    // Get current segment's TWA for coloring
    let currentTwa: number | undefined;
    if (calculatedRoutes.length > 0 && calculatedRoutes[0].segments) {
      const segments = calculatedRoutes[0].segments;
      const segIndex = Math.min(
        Math.floor(animationState.progress * segments.length),
        segments.length - 1
      );
      currentTwa = segments[segIndex]?.twa;
    }

    const yachtIcon = L.divIcon({
      className: 'animated-yacht',
      html: createYachtSvg(bearing, currentTwa),
      iconSize: [48, 48],
      iconAnchor: [24, 24]
    });

    if (animatedYachtRef.current) {
      animatedYachtRef.current.setLatLng(position);
      animatedYachtRef.current.setIcon(yachtIcon);
    } else {
      animatedYachtRef.current = L.marker(position, {
        icon: yachtIcon,
        zIndexOffset: 2000
      }).addTo(mapRef.current);
    }

    if (followBoat && !userInteractingRef.current) {
      mapRef.current.setView(position, mapRef.current.getZoom(), {
        animate: true,
        duration: 0.25
      });
    }
  }, [animationState, calculatedRoutes, followBoat]);

  const cursorStyle = isRouteCalculated ? 'default' : 'crosshair';

  return (
    <div
      ref={mapContainerRef}
      className="absolute inset-0 z-0"
      style={{ cursor: cursorStyle }}
    />
  );
}