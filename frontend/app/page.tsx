'use client';

import dynamic from 'next/dynamic';
import { useState, useEffect, useCallback } from 'react';
import LoadingOverlay from '../components/LoadingOverlay';
import SplashScreen from '../components/SplashScreen';

// Import mapy bez SSR
const SailingMap = dynamic(() => import('../components/Map'), {
  ssr: false,
  loading: () => <div className="flex items-center justify-center h-full bg-slate-900 text-white">Ładowanie mapy...</div>
});

// --- LISTA ID PRESETÓW (Zgodna z Twoim yacht_seeder.py) ---
const PRESET_IDS = [
    "c6d1d8ca-4a7c-4c81-a3aa-1fb2f1b6c3af", // CLASS_40
    "0f0c9d6f-92e4-4c52-bc1b-1cc2aeac70e1", // VOLVO_65
    "d3bb2c1e-0d7d-49e6-a1bf-2abf1b185ed9", // OMEGA
    "b59f8c3e-f0ea-4b3e-bd12-92c8529db41a", // BAVARIA_46
    "7e4e8a04-a8b2-4cc4-97dd-93f6e6e1a087", // OYSTER_72
    "f5a2eaf1-1b55-4a0f-a9a4-e6a2f8db5c76", // TP_52
    "3bfeb2a0-d59a-4f15-8e0b-7d9b77cbd789"  // IMOCA_60
];

// Typy danych
type Yacht = {
  id: string;
  name: string;
  yacht_type: string;
  length: number;
  beam: number;
  draft: number;
  sail_number?: string;
  max_speed: number;
  max_wind_speed: number;
  amount_of_crew: number;
};

// Typy punktów kontrolnych
type ControlPointType = 'START' | 'WAYPOINT' | 'MARK' | 'GATE' | 'FINISH';

type ControlPoint = {
  lat: number;
  lon: number;
  type: ControlPointType;
  width?: number; // szerokość bramki w metrach
  desc?: string;  // opis punktu
};

// Ustawienia mesh
type MeshSettings = {
  corridor_nm: number;
  ring1_m: number;
  ring2_m: number;
  ring3_m: number;
  area1: number;
  area2: number;
  area3: number;
  shoreline_avoid_m: number;
  max_weather_points: number;
  weather_grid_km: number;
};

const DEFAULT_MESH_SETTINGS: MeshSettings = {
  corridor_nm: 2.0,
  ring1_m: 500,
  ring2_m: 1500,
  ring3_m: 3000,
  area1: 3000,
  area2: 15000,
  area3: 60000,
  shoreline_avoid_m: 200,
  max_weather_points: 30,
  weather_grid_km: 3.0
};

type CalculationStep = 'idle' | 'mesh' | 'weather' | 'routing' | 'done' | 'error';

type RouteSegment = {
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
};

type TackPoint = {
  lat: number;
  lon: number;
  type: 'tack' | 'jibe';
  from_twa: number;
  to_twa: number;
  bearing_change: number;
};

type RouteVariant = {
  variant_id: string;
  departure_time: string;
  total_time_hours: number;
  total_distance_nm: number;
  average_speed_knots: number;
  avg_wind_speed: number;
  avg_wave_height: number;
  tacks_count: number;
  jibes_count: number;
  is_best: boolean;
  segments_count: number;
  difficulty_score: number;
  difficulty_level: string;
  waypoints_wgs84?: [number, number][]; // lon, lat pairs from backend
  segments?: RouteSegment[];
};

type RouteResult = {
  meshed_area_id: string;
  yacht: { id: string; name: string; type: string };
  variants_count: number;
  variants: RouteVariant[];
  best_variant: RouteVariant | null;
  difficulty: {
    overall_score: number;
    level: string;
  };
};

type CalculationStatus = {
  step: CalculationStep;
  message: string;
  meshedAreaId?: string;
  routeResult?: RouteResult | null;
};

// Domyślny formularz nowego jachtu
const emptyYachtForm = {
  name: "",
  yacht_type: "Sailboat",
  length: 12,
  beam: 4,
  draft: 2,
  sail_number: "POL-1",
  has_spinnaker: false,
  has_genaker: false,
  max_speed: 8,
  max_wind_speed: 35,
  amount_of_crew: 4,
  tack_time: 2,
  jibe_time: 4,
  polar_data: {}
};

// Helper: generuj domyślne okno startowe (od teraz do +24h) w czasie warszawskim
const getDefaultStartWindow = () => {
  const now = new Date();
  const tomorrow = new Date(now.getTime() + 24 * 60 * 60 * 1000);

  // Format dla datetime-local input: YYYY-MM-DDTHH:MM (czas lokalny)
  const formatForInput = (d: Date) => {
    const year = d.getFullYear();
    const month = String(d.getMonth() + 1).padStart(2, '0');
    const day = String(d.getDate()).padStart(2, '0');
    const hours = String(d.getHours()).padStart(2, '0');
    const minutes = String(d.getMinutes()).padStart(2, '0');
    return `${year}-${month}-${day}T${hours}:${minutes}`;
  };

  return {
    start: formatForInput(now),
    end: formatForInput(tomorrow),
    checkCount: 6
  };
};

// Adres API
const API_URL = "http://localhost:8000/api/v1";

