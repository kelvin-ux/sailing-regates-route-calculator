'use client';

import { useEffect, useRef } from 'react';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';

// Route colors for different variants
const ROUTE_COLORS = [
  '#22c55e', // green
  '#3b82f6', // blue
  '#f97316', // orange
  '#ef4444', // red
  '#8b5cf6', // purple
  '#06b6d4', // cyan
  '#ec4899', // pink
  '#eab308', // yellow
];

// Icons for input markers
const startIcon = L.divIcon({
  className: 'custom-marker',
  html: '<div style="background: #22c55e; border: 3px solid white; border-radius: 50%; width: 20px; height: 20px; box-shadow: 0 2px 8px rgba(0,0,0,0.3);"></div>',
  iconSize: [20, 20],
  iconAnchor: [10, 10]
});

const endIcon = L.divIcon({
  className: 'custom-marker',
  html: '<div style="background: #ef4444; border: 3px solid white; border-radius: 50%; width: 20px; height: 20px; box-shadow: 0 2px 8px rgba(0,0,0,0.3);"></div>',
  iconSize: [20, 20],
  iconAnchor: [10, 10]
});

const waypointIcon = L.divIcon({
  className: 'custom-marker',
  html: '<div style="background: #3b82f6; border: 2px solid white; border-radius: 50%; width: 14px; height: 14px; box-shadow: 0 2px 6px rgba(0,0,0,0.3);"></div>',
  iconSize: [14, 14],
  iconAnchor: [7, 7]
});

// Icons for calculated route
const calcStartIcon = L.divIcon({
  className: 'calc-marker',
  html: '<div style="background: #22c55e; border: 4px solid white; border-radius: 50%; width: 24px; height: 24px; box-shadow: 0 2px 10px rgba(34,197,94,0.5); display: flex; align-items: center; justify-content: center;"><span style="font-size: 12px;">▶</span></div>',
  iconSize: [24, 24],
  iconAnchor: [12, 12]
});

const calcEndIcon = L.divIcon({
  className: 'calc-marker',
  html: '<div style="background: #ef4444; border: 4px solid white; border-radius: 50%; width: 24px; height: 24px; box-shadow: 0 2px 10px rgba(239,68,68,0.5); display: flex; align-items: center; justify-content: center;"><span style="font-size: 12px;">🏁</span></div>',
  iconSize: [24, 24],
  iconAnchor: [12, 12]
});

interface SailingMapProps {
  markers: [number, number][];
  onMapClick: (lat: number, lng: number) => void;
  calculatedRoutes?: [number, number][][];
  isRouteCalculated?: boolean;
}

export default function SailingMap({
  markers,
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

    // Handle click events (only when route not calculated)
    map.on('click', (e: L.LeafletMouseEvent) => {
      onMapClick(e.latlng.lat, e.latlng.lng);
    });

    mapRef.current = map;

    return () => {
      map.remove();
      mapRef.current = null;
    };
  }, []);

  // Update input markers (when placing points before calculation)
  useEffect(() => {
    if (!mapRef.current || !markersLayerRef.current) return;

    // Clear existing markers
    markersLayerRef.current.clearLayers();

    // Remove existing input route line
    if (inputRouteLayerRef.current) {
      inputRouteLayerRef.current.remove();
      inputRouteLayerRef.current = null;
    }

    // Don't show input markers when route is calculated
    if (isRouteCalculated || markers.length === 0) return;

    // Add input markers
    markers.forEach((coord, index) => {
      let icon = waypointIcon;
      let popupText = `Punkt ${index + 1}`;

      if (index === 0) {
        icon = startIcon;
        popupText = '🟢 START';
      } else if (index === markers.length - 1) {
        icon = endIcon;
        popupText = '🏁 FINISH';
      }

      const marker = L.marker([coord[0], coord[1]], { icon })
        .bindPopup(`<b>${popupText}</b><br/>Lat: ${coord[0].toFixed(5)}<br/>Lon: ${coord[1].toFixed(5)}`);

      markersLayerRef.current?.addLayer(marker);
    });

    // Draw dashed line connecting input points
    if (markers.length >= 2) {
      inputRouteLayerRef.current = L.polyline(markers, {
        color: '#3b82f6',
        weight: 3,
        opacity: 0.8,
        dashArray: '10, 10'
      }).addTo(mapRef.current);
    }

    // Fit bounds
    if (markers.length > 0) {
      const bounds = L.latLngBounds(markers.map(m => [m[0], m[1]]));
      mapRef.current.fitBounds(bounds, { padding: [50, 50], maxZoom: 12 });
    }
  }, [markers, isRouteCalculated]);

  // Update calculated routes display
  useEffect(() => {
    if (!mapRef.current || !calculatedRoutesLayerRef.current) return;

    // Clear existing calculated routes
    calculatedRoutesLayerRef.current.clearLayers();

    if (!calculatedRoutes || calculatedRoutes.length === 0) return;

    // Draw each route variant with different color
    calculatedRoutes.forEach((route, index) => {
      if (!route || route.length < 2) return;

      const color = ROUTE_COLORS[index % ROUTE_COLORS.length];

      // Route line
      const polyline = L.polyline(route, {
        color: color,
        weight: index === 0 ? 4 : 3, // First (best) variant is thicker
        opacity: index === 0 ? 1 : 0.7
      });

      calculatedRoutesLayerRef.current?.addLayer(polyline);

      // Start marker (only for first variant)
      if (index === 0) {
        const startPoint = route[0];
        const startMarker = L.marker([startPoint[0], startPoint[1]], {
          icon: calcStartIcon,
          zIndexOffset: 1000
        }).bindPopup('<b>🟢 START</b>');
        calculatedRoutesLayerRef.current?.addLayer(startMarker);

        const endPoint = route[route.length - 1];
        const endMarker = L.marker([endPoint[0], endPoint[1]], {
          icon: calcEndIcon,
          zIndexOffset: 1000
        }).bindPopup('<b>🏁 FINISH</b>');
        calculatedRoutesLayerRef.current?.addLayer(endMarker);
      }
    });

    // Fit bounds to show all routes
    const allPoints = calculatedRoutes.flat();
    if (allPoints.length > 0) {
      const bounds = L.latLngBounds(allPoints);
      mapRef.current.fitBounds(bounds, { padding: [50, 50], maxZoom: 12 });
    }
  }, [calculatedRoutes]);

  // Update cursor based on state
  const cursorStyle = isRouteCalculated ? 'default' : 'crosshair';

  return (
    <div
      ref={mapContainerRef}
      className="absolute inset-0 z-0"
      style={{ cursor: cursorStyle }}
    />
  );
}