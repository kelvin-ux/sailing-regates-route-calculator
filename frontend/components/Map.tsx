'use client';

import { MapContainer, TileLayer, Marker, Popup, useMapEvents } from 'react-leaflet';
import 'leaflet/dist/leaflet.css';
import L from 'leaflet';
import { useState, useEffect } from 'react';

// --- DEFINICJA IKON ---

// Ikona Startowa (Zielona)
const StartIcon = new L.Icon({
  iconUrl: 'https://raw.githubusercontent.com/pointhi/leaflet-color-markers/master/img/marker-icon-green.png',
  shadowUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.7.1/images/marker-shadow.png',
  iconSize: [25, 41],
  iconAnchor: [12, 41],
  popupAnchor: [1, -34],
  shadowSize: [41, 41]
});

// Ikona Standardowa (Niebieska)
const DefaultIcon = new L.Icon({
  iconUrl: 'https://raw.githubusercontent.com/pointhi/leaflet-color-markers/master/img/marker-icon-blue.png',
  shadowUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.7.1/images/marker-shadow.png',
  iconSize: [25, 41],
  iconAnchor: [12, 41],
  popupAnchor: [1, -34],
  shadowSize: [41, 41]
});

interface SailingMapProps {
  markers: [number, number][];
  onMapClick: (lat: number, lng: number) => void;
}

const SailingMap = ({ markers, onMapClick }: SailingMapProps) => {
  const [isMounted, setIsMounted] = useState(false);

  useEffect(() => {
    // Fix dla Next.js nie jest już krytyczny dla ikon bo używamy własnych obiektów,
    // ale zostawiamy flagę isMounted dla bezpieczeństwa renderowania.
    setIsMounted(true);
  }, []);

  const MapClickHandler = () => {
    useMapEvents({
      click(e) {
        onMapClick(e.latlng.lat, e.latlng.lng);
      },
    });
    return null;
  };

  if (!isMounted) {
    return <div className="flex items-center justify-center h-full bg-slate-100 text-slate-500">Ładowanie mapy...</div>;
  }

  return (
    <MapContainer
      center={[54.5, 18.5]}
      zoom={10}
      style={{ height: "100%", width: "100%" }}
    >
      <TileLayer
        attribution='&copy; OpenStreetMap contributors'
        url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
      />

      <TileLayer
        url="https://tiles.openseamap.org/seamark/{z}/{x}/{y}.png"
        attribution='&copy; OpenSeaMap contributors'
      />

      <MapClickHandler />

      {markers.map((pos, idx) => (
        <Marker
          key={idx}
          position={pos}
          // Logika: Jeśli indeks 0 (pierwszy punkt) użyj StartIcon, w przeciwnym razie DefaultIcon
          icon={idx === 0 ? StartIcon : DefaultIcon}
        >
          <Popup>
            {idx === 0 ? <b>Punkt Startowy</b> : `Punkt trasy #${idx}`}
          </Popup>
        </Marker>
      ))}
    </MapContainer>
  );
};

export default SailingMap;