export default function Home() {
  // --- STANY ---
  const [allYachts, setAllYachts] = useState<Yacht[]>([]);
  const [mySessionIds, setMySessionIds] = useState<string[]>([]);

  const [selectedYachtId, setSelectedYachtId] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<'presets' | 'my'>('presets');

  // UI - Routing i punkty kontrolne
  const [controlPoints, setControlPoints] = useState<ControlPoint[]>([]);
  const [isCalculating, setIsCalculating] = useState(false);
  const [expandedSection, setExpandedSection] = useState<'yachts' | 'route' | 'startWindow' | 'results' | 'meshSettings' | null>('yachts');

  // UI - Edycja punktu
  const [editingPointIndex, setEditingPointIndex] = useState<number | null>(null);

  // UI - Ustawienia mesh
  const [meshSettings, setMeshSettings] = useState<MeshSettings>(DEFAULT_MESH_SETTINGS);
  const [useAutoMesh, setUseAutoMesh] = useState(true); // automatyczne dostosowanie parametrów

  // UI - Dodawanie jachtu
  const [isAddingYacht, setIsAddingYacht] = useState(false);
  const [newYachtData, setNewYachtData] = useState(emptyYachtForm);

  // UI - Error handling
  const [error, setError] = useState<string | null>(null);

  // UI - Splash screen
  const [showSplash, setShowSplash] = useState(true);

  // NOWE: Okno startowe
  const [startWindow, setStartWindow] = useState(getDefaultStartWindow);
  const [useTimeWindow, setUseTimeWindow] = useState(false);

  // NOWE: Status obliczania
  const [calcStatus, setCalcStatus] = useState<CalculationStatus>({
    step: 'idle',
    message: '',
    routeResult: null
  });

  // NOWE: Wybrane warianty do wyświetlenia na mapie
  const [selectedVariantIds, setSelectedVariantIds] = useState<string[]>([]);

  // NOWE: Dane wariantów (waypoints, segments, tack points)
  const [variantWaypoints, setVariantWaypoints] = useState<Record<string, [number, number][]>>({});
  const [variantSegments, setVariantSegments] = useState<Record<string, RouteSegment[]>>({});
  const [variantTackPoints, setVariantTackPoints] = useState<Record<string, TackPoint[]>>({});

  // --- INICJALIZACJA ---
  useEffect(() => {
    const stored = sessionStorage.getItem("my_yacht_ids");
    if (stored) {
        setMySessionIds(JSON.parse(stored));
    }
    fetchYachts();
  }, []);

  const fetchYachts = async () => {
    try {
      setError(null);
      const res = await fetch(`${API_URL}/yacht/`);
      if (!res.ok) {
        throw new Error(`Failed to fetch yachts: ${res.status} ${res.statusText}`);
      }
      const data: Yacht[] = await res.json();
      setAllYachts(data);

      if (!selectedYachtId && data.length > 0) {
          const defaultPreset = data.find(y => PRESET_IDS.includes(y.id));
          if (defaultPreset) setSelectedYachtId(defaultPreset.id);
      }
    } catch (err) {
      console.error("Błąd pobierania jachtów:", err);
      setError(err instanceof Error ? err.message : "Nie udało się pobrać jachtów");
    }
  };

  // --- FILTROWANIE ---
  const presetYachts = allYachts.filter(y => PRESET_IDS.includes(y.id));
  const myYachts = allYachts.filter(y => mySessionIds.includes(y.id));

  // --- AKCJE JACHTÓW ---

  const handleCreateYacht = async () => {
    try {
        setError(null);
        const res = await fetch(`${API_URL}/yacht/`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(newYachtData)
        });

        if (res.ok) {
            const createdYacht = await res.json();

            setAllYachts(prev => [...prev, createdYacht]);

            const newSessionIds = [...mySessionIds, createdYacht.id];
            setMySessionIds(newSessionIds);
            sessionStorage.setItem("my_yacht_ids", JSON.stringify(newSessionIds));

            setIsAddingYacht(false);
            setNewYachtData(emptyYachtForm);
            setActiveTab('my');
            setSelectedYachtId(createdYacht.id);
        } else {
            const errorText = await res.text();
            console.error("Błąd tworzenia jachtu", errorText);
            setError(`Nie udało się utworzyć jachtu: ${errorText}`);
        }
    } catch (err) {
      console.error(err);
      setError(err instanceof Error ? err.message : "Nie udało się utworzyć jachtu");
    }
  };

  const handleDeleteYacht = async (e: React.MouseEvent, id: string) => {
    e.stopPropagation();
    if(!confirm("Czy na pewno usunąć ten jacht?")) return;

    try {
        setError(null);
        const res = await fetch(`${API_URL}/yacht/${id}`, { method: 'DELETE' });
        if (res.ok || res.status === 204) {
            setAllYachts(prev => prev.filter(y => y.id !== id));

            const newSessionIds = mySessionIds.filter(mid => mid !== id);
            setMySessionIds(newSessionIds);
            sessionStorage.setItem("my_yacht_ids", JSON.stringify(newSessionIds));

            if (selectedYachtId === id) setSelectedYachtId(null);
        } else {
            setError("Nie udało się usunąć jachtu");
        }
    } catch (err) {
      console.error(err);
      setError(err instanceof Error ? err.message : "Nie udało się usunąć jachtu");
    }
  };

  // --- MAPA I ROUTING ---
  const addPoint = (lat: number, lng: number) => {
    if (isCalculating) return;
    if (calcStatus.routeResult) return; // nie dodawaj gdy trasa obliczona

    const numPoints = controlPoints.length;
    let pointType: ControlPointType = 'WAYPOINT';

    // Pierwszy punkt = START, domyślnie
    if (numPoints === 0) {
      pointType = 'START';
    }

    const newPoint: ControlPoint = {
      lat,
      lon: lng,
      type: pointType,
      desc: ''
    };

    setControlPoints(prev => {
      const updated = [...prev, newPoint];
      // Jeśli więcej niż 1 punkt, ostatni automatycznie staje się FINISH
      if (updated.length > 1) {
        // Poprzedni ostatni punkt - jeśli był FINISH, zmień na WAYPOINT
        if (updated[updated.length - 2].type === 'FINISH') {
          updated[updated.length - 2] = { ...updated[updated.length - 2], type: 'WAYPOINT' };
        }
        // Nowy ostatni punkt = FINISH
        updated[updated.length - 1] = { ...updated[updated.length - 1], type: 'FINISH' };
      }
      return updated;
    });

    if (expandedSection !== 'route') setExpandedSection('route');
  };

  const removePoint = (index: number) => {
    setControlPoints(prev => {
      const updated = prev.filter((_, i) => i !== index);
      // Zaktualizuj typy po usunięciu
      if (updated.length > 0) {
        updated[0] = { ...updated[0], type: 'START' };
        if (updated.length > 1) {
          updated[updated.length - 1] = { ...updated[updated.length - 1], type: 'FINISH' };
        }
      }
      return updated;
    });
    setEditingPointIndex(null);
  };

  const updatePoint = (index: number, updates: Partial<ControlPoint>) => {
    setControlPoints(prev => prev.map((p, i) => i === index ? { ...p, ...updates } : p));
  };

  // Konwersja ControlPoints na format dla API/mapy
  const getRoutePointsForApi = () => controlPoints.map(p => ({ lat: p.lat, lon: p.lon }));
  const getMarkersForMap = (): [number, number][] => controlPoints.map(p => [p.lat, p.lon]);

  // ========================================
  // GŁÓWNY WORKFLOW OBLICZANIA TRASY
  // ========================================
  const handleCalculateRoute = async () => {
    if (controlPoints.length < 2 || !selectedYachtId) return;

    setIsCalculating(true);
    setError(null);
    setCalcStatus({ step: 'mesh', message: 'Tworzenie siatki nawigacyjnej...' });

    try {
      // ============ KROK 1: Tworzenie MESH ============
      console.log("🔷 KROK 1: Tworzenie mesh...");

      // Oblicz rozmiar obszaru
      const latSpan = Math.max(...controlPoints.map(p => p.lat)) - Math.min(...controlPoints.map(p => p.lat));
      const lonSpan = Math.max(...controlPoints.map(p => p.lon)) - Math.min(...controlPoints.map(p => p.lon));
      const spanNm = Math.max(latSpan, lonSpan) * 60; // przybliżone nm
      const numPoints = controlPoints.length;

      // Oblicz minimalną odległość między sąsiednimi punktami (w nm)
      let minSegmentNm = Infinity;
      for (let i = 0; i < controlPoints.length - 1; i++) {
        const p1 = controlPoints[i];
        const p2 = controlPoints[i + 1];
        const dLat = (p2.lat - p1.lat) * 60; // nm
        const dLon = (p2.lon - p1.lon) * 60 * Math.cos(p1.lat * Math.PI / 180); // nm z korekcją szerokości
        const dist = Math.sqrt(dLat * dLat + dLon * dLon);
        if (dist < minSegmentNm) minSegmentNm = dist;
      }

      console.log(`📊 Trasa: ${numPoints} punktów, span: ${spanNm.toFixed(2)} nm, min segment: ${minSegmentNm.toFixed(3)} nm`);

      let corridorNm, ring1, ring2, ring3, area1, area2, area3, maxWeatherPts, weatherGrid, shorelineAvoid;

      if (useAutoMesh) {
        // KLUCZOWE: Korytarz nie może być większy niż 40% najkrótszego segmentu
        const maxCorridorFromSegment = minSegmentNm * 0.4;

        if (minSegmentNm < 0.3 || spanNm < 1) {
          console.log("⚡ Tryb AUTO: MICRO");
          corridorNm = Math.min(0.1, maxCorridorFromSegment);
          ring1 = 50; ring2 = 100; ring3 = 200;
          area1 = 200; area2 = 500; area3 = 1000;
          maxWeatherPts = 5; weatherGrid = 0.5; shorelineAvoid = 50;
        } else if (minSegmentNm < 1.0 || spanNm < 3) {
          console.log("⚡ Tryb AUTO: MALY");
          corridorNm = Math.min(0.3, maxCorridorFromSegment);
          ring1 = 100; ring2 = 250; ring3 = 500;
          area1 = 500; area2 = 1500; area3 = 4000;
          maxWeatherPts = 10; weatherGrid = 1.0; shorelineAvoid = 100;
        } else if (spanNm < 8) {
          console.log("⚡ Tryb AUTO: SREDNI");
          corridorNm = Math.min(1.0, maxCorridorFromSegment);
          ring1 = 300; ring2 = 800; ring3 = 1500;
          area1 = 2000; area2 = 8000; area3 = 25000;
          maxWeatherPts = 20; weatherGrid = 2.0; shorelineAvoid = 150;
        } else {
          console.log("⚡ Tryb AUTO: STANDARDOWY");
          corridorNm = Math.min(3.0, spanNm * 0.15, maxCorridorFromSegment);
          ring1 = 500; ring2 = 1500; ring3 = 3000;
          area1 = 3000; area2 = 15000; area3 = 60000;
          maxWeatherPts = 40; weatherGrid = 5.0; shorelineAvoid = 200;
        }
      } else {
        // Użyj ręcznych ustawień
        console.log("⚡ Tryb: RECZNY");
        corridorNm = meshSettings.corridor_nm;
        ring1 = meshSettings.ring1_m;
        ring2 = meshSettings.ring2_m;
        ring3 = meshSettings.ring3_m;
        area1 = meshSettings.area1;
        area2 = meshSettings.area2;
        area3 = meshSettings.area3;
        maxWeatherPts = meshSettings.max_weather_points;
        weatherGrid = meshSettings.weather_grid_km;
        shorelineAvoid = meshSettings.shoreline_avoid_m;
      }

      console.log(`📐 Corridor: ${corridorNm.toFixed(3)} nm`);

      const meshPayload = {
        user_id: "3fa85f64-5717-4562-b3fc-2c963f66afa6", // TODO: prawdziwy user ID
        yacht_id: selectedYachtId,
        points: controlPoints.map((p, idx) => ({
          lat: p.lat,
          lon: p.lon,
          type: p.type,
          width: p.width || null,
          desc: p.desc || null,
          timestamp: null
        })),
        corridor_nm: corridorNm,
        ring1_m: ring1,
        ring2_m: ring2,
        ring3_m: ring3,
        area1: area1,
        area2: area2,
        area3: area3,
        shoreline_avoid_m: shorelineAvoid,
        enable_weather_optimization: true,
        max_weather_points: maxWeatherPts,
        weather_grid_km: weatherGrid,
        weather_clustering_method: "kmeans"
      };

      console.log("📤 Mesh payload:", meshPayload);

      // Bez timeoutu - czekamy na backend
      const meshRes = await fetch(`${API_URL}/routes_mesh/mesh`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(meshPayload)
      });

      if (!meshRes.ok) {
        const errText = await meshRes.text();
        let errorMsg = errText;
        try {
          const errJson = JSON.parse(errText);
          errorMsg = errJson.detail || errJson.message || errText;
        } catch {}
        throw new Error(`Blad tworzenia siatki: ${errorMsg}`);
      }

      const meshData = await meshRes.json();
      const meshedAreaId = meshData.meshed_area_id;

      console.log("✅ Mesh utworzony:", meshedAreaId);
      setCalcStatus({
        step: 'weather',
        message: 'Pobieranie danych pogodowych...',
        meshedAreaId
      });

      // ============ KROK 2: Pobieranie pogody ============
      console.log("🔷 KROK 2: Pobieranie pogody dla mesh:", meshedAreaId);

      const weatherRes = await fetch(`${API_URL}/weather/${meshedAreaId}/fetch-weather`, {
        method: 'POST'
      });

      if (!weatherRes.ok) {
        const errText = await weatherRes.text();
        let errorMsg = errText;
        try {
          const errJson = JSON.parse(errText);
          errorMsg = errJson.detail || errJson.message || errText;
        } catch {}
        throw new Error(`Blad pobierania pogody: ${errorMsg}`);
      }

      const weatherData = await weatherRes.json();
      console.log("✅ Pogoda pobrana:", weatherData);

      const numVariants = useTimeWindow ? startWindow.checkCount : 1;
      setCalcStatus({
        step: 'routing',
        message: `Obliczanie optymalnej trasy (${numVariants} wariant${numVariants > 1 ? 'ów' : ''})...`,
        meshedAreaId
      });

      // ============ KROK 3: Obliczanie trasy ============
      console.log("🔷 KROK 3: Obliczanie trasy...");

      // Payload zgodny z TimeWindowRequest schema
      let routingPayload;

      if (useTimeWindow) {
        // Użyj ustawionego okna czasowego
        routingPayload = {
          start_time: new Date(startWindow.start).toISOString(),
          end_time: new Date(startWindow.end).toISOString(),
          num_checks: startWindow.checkCount
        };
      } else {
        // Start natychmiast - aktualny czas warszawski, +1 minuta, 1 sprawdzenie
        const now = new Date();
        const oneMinuteLater = new Date(now.getTime() + 60 * 1000);
        routingPayload = {
          start_time: now.toISOString(),
          end_time: oneMinuteLater.toISOString(),
          num_checks: 1
        };
      }

      console.log("📤 Routing payload:", routingPayload);

      // Endpoint: /calculate-route - obliczenia mogą trwać dłużej
      const routingRes = await fetch(`${API_URL}/routing/${meshedAreaId}/calculate-route`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(routingPayload)
      });

      if (!routingRes.ok) {
        const errText = await routingRes.text();
        // Parsuj błąd z backendu jeśli to JSON
        let errorMsg = errText;
        try {
          const errJson = JSON.parse(errText);
          errorMsg = errJson.detail || errJson.message || errText;
        } catch {}
        throw new Error(`Blad obliczania trasy: ${errorMsg}`);
      }

      const routeResult = await routingRes.json();
      console.log("✅ Trasa obliczona:", routeResult);

      // NIE czyść punktów kontrolnych - pokazujemy je na trasie

      // Zbierz waypoints, segments i tack points dla wszystkich wariantów
      const waypointsMap: Record<string, [number, number][]> = {};
      const segmentsMap: Record<string, RouteSegment[]> = {};
      const tackPointsMap: Record<string, TackPoint[]> = {};

      // Funkcja do wykrywania zwrotów/przejść na podstawie TWA
      const detectTackPoints = (segments: RouteSegment[]): TackPoint[] => {
        const points: TackPoint[] = [];
        for (let i = 1; i < segments.length; i++) {
          const prevSeg = segments[i - 1];
          const currSeg = segments[i];
          const prevTwa = prevSeg.twa;
          const currTwa = currSeg.twa;

          // Sprawdź czy TWA zmienił znak (przeszliśmy przez wiatr)
          if ((prevTwa > 0 && currTwa < 0) || (prevTwa < 0 && currTwa > 0)) {
            let bearingChange = Math.abs(currSeg.bearing - prevSeg.bearing);
            if (bearingChange > 180) bearingChange = 360 - bearingChange;

            // Tack jeśli TWA < 90, Jibe jeśli TWA > 90
            const isTack = Math.abs(prevTwa) < 90 || Math.abs(currTwa) < 90;

            points.push({
              lat: currSeg.from.lat,
              lon: currSeg.from.lon,
              type: isTack ? 'tack' : 'jibe',
              from_twa: prevTwa,
              to_twa: currTwa,
              bearing_change: bearingChange
            });
          }
        }
        return points;
      };

      // Sprawdź czy response zawiera waypoints i segments
      for (const variant of routeResult.variants) {
        if (variant.waypoints_wgs84 && variant.waypoints_wgs84.length > 0) {
          // waypoints są w formacie [lon, lat], konwertujemy na [lat, lon] dla Leaflet
          waypointsMap[variant.variant_id] = variant.waypoints_wgs84.map(
            (wp: [number, number]) => [wp[1], wp[0]] as [number, number]
          );
        }

        // Pobierz segments jeśli są dostępne
        if (variant.segments && variant.segments.length > 0) {
          segmentsMap[variant.variant_id] = variant.segments;
          tackPointsMap[variant.variant_id] = detectTackPoints(variant.segments);
        }
      }

      // Jeśli brak waypoints/segments w response, pobierz z calculated-route
      if (Object.keys(waypointsMap).length === 0) {
        const waypointsRes = await fetch(`${API_URL}/routing/${meshedAreaId}/calculated-route`);
        if (waypointsRes.ok) {
          const waypointsData = await waypointsRes.json();
          console.log("📍 Waypoints from calculated-route:", waypointsData);

          if (waypointsData.data?.route && routeResult.best_variant) {
            const routeData = waypointsData.data.route;
            const variantId = routeResult.best_variant.variant_id;

            if (routeData.waypoints_wgs84) {
              waypointsMap[variantId] = routeData.waypoints_wgs84.map(
                (wp: [number, number]) => [wp[1], wp[0]] as [number, number]
              );
            }

            if (routeData.segments && routeData.segments.length > 0) {
              // Konwertuj segments z backendu
              const segments: RouteSegment[] = routeData.segments.map((seg: any) => ({
                from: { lat: seg.from.lat, lon: seg.from.lon },
                to: { lat: seg.to.lat, lon: seg.to.lon },
                bearing: seg.bearing,
                distance_nm: seg.distance_nm,
                time_seconds: seg.time_seconds,
                boat_speed_knots: seg.boat_speed_knots,
                wind_speed_knots: seg.wind_speed_knots,
                wind_direction: seg.wind_direction,
                twa: seg.twa,
                point_of_sail: seg.point_of_sail,
                wave_height_m: seg.wave_height_m
              }));
              segmentsMap[variantId] = segments;
              tackPointsMap[variantId] = detectTackPoints(segments);
            }
          }
        }
      }

      console.log("📍 Waypoints map:", waypointsMap);
      console.log("📍 Segments map:", segmentsMap);
      console.log("📍 Tack points map:", tackPointsMap);

      setVariantWaypoints(waypointsMap);
      setVariantSegments(segmentsMap);
      setVariantTackPoints(tackPointsMap);

      // Zaznacz wszystkie warianty które mają waypoints
      const variantIdsWithWaypoints = Object.keys(waypointsMap);
      if (variantIdsWithWaypoints.length > 0) {
        setSelectedVariantIds(variantIdsWithWaypoints);
      } else if (routeResult.best_variant) {
        setSelectedVariantIds([routeResult.best_variant.variant_id]);
      }

      setCalcStatus({
        step: 'done',
        message: 'Trasa obliczona pomyślnie!',
        meshedAreaId,
        routeResult
      });

      // Otwórz sekcję wyników
      setExpandedSection('results');

    } catch (err) {
      console.error("❌ Błąd:", err);
      setError(err instanceof Error ? err.message : "Błąd obliczania trasy");
      setCalcStatus({
        step: 'error',
        message: err instanceof Error ? err.message : "Nieznany błąd"
      });
    } finally {
      setIsCalculating(false);
    }
  };

  const toggleSection = (section: 'yachts' | 'route' | 'startWindow' | 'results' | 'settings') => {
    setExpandedSection(expandedSection === section ? null : section);
  };

  const getActiveYachtName = () => {
    const y = allYachts.find(y => y.id === selectedYachtId);
    return y ? y.name : "Wybierz jacht";
  };

  // Helper: czy wszystko gotowe do obliczenia
  const canCalculate = selectedYachtId && controlPoints.length >= 2 && !isCalculating;

  // Helper: progress indicator
  const getStepProgress = () => {
    switch(calcStatus.step) {
      case 'mesh': return 33;
      case 'weather': return 66;
      case 'routing': return 90;
      case 'done': return 100;
      default: return 0;
    }
  };

  // Helper: format duration
  const formatDuration = (hours: number): string => {
    const h = Math.floor(hours);
    const m = Math.round((hours - h) * 60);
    return h > 0 ? `${h}h ${m}m` : `${m}m`;
  };

  // Helper: format datetime
  const formatDateTime = (isoString: string): string => {
    const date = new Date(isoString);
    return date.toLocaleString('pl-PL', {
      day: 'numeric',
      month: 'short',
      hour: '2-digit',
      minute: '2-digit'
    });
  };

  // Helper: difficulty color
  const getDifficultyColor = (level: string): string => {
    switch (level?.toLowerCase()) {
      case 'easy': return 'text-green-600 bg-green-100';
      case 'moderate': return 'text-yellow-600 bg-yellow-100';
      case 'challenging': return 'text-orange-600 bg-orange-100';
      case 'difficult': return 'text-red-600 bg-red-100';
      case 'extreme': return 'text-purple-600 bg-purple-100';
      default: return 'text-slate-600 bg-slate-100';
    }
  };

  // Helper: get point type icon and label
  const getPointTypeInfo = (type: ControlPointType) => {
    switch (type) {
      case 'START': return { icon: '🟢', label: 'Start', color: 'text-green-600' };
      case 'FINISH': return { icon: '🏁', label: 'Meta', color: 'text-red-600' };
      case 'WAYPOINT': return { icon: '📍', label: 'Punkt', color: 'text-blue-600' };
      case 'MARK': return { icon: '🔶', label: 'Boja', color: 'text-orange-600' };
      case 'GATE': return { icon: '⛳', label: 'Bramka', color: 'text-purple-600' };
      default: return { icon: '📍', label: 'Punkt', color: 'text-slate-600' };
    }
  };

  // Handler: toggle variant selection
  const handleVariantToggle = async (variantId: string) => {
    const isSelected = selectedVariantIds.includes(variantId);

    if (isSelected) {
      // Odznacz
      setSelectedVariantIds(prev => prev.filter(id => id !== variantId));
    } else {
      // Zaznacz i pobierz waypoints jeśli nie ma
      setSelectedVariantIds(prev => [...prev, variantId]);

      // Pobierz waypoints dla tego wariantu jeśli ich nie mamy
      if (!variantWaypoints[variantId] && calcStatus.meshedAreaId) {
        try {
          const res = await fetch(`${API_URL}/routing/${calcStatus.meshedAreaId}/variants`);
          if (res.ok) {
            const data = await res.json();
            // TODO: Backend powinien zwracać waypoints per variant
            // Na razie używamy calculated-route dla best variant
          }
        } catch (err) {
          console.error('Error fetching variant waypoints:', err);
        }
      }
    }
  };

  // Handler: select all variants
  const handleSelectAllVariants = () => {
    if (calcStatus.routeResult) {
      const allIds = calcStatus.routeResult.variants.map(v => v.variant_id);
      setSelectedVariantIds(allIds);
    }
  };

  // Handler: start new route calculation
  const handleNewRoute = () => {
    setCalcStatus({ step: 'idle', message: '', routeResult: null });
    setSelectedVariantIds([]);
    setVariantWaypoints({});
    setVariantSegments({});
    setVariantTackPoints({});
    setControlPoints([]);
    setEditingPointIndex(null);
    setExpandedSection('yachts');
  };

  // Handler: otwórz pełną wizualizację
  const handleViewVisualization = (meshedAreaId: string) => {
    window.open(`${API_URL}/visualise/${meshedAreaId}/route/view?show_all_variants=false`, '_blank');
  };

  // Oblicz trasy do wyświetlenia na mapie (z segmentami)
  const calculatedRoutes = selectedVariantIds
    .filter(id => variantWaypoints[id])
    .map((id, index) => ({
      waypoints: variantWaypoints[id],
      segments: variantSegments[id],
      variantIndex: index
    }));

  // Handler: zamknij splash screen
  const handleSplashFinish = useCallback(() => {
    setShowSplash(false);
  }, []);

  // Pokaż splash screen
  if (showSplash) {
    return <SplashScreen onFinish={handleSplashFinish} minDuration={2500} />;
  }

  return (
    <main className="flex h-screen w-screen flex-col font-sans relative overflow-hidden">
      {isCalculating && <LoadingOverlay message={calcStatus.message} progress={getStepProgress()} />}

      {/* HEADER */}
      <div className="h-16 bg-slate-900 text-white flex items-center px-6 justify-between z-10 shadow-lg border-b border-slate-700">
        <h1 className="font-semibold text-lg tracking-wide">Sailing Route Calculator</h1>
        <div className="text-xs text-slate-400">
            Jacht: <span className="text-white font-bold ml-1">{getActiveYachtName()}</span>
        </div>
      </div>

      <div className="flex-grow relative">
        <SailingMap
          controlPoints={controlPoints}
          onMapClick={addPoint}
          calculatedRoutes={calculatedRoutes}
          isRouteCalculated={!!calcStatus.routeResult}
        />

        {/* SIDEBAR */}
        <div className="absolute top-4 right-4 bg-white/95 backdrop-blur-sm rounded-lg shadow-xl z-[1000] w-96 max-h-[85vh] flex flex-col border border-slate-200 transition-all overflow-hidden">

            {/* ERROR MESSAGE */}
            {error && (
              <div className="bg-red-100 border-b border-red-300 text-red-700 px-4 py-2 text-xs">
                {error}
                <button onClick={() => setError(null)} className="float-right font-bold">×</button>
              </div>
            )}

            {/* SUCCESS MESSAGE */}
            {calcStatus.step === 'done' && calcStatus.routeResult && (
              <div className="bg-green-100 border-b border-green-300 text-green-800 px-4 py-3 text-xs">
                <div className="font-bold mb-1">Trasa obliczona pomyslnie!</div>
                <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-[11px]">
                  <div>Wariantow: <span className="font-medium">{calcStatus.routeResult.variants_count}</span></div>
                  <div>Trudnosc: <span className="font-medium">{calcStatus.routeResult.difficulty.level}</span></div>
                  {calcStatus.routeResult.best_variant && (
                    <>
                      <div>Najlepszy czas: <span className="font-medium">{formatDuration(calcStatus.routeResult.best_variant.total_time_hours)}</span></div>
                      <div>Dystans: <span className="font-medium">{calcStatus.routeResult.best_variant.total_distance_nm.toFixed(1)} nm</span></div>
                    </>
                  )}
                </div>
              </div>
            )}

            {/* SEKCJA 1: JACHTY */}
            <div className="border-b border-slate-200 flex flex-col">
                <button onClick={() => toggleSection('yachts')} className="p-4 flex justify-between bg-slate-50 hover:bg-slate-100">
                    <span className="font-bold text-slate-800">Jachty</span>
                    <span className="text-slate-400">{expandedSection === 'yachts' ? '▲' : '▼'}</span>
                </button>

                {expandedSection === 'yachts' && (
                    <div className="bg-white">
                        {!isAddingYacht ? (
                            <>
                                {/* ZAKŁADKI */}
                                <div className="flex border-b border-slate-200">
                                    <button
                                        onClick={() => setActiveTab('presets')}
                                        className={`flex-1 py-2 text-xs font-bold transition-colors ${activeTab === 'presets' ? 'text-blue-600 border-b-2 border-blue-600 bg-blue-50' : 'text-slate-500 hover:bg-slate-50'}`}
                                    >
                                        PRESETY ({presetYachts.length})
                                    </button>
                                    <button
                                        onClick={() => setActiveTab('my')}
                                        className={`flex-1 py-2 text-xs font-bold transition-colors ${activeTab === 'my' ? 'text-blue-600 border-b-2 border-blue-600 bg-blue-50' : 'text-slate-500 hover:bg-slate-50'}`}
                                    >
                                        MOJE ({myYachts.length})
                                    </button>
                                </div>

                                {/* LISTA JACHTÓW */}
                                <div className="max-h-[200px] overflow-y-auto custom-scrollbar p-3 space-y-2">
                                    {(activeTab === 'presets' ? presetYachts : myYachts).length === 0 && (
                                        <p className="text-xs text-center text-slate-400 py-4">
                                          {activeTab === 'presets'
                                            ? "Ładowanie presetów..."
                                            : "Brak jachtów. Kliknij 'Dodaj Nowy Jacht'."}
                                        </p>
                                    )}

                                    {(activeTab === 'presets' ? presetYachts : myYachts).map(yacht => (
                                        <div
                                            key={yacht.id}
                                            onClick={() => setSelectedYachtId(yacht.id)}
                                            className={`
                                                relative p-3 rounded border cursor-pointer flex items-center gap-3 transition-all
                                                ${selectedYachtId === yacht.id ? 'border-blue-500 bg-blue-50 shadow-sm' : 'border-slate-200 hover:border-blue-300'}
                                            `}
                                        >
                                            <div className="w-8 h-8 bg-blue-100 rounded-full flex items-center justify-center text-blue-600 text-xs font-bold">Y</div>
                                            <div className="flex-grow">
                                                <div className="font-bold text-sm text-slate-800">{yacht.name}</div>
                                                <div className="text-[10px] text-slate-500">{yacht.yacht_type} • L:{yacht.length}ft • Max:{yacht.max_speed}kt</div>
                                            </div>

                                            {selectedYachtId === yacht.id && <div className="text-blue-600 text-lg font-bold">✓</div>}

                                            {activeTab === 'my' && (
                                                <button
                                                    onClick={(e) => handleDeleteYacht(e, yacht.id)}
                                                    className="absolute top-1 right-1 p-1 text-slate-300 hover:text-red-500 transition-colors"
                                                >✕</button>
                                            )}
                                        </div>
                                    ))}
                                </div>

                                {activeTab === 'my' && (
                                    <div className="p-3 pt-0 border-t border-slate-100 mt-2">
                                        <button
                                            onClick={() => setIsAddingYacht(true)}
                                            className="w-full py-2 border-2 border-dashed border-slate-300 text-slate-500 rounded hover:border-blue-400 hover:text-blue-600 text-xs font-bold transition-all"
                                        >
                                            + Dodaj Nowy Jacht
                                        </button>
                                    </div>
                                )}
                            </>
                        ) : (
                            /* FORMULARZ DODAWANIA */
                            <div className="p-4 space-y-3 bg-slate-50">
                                <h4 className="font-bold text-sm text-slate-800 border-b pb-2">Nowy Jacht</h4>

                                <div>
                                    <label className="text-[10px] text-slate-500 uppercase font-bold">Nazwa *</label>
                                    <input type="text" className="w-full border p-1.5 text-sm rounded focus:ring-1 focus:ring-blue-500 outline-none text-slate-800 placeholder:text-slate-400"
                                        placeholder="Np. Mój Jacht"
                                        value={newYachtData.name} onChange={e => setNewYachtData({...newYachtData, name: e.target.value})} />
                                </div>

                                <div>
                                    <label className="text-[10px] text-slate-500 uppercase font-bold">Typ</label>
                                    <select
                                        className="w-full border p-1.5 text-sm rounded focus:ring-1 focus:ring-blue-500 outline-none text-slate-800"
                                        value={newYachtData.yacht_type}
                                        onChange={e => setNewYachtData({...newYachtData, yacht_type: e.target.value})}
                                    >
                                        <option value="Sailboat">Sailboat</option>
                                        <option value="Class 40">Class 40</option>
                                        <option value="Omega">Omega</option>
                                        <option value="catamaran">Catamaran</option>
                                        <option value="trimaran">Trimaran</option>
                                        <option value="open_60">Open 60</option>
                                    </select>
                                </div>

                                <div className="grid grid-cols-2 gap-2">
                                    <div>
                                        <label className="text-[10px] text-slate-500 uppercase font-bold">Długość (ft)</label>
                                        <input type="number" className="w-full border p-1.5 text-sm rounded focus:ring-1 focus:ring-blue-500 outline-none text-slate-800"
                                            value={newYachtData.length} onChange={e => setNewYachtData({...newYachtData, length: parseFloat(e.target.value) || 0})} />
                                    </div>
                                    <div>
                                        <label className="text-[10px] text-slate-500 uppercase font-bold">Szerokość (m)</label>
                                        <input type="number" className="w-full border p-1.5 text-sm rounded focus:ring-1 focus:ring-blue-500 outline-none text-slate-800"
                                             value={newYachtData.beam} onChange={e => setNewYachtData({...newYachtData, beam: parseFloat(e.target.value) || 0})} />
                                    </div>
                                    <div>
                                        <label className="text-[10px] text-slate-500 uppercase font-bold">Zanurzenie (m)</label>
                                        <input type="number" className="w-full border p-1.5 text-sm rounded focus:ring-1 focus:ring-blue-500 outline-none text-slate-800"
                                             value={newYachtData.draft} onChange={e => setNewYachtData({...newYachtData, draft: parseFloat(e.target.value) || 0})} />
                                    </div>
                                    <div>
                                        <label className="text-[10px] text-slate-500 uppercase font-bold">Załoga</label>
                                        <input type="number" className="w-full border p-1.5 text-sm rounded focus:ring-1 focus:ring-blue-500 outline-none text-slate-800"
                                             value={newYachtData.amount_of_crew} onChange={e => setNewYachtData({...newYachtData, amount_of_crew: parseInt(e.target.value) || 1})} />
                                    </div>
                                    <div>
                                        <label className="text-[10px] text-slate-500 uppercase font-bold">Max Prędkość (kt)</label>
                                        <input type="number" className="w-full border p-1.5 text-sm rounded focus:ring-1 focus:ring-blue-500 outline-none text-slate-800"
                                             value={newYachtData.max_speed} onChange={e => setNewYachtData({...newYachtData, max_speed: parseFloat(e.target.value) || 0})} />
                                    </div>
                                    <div>
                                        <label className="text-[10px] text-slate-500 uppercase font-bold">Max Wiatr (kt)</label>
                                        <input type="number" className="w-full border p-1.5 text-sm rounded focus:ring-1 focus:ring-blue-500 outline-none text-slate-800"
                                             value={newYachtData.max_wind_speed} onChange={e => setNewYachtData({...newYachtData, max_wind_speed: parseFloat(e.target.value) || 0})} />
                                    </div>
                                </div>

                                <div className="flex items-center gap-4 pt-1">
                                    <label className="flex items-center gap-1 text-xs text-slate-600">
                                        <input type="checkbox" checked={newYachtData.has_spinnaker} onChange={e => setNewYachtData({...newYachtData, has_spinnaker: e.target.checked})} />
                                        Spinnaker
                                    </label>
                                    <label className="flex items-center gap-1 text-xs text-slate-600">
                                        <input type="checkbox" checked={newYachtData.has_genaker} onChange={e => setNewYachtData({...newYachtData, has_genaker: e.target.checked})} />
                                        Genaker
                                    </label>
                                </div>

                                <div className="flex gap-2 pt-2">
                                    <button onClick={() => setIsAddingYacht(false)} className="flex-1 py-2 bg-white border border-slate-300 text-slate-600 rounded text-xs font-bold hover:bg-slate-100">Anuluj</button>
                                    <button
                                        onClick={handleCreateYacht}
                                        disabled={!newYachtData.name.trim()}
                                        className="flex-1 py-2 bg-blue-600 text-white rounded text-xs font-bold hover:bg-blue-700 shadow-sm disabled:bg-slate-300 disabled:cursor-not-allowed"
                                    >
                                        Zapisz Jacht
                                    </button>
                                </div>
                            </div>
                        )}
                    </div>
                )}
            </div>

            {/* SEKCJA 2: TRASA (Punkty kontrolne) */}
            <div className="border-b border-slate-200">
                <button onClick={() => toggleSection('route')} className="p-4 w-full flex justify-between bg-slate-50 hover:bg-slate-100">
                    <span className="font-bold text-slate-800">Trasa ({controlPoints.length} pkt)</span>
                    <span className="text-slate-400">{expandedSection === 'route' ? '▲' : '▼'}</span>
                </button>
                {expandedSection === 'route' && (
                   <div className="p-3 bg-white max-h-[250px] overflow-y-auto custom-scrollbar">
                      {calcStatus.routeResult ? (
                        <div className="space-y-2">
                          <p className="text-xs text-slate-500 italic mb-2">
                            Trasa obliczona. Punkty kontrolne:
                          </p>
                          {controlPoints.map((p, i) => {
                            const typeInfo = getPointTypeInfo(p.type);
                            return (
                              <div key={i} className="bg-slate-50 rounded p-2 text-xs">
                                <div className="flex items-center gap-2">
                                  <span>{typeInfo.icon}</span>
                                  <span className={`font-medium ${typeInfo.color}`}>{typeInfo.label}</span>
                                  <span className="text-slate-500 font-mono text-[10px]">
                                    {p.lat.toFixed(4)}, {p.lon.toFixed(4)}
                                  </span>
                                </div>
                                {p.desc && <div className="text-slate-600 mt-1 pl-5">{p.desc}</div>}
                                {p.width && <div className="text-slate-400 mt-0.5 pl-5">Szer. bramki: {p.width}m</div>}
                              </div>
                            );
                          })}
                        </div>
                      ) : controlPoints.length === 0 ? (
                        <p className="text-xs text-slate-400 italic">Kliknij na mapie by dodac punkty kontrolne.</p>
                      ) : (
                        <div className="space-y-2">
                          {controlPoints.map((p, i) => {
                            const typeInfo = getPointTypeInfo(p.type);
                            const isEditing = editingPointIndex === i;

                            return (
                              <div key={i} className={`rounded border ${isEditing ? 'border-blue-300 bg-blue-50' : 'border-slate-200 bg-slate-50'} p-2`}>
                                {/* Header */}
                                <div className="flex justify-between items-center">
                                  <div className="flex items-center gap-2">
                                    <span>{typeInfo.icon}</span>
                                    <span className={`font-medium text-xs ${typeInfo.color}`}>{typeInfo.label}</span>
                                    <span className="text-slate-400 font-mono text-[10px]">
                                      {p.lat.toFixed(4)}, {p.lon.toFixed(4)}
                                    </span>
                                  </div>
                                  <div className="flex gap-1">
                                    <button
                                      onClick={() => setEditingPointIndex(isEditing ? null : i)}
                                      className={`text-xs px-1.5 py-0.5 rounded ${isEditing ? 'bg-blue-500 text-white' : 'bg-slate-200 text-slate-600 hover:bg-slate-300'}`}
                                      title="Edytuj"
                                    >
                                      {isEditing ? '✓' : '✎'}
                                    </button>
                                    <button
                                      onClick={() => removePoint(i)}
                                      className="text-xs px-1.5 py-0.5 rounded bg-red-100 text-red-600 hover:bg-red-200"
                                      title="Usun"
                                    >
                                      ×
                                    </button>
                                  </div>
                                </div>

                              {/* Edit form */}
                              {isEditing && (
                                  <div className="mt-2 pt-2 border-t border-blue-200 space-y-2">
                                    {/* Typ punktu */}
                                    <div>
                                      <label className="text-[10px] text-slate-500 block mb-1">Typ punktu</label>
                                      <select
                                          value={p.type}
                                          onChange={e => updatePoint(i, {type: e.target.value as ControlPointType})}
                                          className="w-full text-xs border rounded px-2 py-1 text-slate-800"
                                          disabled={i === 0 || i === controlPoints.length - 1}
                                      >
                                        {/* Logika wyświetlania opcji zależna od pozycji punktu */}
                                        {i === 0 ? (
                                            <option value="START">Start</option>
                                        ) : i === controlPoints.length - 1 ? (
                                            <option value="FINISH">Meta</option>
                                        ) : (
                                            <>
                                              <option value="WAYPOINT">Punkt nawigacyjny</option>
                                              <option value="MARK">Boja/Znak</option>
                                              <option value="GATE">Bramka</option>
                                            </>
                                        )}
                                      </select>
                                    </div>

                                    {/* Szerokość bramki */}
                                    {(p.type === 'GATE' || p.type === 'START' || p.type === 'FINISH') && (
                                        <div>
                                          <label className="text-[10px] text-slate-500 block mb-1">Szerokosc (m)</label>
                                          <input
                                              type="number"
                                              min="0"
                                              value={p.width || ''}
                                              onChange={e => {
                                                const val = parseFloat(e.target.value);
                                                const safeValue = val < 0 ? 0 : val;

                                                updatePoint(i, {
                                                  width: isNaN(safeValue) ? undefined : safeValue
                                                });
                                              }}
                                              placeholder="np. 50"
                                              className="w-full text-xs border rounded px-2 py-1 text-slate-800 placeholder:text-slate-400"
                                          />
                                        </div>
                                    )}

                                    {/* Opis */}
                                    <div>
                                      <label className="text-[10px] text-slate-500 block mb-1">Opis
                                        (opcjonalnie)</label>
                                      <input
                                          type="text"
                                          value={p.desc || ''}
                                          onChange={e => updatePoint(i, {desc: e.target.value || undefined})}
                                          placeholder="np. Boja startowa A"
                                          className="w-full text-xs border rounded px-2 py-1 text-slate-800 placeholder:text-slate-400"
                                      />
                                    </div>
                                  </div>
                              )}
                              </div>
                            );
                          })}

                          {controlPoints.length > 0 && (
                              <button
                                  onClick={() => setControlPoints([])}
                                  className="text-xs text-red-500 mt-2 hover:underline"
                              >
                                Wyczysc wszystkie punkty
                              </button>
                          )}
                        </div>
                      )}
                   </div>
                )}
            </div>

          {/* SEKCJA 2.5: USTAWIENIA SIATKI */}
          <div className="border-b border-slate-200">
            <button onClick={() => toggleSection('meshSettings')}
                    className="p-4 w-full flex justify-between bg-slate-50 hover:bg-slate-100">
                    <span className="font-bold text-slate-800">Ustawienia Siatki</span>
                    <span className="text-slate-400">{expandedSection === 'meshSettings' ? '▲' : '▼'}</span>
                </button>
                {expandedSection === 'meshSettings' && (
                   <div className="p-3 bg-white space-y-3">
                      {/* Auto/Manual toggle */}
                      <label className="flex items-center gap-2 cursor-pointer">
                        <input
                          type="checkbox"
                          checked={useAutoMesh}
                          onChange={e => setUseAutoMesh(e.target.checked)}
                          className="w-4 h-4 text-blue-600 rounded"
                        />
                        <span className="text-sm text-slate-700 font-medium">Automatyczne parametry</span>
                      </label>

                      {useAutoMesh ? (
                        <div className="bg-green-50 border border-green-200 rounded p-2 text-xs text-green-700">
                          Parametry siatki beda dostosowane automatycznie do wielkosci trasy.
                        </div>
                      ) : (
                        <div className="space-y-2">
                          <div className="grid grid-cols-2 gap-2">
                            <div>
                              <label className="text-[10px] text-slate-500 block mb-1">Korytarz (nm)</label>
                              <input
                                type="number"
                                step="0.1"
                                value={meshSettings.corridor_nm}
                                onChange={e => setMeshSettings(s => ({ ...s, corridor_nm: Number(e.target.value) }))}
                                className="w-full text-xs border rounded px-2 py-1 text-slate-800"
                              />
                            </div>
                            <div>
                              <label className="text-[10px] text-slate-500 block mb-1">Unikaj brzegu (m)</label>
                              <input
                                type="number"
                                value={meshSettings.shoreline_avoid_m}
                                onChange={e => setMeshSettings(s => ({ ...s, shoreline_avoid_m: Number(e.target.value) }))}
                                className="w-full text-xs border rounded px-2 py-1 text-slate-800"
                              />
                            </div>
                          </div>

                          <div className="grid grid-cols-3 gap-2">
                            <div>
                              <label className="text-[10px] text-slate-500 block mb-1">Ring 1 (m)</label>
                              <input
                                type="number"
                                value={meshSettings.ring1_m}
                                onChange={e => setMeshSettings(s => ({ ...s, ring1_m: Number(e.target.value) }))}
                                className="w-full text-xs border rounded px-2 py-1 text-slate-800"
                              />
                            </div>
                            <div>
                              <label className="text-[10px] text-slate-500 block mb-1">Ring 2 (m)</label>
                              <input
                                type="number"
                                value={meshSettings.ring2_m}
                                onChange={e => setMeshSettings(s => ({ ...s, ring2_m: Number(e.target.value) }))}
                                className="w-full text-xs border rounded px-2 py-1 text-slate-800"
                              />
                            </div>
                            <div>
                              <label className="text-[10px] text-slate-500 block mb-1">Ring 3 (m)</label>
                              <input
                                type="number"
                                value={meshSettings.ring3_m}
                                onChange={e => setMeshSettings(s => ({ ...s, ring3_m: Number(e.target.value) }))}
                                className="w-full text-xs border rounded px-2 py-1 text-slate-800"
                              />
                            </div>
                          </div>

                          <div className="grid grid-cols-2 gap-2">
                            <div>
                              <label className="text-[10px] text-slate-500 block mb-1">Max pkt pogody</label>
                              <input
                                type="number"
                                value={meshSettings.max_weather_points}
                                onChange={e => setMeshSettings(s => ({ ...s, max_weather_points: Number(e.target.value) }))}
                                className="w-full text-xs border rounded px-2 py-1 text-slate-800"
                              />
                            </div>
                            <div>
                              <label className="text-[10px] text-slate-500 block mb-1">Grid pogody (km)</label>
                              <input
                                type="number"
                                step="0.5"
                                value={meshSettings.weather_grid_km}
                                onChange={e => setMeshSettings(s => ({ ...s, weather_grid_km: Number(e.target.value) }))}
                                className="w-full text-xs border rounded px-2 py-1 text-slate-800"
                              />
                            </div>
                          </div>

                          <button
                            onClick={() => setMeshSettings(DEFAULT_MESH_SETTINGS)}
                            className="text-xs text-blue-500 hover:underline"
                          >
                            Przywroc domyslne
                          </button>
                        </div>
                      )}
                   </div>
                )}
            </div>

            {/* SEKCJA 3: OKNO STARTOWE */}
            <div className="border-b border-slate-200">
                <button onClick={() => toggleSection('startWindow')} className="p-4 w-full flex justify-between bg-slate-50 hover:bg-slate-100">
                    <span className="font-bold text-slate-800">Okno Startowe</span>
                    <span className="text-slate-400">{expandedSection === 'startWindow' ? '▲' : '▼'}</span>
                </button>
                {expandedSection === 'startWindow' && (
                   <div className="p-4 bg-white space-y-3">
                      {/* Checkbox do włączenia okna czasowego */}
                      <label className="flex items-center gap-2 cursor-pointer">
                        <input
                          type="checkbox"
                          checked={useTimeWindow}
                          onChange={e => setUseTimeWindow(e.target.checked)}
                          className="w-4 h-4 text-blue-600 rounded"
                        />
                        <span className="text-sm text-slate-700 font-medium">Ustaw okno czasowe startu</span>
                      </label>

                      {!useTimeWindow ? (
                        <div className="bg-slate-50 border border-slate-200 rounded p-3 text-xs text-slate-600">
                          <p>Start zostanie ustawiony na <strong>aktualną godzinę (Warszawa)</strong> z jednym sprawdzeniem.</p>
                        </div>
                      ) : (
                        <>
                          <div>
                            <label className="text-[10px] text-slate-500 uppercase font-bold block mb-1">
                              Pierwszy możliwy start
                            </label>
                            <input
                              type="datetime-local"
                              className="w-full border p-2 text-sm rounded focus:ring-1 focus:ring-blue-500 outline-none text-slate-800"
                              value={startWindow.start}
                              onChange={e => setStartWindow({...startWindow, start: e.target.value})}
                            />
                          </div>

                          <div>
                            <label className="text-[10px] text-slate-500 uppercase font-bold block mb-1">
                              Zamknięcie okna
                            </label>
                            <input
                              type="datetime-local"
                              className="w-full border p-2 text-sm rounded focus:ring-1 focus:ring-blue-500 outline-none text-slate-800"
                              value={startWindow.end}
                              onChange={e => setStartWindow({...startWindow, end: e.target.value})}
                            />
                          </div>

                          <div>
                            <label className="text-[10px] text-slate-500 uppercase font-bold block mb-1">
                              Liczba sprawdzeń: <span className="text-blue-600">{startWindow.checkCount}</span>
                            </label>
                            <input
                              type="range"
                              min="1"
                              max="10"
                              className="w-full"
                              value={startWindow.checkCount}
                              onChange={e => setStartWindow({...startWindow, checkCount: parseInt(e.target.value)})}
                            />
                            <div className="flex justify-between text-[9px] text-slate-400 mt-1">
                              <span>1</span>
                              <span>Więcej = dokładniej, ale wolniej</span>
                              <span>10</span>
                            </div>
                          </div>

                          <div className="bg-blue-50 border border-blue-200 rounded p-2 text-xs text-blue-800">
                            <strong>Podsumowanie:</strong><br/>
                            Od: {new Date(startWindow.start).toLocaleString('pl-PL')}<br/>
                            Do: {new Date(startWindow.end).toLocaleString('pl-PL')}<br/>
                            Sprawdzeń: {startWindow.checkCount} wariantów startu
                          </div>
                        </>
                      )}
                   </div>
                )}
            </div>

            {/* SEKCJA 4: WYNIKI TRASY - pokazuje się po obliczeniu */}
            {calcStatus.routeResult && (
            <div className="border-b border-slate-200">
                <button onClick={() => toggleSection('results')} className="p-4 w-full flex justify-between bg-green-50 hover:bg-green-100">
                    <span className="font-bold text-green-800">Wyniki ({calcStatus.routeResult.variants_count} wariantow)</span>
                    <span className="text-green-600">{expandedSection === 'results' ? '▲' : '▼'}</span>
                </button>
                {expandedSection === 'results' && (
                   <div className="bg-white max-h-[350px] overflow-y-auto">
                      {/* Summary */}
                      <div className="p-3 bg-green-50 border-b text-xs">
                        <div className="flex justify-between">
                          <span>Trudność: <strong className={getDifficultyColor(calcStatus.routeResult.difficulty.level)}>{calcStatus.routeResult.difficulty.level}</strong></span>
                          <span>Score: {calcStatus.routeResult.difficulty.overall_score}</span>
                        </div>
                      </div>

                      {/* Variants list */}
                      <div className="p-2 space-y-2">
                        {calcStatus.routeResult.variants.map((variant, idx) => (
                          <div
                            key={variant.variant_id}
                            onClick={() => handleVariantToggle(variant.variant_id)}
                            className={`
                              p-3 rounded border cursor-pointer transition-all
                              ${selectedVariantIds.includes(variant.variant_id) 
                                ? 'border-green-500 bg-green-50 shadow-sm' 
                                : 'border-slate-200 hover:border-green-300'}
                            `}
                          >
                            <div className="flex items-center justify-between">
                              <div className="flex items-center gap-2">
                                <input
                                  type="checkbox"
                                  checked={selectedVariantIds.includes(variant.variant_id)}
                                  onChange={() => {}}
                                  className="w-4 h-4 text-green-600"
                                />
                                <div>
                                  <div className="font-bold text-sm text-slate-800 flex items-center gap-1">
                                    {formatDateTime(variant.departure_time)}
                                    {variant.is_best && (
                                      <span className="text-[10px] bg-green-500 text-white px-1.5 py-0.5 rounded">BEST</span>
                                    )}
                                  </div>
                                  <div className="text-[10px] text-slate-500">
                                    {formatDuration(variant.total_time_hours)} • {variant.total_distance_nm.toFixed(1)} nm • {variant.average_speed_knots.toFixed(1)} kt
                                  </div>
                                </div>
                              </div>
                              <div className={`text-[10px] px-1.5 py-0.5 rounded ${getDifficultyColor(variant.difficulty_level)}`}>
                                {variant.difficulty_level}
                              </div>
                            </div>

                            {/* Expanded details when selected */}
                            {selectedVariantIds.includes(variant.variant_id) && (
                              <div className="mt-2 pt-2 border-t border-slate-200 grid grid-cols-4 gap-1 text-[10px]">
                                <div className="text-center">
                                  <div className="text-slate-600 font-medium">Wiatr</div>
                                  <div className="font-bold text-slate-800">{(Math.round((variant.avg_wind_speed * 0.53) * 2) / 2).toFixed(1)} kt</div>
                                </div>
                                <div className="text-center">
                                  <div className="text-slate-600 font-medium">Fale</div>
                                  <div className="font-bold text-slate-800">{variant.avg_wave_height.toFixed(2)} m</div>
                                </div>
                                <div className="text-center">
                                  <div className="text-slate-600 font-medium">Zwroty</div>
                                  <div className="font-bold text-slate-800">{variant.tacks_count}</div>
                                </div>
                                <div className="text-center">
                                  <div className="text-slate-600 font-medium">Przejścia</div>
                                  <div className="font-bold text-slate-800">{variant.jibes_count}</div>
                                </div>
                              </div>
                            )}
                          </div>
                        ))}
                      </div>

                      {/* Actions */}
                      <div className="p-2 border-t bg-slate-50 flex gap-2">
                        <button
                          onClick={handleSelectAllVariants}
                          className="flex-1 py-1.5 text-xs bg-slate-200 text-slate-700 rounded hover:bg-slate-300"
                        >
                          Zaznacz wszystkie
                        </button>
                        <button
                          onClick={handleNewRoute}
                          className="flex-1 py-1.5 text-xs bg-blue-600 text-white rounded hover:bg-blue-700"
                        >
                          Nowa trasa
                        </button>
                      </div>
                   </div>
                )}
            </div>
            )}

            {/* ACTION BUTTON */}
            <div className="p-4 bg-slate-50 mt-auto border-t border-slate-200">
                {!calcStatus.routeResult ? (
                  <>
                    <button
                        onClick={handleCalculateRoute}
                        disabled={!canCalculate}
                        className="w-full py-3 bg-green-600 text-white rounded font-bold shadow hover:bg-green-700 disabled:bg-slate-300 disabled:cursor-not-allowed transition-all active:scale-[0.98]"
                    >
                        {isCalculating ? calcStatus.message : 'OBLICZ TRASE'}
                    </button>

                    {!canCalculate && !isCalculating && (
                        <p className="text-[10px] text-slate-400 text-center mt-2">
                            {!selectedYachtId ? "① Wybierz jacht" : ""}
                            {selectedYachtId && controlPoints.length < 2 ? "② Dodaj min. 2 punkty na mapie" : ""}
                        </p>
                    )}

                    {/* Mini status */}
                    {calcStatus.step !== 'idle' && calcStatus.step !== 'done' && calcStatus.step !== 'error' && (
                      <div className="mt-2 text-xs text-center">
                        <div className="w-full bg-slate-200 rounded-full h-1.5 mb-1">
                          <div
                            className="bg-blue-600 h-1.5 rounded-full transition-all duration-500"
                            style={{width: `${getStepProgress()}%`}}
                          ></div>
                        </div>
                        <span className="text-slate-500">{calcStatus.message}</span>
                      </div>
                    )}
                  </>
                ) : (
                  <div className="text-center">
                    <div className="text-sm text-green-600 font-bold mb-2">Trasa obliczona!</div>
                    <div className="text-xs text-slate-500">
                      Wybrano {selectedVariantIds.length} z {calcStatus.routeResult.variants_count} wariantów
                    </div>
                  </div>
                )}
            </div>

        </div>
      </div>
    </main>
  );
}