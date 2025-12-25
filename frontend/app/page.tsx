'use client';

import dynamic from 'next/dynamic';
import { useState, useEffect } from 'react';
import LoadingOverlay from '../components/LoadingOverlay';

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

type CalculationStep = 'idle' | 'mesh' | 'weather' | 'routing' | 'done' | 'error';

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

// Helper: generuj domyślne okno startowe (od teraz do +24h)
const getDefaultStartWindow = () => {
  const now = new Date();
  const tomorrow = new Date(now.getTime() + 24 * 60 * 60 * 1000);

  // Format dla datetime-local input: YYYY-MM-DDTHH:MM
  const formatForInput = (d: Date) => {
    return d.toISOString().slice(0, 16);
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

  // UI - Routing i punkty
  const [routePoints, setRoutePoints] = useState<[number, number][]>([]);
  const [isCalculating, setIsCalculating] = useState(false);
  const [expandedSection, setExpandedSection] = useState<'yachts' | 'route' | 'startWindow' | 'results' | 'settings' | null>('yachts');

  // UI - Dodawanie jachtu
  const [isAddingYacht, setIsAddingYacht] = useState(false);
  const [newYachtData, setNewYachtData] = useState(emptyYachtForm);

  // UI - Error handling
  const [error, setError] = useState<string | null>(null);

  // NOWE: Okno startowe
  const [startWindow, setStartWindow] = useState(getDefaultStartWindow);

  // NOWE: Status obliczania
  const [calcStatus, setCalcStatus] = useState<CalculationStatus>({
    step: 'idle',
    message: '',
    routeResult: null
  });

  // NOWE: Wybrane warianty do wyświetlenia na mapie
  const [selectedVariantIds, setSelectedVariantIds] = useState<string[]>([]);

  // NOWE: Waypoints dla wariantów (pobrane z API)
  const [variantWaypoints, setVariantWaypoints] = useState<Record<string, [number, number][]>>({});

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
    setRoutePoints(prev => [...prev, [lat, lng]]);
    if (expandedSection !== 'route') setExpandedSection('route');
  };

  const removePoint = (index: number) => {
    setRoutePoints(prev => prev.filter((_, i) => i !== index));
  };

  // ========================================
  // GŁÓWNY WORKFLOW OBLICZANIA TRASY
  // ========================================
  const handleCalculateRoute = async () => {
    if (routePoints.length < 2 || !selectedYachtId) return;

    setIsCalculating(true);
    setError(null);
    setCalcStatus({ step: 'mesh', message: 'Tworzenie siatki nawigacyjnej...' });

    try {
      // ============ KROK 1: Tworzenie MESH ============
      console.log("🔷 KROK 1: Tworzenie mesh...");

      const meshPayload = {
        user_id: "3fa85f64-5717-4562-b3fc-2c963f66afa6",
        yacht_id: selectedYachtId,
        points: routePoints.map((p, idx) => ({
          lat: p[0],
          lon: p[1],
          timestamp: null
        })),
        corridor_nm: 3.0,
        ring1_m: 500,
        ring2_m: 1500,
        ring3_m: 3000,
        area1: 3000,
        area2: 15000,
        area3: 60000,
        shoreline_avoid_m: 300,
        enable_weather_optimization: true,
        max_weather_points: 40,
        weather_grid_km: 5.0,
        weather_clustering_method: "kmeans"
      };

      console.log("📤 Mesh payload:", meshPayload);

      const meshRes = await fetch(`${API_URL}/routes_mesh/mesh`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(meshPayload)
      });

      if (!meshRes.ok) {
        const errText = await meshRes.text();
        throw new Error(`Mesh creation failed: ${meshRes.status} - ${errText}`);
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
        throw new Error(`Weather fetch failed: ${weatherRes.status} - ${errText}`);
      }

      const weatherData = await weatherRes.json();
      console.log("✅ Pogoda pobrana:", weatherData);

      setCalcStatus({
        step: 'routing',
        message: `Obliczanie optymalnej trasy (${startWindow.checkCount} wariantów)...`,
        meshedAreaId
      });

      // ============ KROK 3: Obliczanie trasy ============
      console.log("🔷 KROK 3: Obliczanie trasy...");

      // Payload zgodny z TimeWindowRequest schema
      const routingPayload = {
        start_time: new Date(startWindow.start).toISOString(),
        end_time: new Date(startWindow.end).toISOString(),
        num_checks: startWindow.checkCount
      };

      console.log("📤 Routing payload:", routingPayload);

      // Endpoint: /calculate-route (nie /calculate!)
      const routingRes = await fetch(`${API_URL}/routing/${meshedAreaId}/calculate-route`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(routingPayload)
      });

      if (!routingRes.ok) {
        const errText = await routingRes.text();
        throw new Error(`Route calculation failed: ${routingRes.status} - ${errText}`);
      }

      const routeResult = await routingRes.json();
      console.log("✅ Trasa obliczona:", routeResult);

      // Wyczyść wyklikane punkty - teraz pokazujemy obliczoną trasę
      setRoutePoints([]);

      // Zbierz waypoints dla wszystkich wariantów
      const waypointsMap: Record<string, [number, number][]> = {};

      // Sprawdź czy response zawiera waypoints (po zastosowaniu patcha backendu)
      for (const variant of routeResult.variants) {
        if (variant.waypoints_wgs84 && variant.waypoints_wgs84.length > 0) {
          // waypoints są w formacie [lon, lat], konwertujemy na [lat, lon] dla Leaflet
          waypointsMap[variant.variant_id] = variant.waypoints_wgs84.map(
            (wp: [number, number]) => [wp[1], wp[0]] as [number, number]
          );
        }
      }

      // Jeśli brak waypoints w response, pobierz z calculated-route (dla best variant)
      if (Object.keys(waypointsMap).length === 0) {
        const waypointsRes = await fetch(`${API_URL}/routing/${meshedAreaId}/calculated-route`);
        if (waypointsRes.ok) {
          const waypointsData = await waypointsRes.json();
          console.log("📍 Waypoints from calculated-route:", waypointsData);

          if (waypointsData.data?.route?.waypoints_wgs84 && routeResult.best_variant) {
            const waypoints = waypointsData.data.route.waypoints_wgs84.map(
              (wp: [number, number]) => [wp[1], wp[0]] as [number, number]
            );
            waypointsMap[routeResult.best_variant.variant_id] = waypoints;
          }
        }
      }

      console.log("📍 Waypoints map:", waypointsMap);
      setVariantWaypoints(waypointsMap);

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
  const canCalculate = selectedYachtId && routePoints.length >= 2 && !isCalculating;

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
    setRoutePoints([]);
    setExpandedSection('yachts');
  };

  // Handler: otwórz pełną wizualizację
  const handleViewVisualization = (meshedAreaId: string) => {
    window.open(`${API_URL}/visualise/${meshedAreaId}/route/view?show_all_variants=false`, '_blank');
  };

  // Oblicz trasy do wyświetlenia na mapie
  const calculatedRoutes = selectedVariantIds
    .filter(id => variantWaypoints[id])
    .map(id => variantWaypoints[id]);

  return (
    <main className="flex h-screen w-screen flex-col font-sans relative overflow-hidden">
      {isCalculating && <LoadingOverlay message={calcStatus.message} progress={getStepProgress()} />}

      {/* HEADER */}
      <div className="h-16 bg-slate-900 text-white flex items-center px-6 justify-between z-10 shadow-lg border-b border-slate-700">
        <h1 className="font-semibold text-lg tracking-wide">⛵ Sailing Route Calculator</h1>
        <div className="text-xs text-slate-400">
            Jacht: <span className="text-white font-bold ml-1">{getActiveYachtName()}</span>
        </div>
      </div>

      <div className="flex-grow relative">
        <SailingMap
          markers={routePoints}
          onMapClick={addPoint}
          calculatedRoutes={calculatedRoutes}
          isRouteCalculated={!!calcStatus.routeResult}
        />

        {/* SIDEBAR */}
        <div className="absolute top-4 right-4 bg-white/95 backdrop-blur-sm rounded-lg shadow-xl z-[1000] w-96 max-h-[85vh] flex flex-col border border-slate-200 transition-all overflow-hidden">

            {/* ERROR MESSAGE */}
            {error && (
              <div className="bg-red-100 border-b border-red-300 text-red-700 px-4 py-2 text-xs">
                ⚠️ {error}
                <button onClick={() => setError(null)} className="float-right font-bold">×</button>
              </div>
            )}

            {/* SUCCESS MESSAGE */}
            {calcStatus.step === 'done' && (
              <div className="bg-green-100 border-b border-green-300 text-green-700 px-4 py-2 text-xs flex items-center justify-between">
                <span>✅ {calcStatus.message}</span>
                <div className="flex gap-2">
                  <button
                    onClick={() => setShowResultsModal(true)}
                    className="underline hover:text-green-800"
                  >
                    📊 Wyniki
                  </button>
                  {calcStatus.meshedAreaId && (
                    <button
                      onClick={() => handleViewVisualization(calcStatus.meshedAreaId!)}
                      className="underline hover:text-green-800"
                    >
                      🗺️ Mapa
                    </button>
                  )}
                </div>
              </div>
            )}

            {/* SEKCJA 1: JACHTY */}
            <div className="border-b border-slate-200 flex flex-col">
                <button onClick={() => toggleSection('yachts')} className="p-4 flex justify-between bg-slate-50 hover:bg-slate-100">
                    <span className="font-bold text-slate-800">⛵ Jachty</span>
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
                                            <div className="text-xl">⛵</div>
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
                                    <input type="text" className="w-full border p-1.5 text-sm rounded focus:ring-1 focus:ring-blue-500 outline-none"
                                        placeholder="Np. Mój Jacht"
                                        value={newYachtData.name} onChange={e => setNewYachtData({...newYachtData, name: e.target.value})} />
                                </div>

                                <div>
                                    <label className="text-[10px] text-slate-500 uppercase font-bold">Typ</label>
                                    <select
                                        className="w-full border p-1.5 text-sm rounded focus:ring-1 focus:ring-blue-500 outline-none"
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
                                        <input type="number" className="w-full border p-1.5 text-sm rounded focus:ring-1 focus:ring-blue-500 outline-none"
                                            value={newYachtData.length} onChange={e => setNewYachtData({...newYachtData, length: parseFloat(e.target.value) || 0})} />
                                    </div>
                                    <div>
                                        <label className="text-[10px] text-slate-500 uppercase font-bold">Szerokość (m)</label>
                                        <input type="number" className="w-full border p-1.5 text-sm rounded focus:ring-1 focus:ring-blue-500 outline-none"
                                             value={newYachtData.beam} onChange={e => setNewYachtData({...newYachtData, beam: parseFloat(e.target.value) || 0})} />
                                    </div>
                                    <div>
                                        <label className="text-[10px] text-slate-500 uppercase font-bold">Zanurzenie (m)</label>
                                        <input type="number" className="w-full border p-1.5 text-sm rounded focus:ring-1 focus:ring-blue-500 outline-none"
                                             value={newYachtData.draft} onChange={e => setNewYachtData({...newYachtData, draft: parseFloat(e.target.value) || 0})} />
                                    </div>
                                    <div>
                                        <label className="text-[10px] text-slate-500 uppercase font-bold">Załoga</label>
                                        <input type="number" className="w-full border p-1.5 text-sm rounded focus:ring-1 focus:ring-blue-500 outline-none"
                                             value={newYachtData.amount_of_crew} onChange={e => setNewYachtData({...newYachtData, amount_of_crew: parseInt(e.target.value) || 1})} />
                                    </div>
                                    <div>
                                        <label className="text-[10px] text-slate-500 uppercase font-bold">Max Prędkość (kt)</label>
                                        <input type="number" className="w-full border p-1.5 text-sm rounded focus:ring-1 focus:ring-blue-500 outline-none"
                                             value={newYachtData.max_speed} onChange={e => setNewYachtData({...newYachtData, max_speed: parseFloat(e.target.value) || 0})} />
                                    </div>
                                    <div>
                                        <label className="text-[10px] text-slate-500 uppercase font-bold">Max Wiatr (kt)</label>
                                        <input type="number" className="w-full border p-1.5 text-sm rounded focus:ring-1 focus:ring-blue-500 outline-none"
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

            {/* SEKCJA 2: TRASA */}
            <div className="border-b border-slate-200">
                <button onClick={() => toggleSection('route')} className="p-4 w-full flex justify-between bg-slate-50 hover:bg-slate-100">
                    <span className="font-bold text-slate-800">📍 Trasa ({routePoints.length} pkt)</span>
                    <span className="text-slate-400">{expandedSection === 'route' ? '▲' : '▼'}</span>
                </button>
                {expandedSection === 'route' && (
                   <div className="p-4 bg-white max-h-[150px] overflow-y-auto custom-scrollbar">
                      {routePoints.length === 0 && <p className="text-xs text-slate-400 italic">Kliknij na mapie by dodać punkty.</p>}
                      {routePoints.map((p, i) => (
                        <div key={i} className="flex justify-between items-center text-xs text-slate-600 mb-1 border-b border-slate-50 pb-1 last:border-0">
                            <span className="font-mono">
                              {i === 0 ? '🟢' : i === routePoints.length - 1 ? '🏁' : '📍'} P{i}: {p[0].toFixed(4)}, {p[1].toFixed(4)}
                            </span>
                            <button
                              onClick={() => removePoint(i)}
                              className="text-red-400 hover:text-red-600 ml-2"
                              title="Usuń punkt"
                            >
                              ✕
                            </button>
                        </div>
                      ))}
                      {routePoints.length > 0 && (
                        <button onClick={() => setRoutePoints([])} className="text-xs text-red-500 mt-2 hover:underline">
                          Wyczyść wszystkie punkty
                        </button>
                      )}
                   </div>
                )}
            </div>

            {/* SEKCJA 3: OKNO STARTOWE */}
            <div className="border-b border-slate-200">
                <button onClick={() => toggleSection('startWindow')} className="p-4 w-full flex justify-between bg-slate-50 hover:bg-slate-100">
                    <span className="font-bold text-slate-800">🕐 Okno Startowe</span>
                    <span className="text-slate-400">{expandedSection === 'startWindow' ? '▲' : '▼'}</span>
                </button>
                {expandedSection === 'startWindow' && (
                   <div className="p-4 bg-white space-y-3">
                      <div>
                        <label className="text-[10px] text-slate-500 uppercase font-bold block mb-1">
                          Pierwszy możliwy start
                        </label>
                        <input
                          type="datetime-local"
                          className="w-full border p-2 text-sm rounded focus:ring-1 focus:ring-blue-500 outline-none"
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
                          className="w-full border p-2 text-sm rounded focus:ring-1 focus:ring-blue-500 outline-none"
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
                          max="24"
                          className="w-full"
                          value={startWindow.checkCount}
                          onChange={e => setStartWindow({...startWindow, checkCount: parseInt(e.target.value)})}
                        />
                        <div className="flex justify-between text-[9px] text-slate-400 mt-1">
                          <span>1</span>
                          <span>Więcej = dokładniej, ale wolniej</span>
                          <span>24</span>
                        </div>
                      </div>

                      <div className="bg-blue-50 border border-blue-200 rounded p-2 text-xs text-blue-800">
                        <strong>Podsumowanie:</strong><br/>
                        Od: {new Date(startWindow.start).toLocaleString('pl-PL')}<br/>
                        Do: {new Date(startWindow.end).toLocaleString('pl-PL')}<br/>
                        Sprawdzeń: {startWindow.checkCount} wariantów startu
                      </div>
                   </div>
                )}
            </div>

            {/* SEKCJA 4: WYNIKI TRASY - pokazuje się po obliczeniu */}
            {calcStatus.routeResult && (
            <div className="border-b border-slate-200">
                <button onClick={() => toggleSection('results')} className="p-4 w-full flex justify-between bg-green-50 hover:bg-green-100">
                    <span className="font-bold text-green-800">🏁 Wyniki ({calcStatus.routeResult.variants_count} wariantów)</span>
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
                                  <div className="font-bold text-slate-800">{variant.avg_wind_speed.toFixed(1)} kt</div>
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
                        {isCalculating ? calcStatus.message : 'OBLICZ TRASĘ 🏁'}
                    </button>

                    {!canCalculate && !isCalculating && (
                        <p className="text-[10px] text-slate-400 text-center mt-2">
                            {!selectedYachtId ? "① Wybierz jacht" : ""}
                            {selectedYachtId && routePoints.length < 2 ? "② Dodaj min. 2 punkty na mapie" : ""}
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
                    <div className="text-sm text-green-600 font-bold mb-2">✅ Trasa obliczona!</div>
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