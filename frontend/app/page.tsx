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
  // reszta pól opcjonalna, zależnie od tego co zwraca API
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

// Adres API (zwróć uwagę na prefix /api/v1 z Twojego routera)
const API_URL = "http://localhost:8000/api/v1";

export default function Home() {
  // --- STANY ---
  const [allYachts, setAllYachts] = useState<Yacht[]>([]);
  const [mySessionIds, setMySessionIds] = useState<string[]>([]); // ID jachtów stworzonych w tej sesji

  const [selectedYachtId, setSelectedYachtId] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<'presets' | 'my'>('presets');

  // UI - Routing i inne
  const [routePoints, setRoutePoints] = useState<[number, number][]>([]);
  const [isCalculating, setIsCalculating] = useState(false);
  const [expandedSection, setExpandedSection] = useState<'yachts' | 'route' | 'settings' | null>('yachts');

  // UI - Dodawanie jachtu
  const [isAddingYacht, setIsAddingYacht] = useState(false);
  const [newYachtData, setNewYachtData] = useState(emptyYachtForm);

  // --- INICJALIZACJA ---
  useEffect(() => {
    // 1. Odczytaj ID "moich" jachtów z sessionStorage
    const stored = sessionStorage.getItem("my_yacht_ids");
    if (stored) {
        setMySessionIds(JSON.parse(stored));
    }

    // 2. Pobierz WSZYSTKIE jachty z API
    fetchYachts();
  }, []);

  const fetchYachts = async () => {
    try {
      const res = await fetch(`${API_URL}/yachts/`);
      if (!res.ok) throw new Error("Failed to fetch");
      const data: Yacht[] = await res.json();
      setAllYachts(data);

      // Jeśli nic nie jest wybrane, wybierz domyślny preset (np. pierwszy z listy presetów)
      if (!selectedYachtId && data.length > 0) {
          const defaultPreset = data.find(y => PRESET_IDS.includes(y.id));
          if (defaultPreset) setSelectedYachtId(defaultPreset.id);
      }
    } catch (err) {
      console.error("Błąd pobierania jachtów:", err);
    }
  };

  // --- FILTROWANIE ---
  // Presety = te, których ID jest na liście stałych ID
  const presetYachts = allYachts.filter(y => PRESET_IDS.includes(y.id));

  // Moje Jachty = te, których ID jest w sessionStorage (czyli stworzone przez nas)
  // LUB te, które nie są presetami (opcjonalne podejście, zależnie czy chcesz widzieć jachty innych userów)
  // Tutaj używamy bezpiecznej wersji: pokazujemy tylko te, które mamy zapisane w sesji.
  const myYachts = allYachts.filter(y => mySessionIds.includes(y.id));

  // --- AKCJE JACHTÓW ---

  const handleCreateYacht = async () => {
    try {
        const res = await fetch(`${API_URL}/yachts/`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(newYachtData)
        });

        if (res.ok) {
            const createdYacht = await res.json();

            // 1. Dodaj do lokalnej listy wszystkich jachtów (żeby nie odświeżać całej strony)
            setAllYachts(prev => [...prev, createdYacht]);

            // 2. Zapisz ID w sesji ("to jest mój jacht")
            const newSessionIds = [...mySessionIds, createdYacht.id];
            setMySessionIds(newSessionIds);
            sessionStorage.setItem("my_yacht_ids", JSON.stringify(newSessionIds));

            // 3. Reset UI
            setIsAddingYacht(false);
            setNewYachtData(emptyYachtForm);
            setActiveTab('my'); // Przełącz na zakładkę "Moje"
            setSelectedYachtId(createdYacht.id); // Zaznacz nowy
        } else {
            console.error("Błąd tworzenia jachtu", await res.text());
        }
    } catch (err) { console.error(err); }
  };

  const handleDeleteYacht = async (e: React.MouseEvent, id: string) => {
    e.stopPropagation();
    if(!confirm("Czy na pewno usunąć ten jacht?")) return;

    try {
        const res = await fetch(`${API_URL}/yachts/${id}`, { method: 'DELETE' });
        if (res.ok) {
            // Usuń z listy wszystkich
            setAllYachts(prev => prev.filter(y => y.id !== id));

            // Usuń z sesji
            const newSessionIds = mySessionIds.filter(mid => mid !== id);
            setMySessionIds(newSessionIds);
            sessionStorage.setItem("my_yacht_ids", JSON.stringify(newSessionIds));

            if (selectedYachtId === id) setSelectedYachtId(null);
        }
    } catch (err) { console.error(err); }
  };

  // --- MAPA I ROUTING ---
  const addPoint = (lat: number, lng: number) => {
    if (isCalculating) return;
    setRoutePoints(prev => [...prev, [lat, lng]]);
    if (expandedSection !== 'route') setExpandedSection('route');
  };

  const handleCalculateRoute = async () => {
    if (routePoints.length < 2 || !selectedYachtId) return;
    setIsCalculating(true);

    const activeYacht = allYachts.find(y => y.id === selectedYachtId);

    const payload = {
        yacht_id: selectedYachtId,
        // Możemy wysłać też pełne dane jachtu, jeśli backend tego potrzebuje
        // active_yacht_snapshot: activeYacht,
        points: routePoints.map(p => ({ lat: p[0], lon: p[1] }))
    };

    console.log("🚀 Wysyłam do obliczenia:", payload);

    // Symulacja
    setTimeout(() => setIsCalculating(false), 2000);
  };

  const toggleSection = (section: any) => setExpandedSection(expandedSection === section ? null : section);

  const getActiveYachtName = () => {
    const y = allYachts.find(y => y.id === selectedYachtId);
    return y ? y.name : "Wybierz jacht";
  };

  return (
    <main className="flex h-screen w-screen flex-col font-sans relative overflow-hidden">
      {isCalculating && <LoadingOverlay />}

      {/* HEADER */}
      <div className="h-16 bg-slate-900 text-white flex items-center px-6 justify-between z-10 shadow-lg border-b border-slate-700">
        <h1 className="font-semibold text-lg tracking-wide">Sailing Route Calculator</h1>
        <div className="text-xs text-slate-400">
            Wybrany: <span className="text-white font-bold ml-1">{getActiveYachtName()}</span>
        </div>
      </div>

      <div className="flex-grow relative">
        <SailingMap markers={routePoints} onMapClick={addPoint} />

        {/* SIDEBAR */}
        <div className="absolute top-4 right-4 bg-white/95 backdrop-blur-sm rounded-lg shadow-xl z-[1000] w-96 max-h-[85vh] flex flex-col border border-slate-200 transition-all overflow-hidden">

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
                                <div className="max-h-[300px] overflow-y-auto custom-scrollbar p-3 space-y-2">
                                    {(activeTab === 'presets' ? presetYachts : myYachts).length === 0 && (
                                        <p className="text-xs text-center text-slate-400 py-4">Brak jachtów w tej sekcji.</p>
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
                                                <div className="text-[10px] text-slate-500">{yacht.yacht_type} • L:{yacht.length}m</div>
                                            </div>

                                            {selectedYachtId === yacht.id && <div className="text-blue-600 text-lg font-bold">✓</div>}

                                            {/* Przycisk usuwania (tylko w zakładce MOJE) */}
                                            {activeTab === 'my' && (
                                                <button
                                                    onClick={(e) => handleDeleteYacht(e, yacht.id)}
                                                    className="absolute top-1 right-1 p-1 text-slate-300 hover:text-red-500 transition-colors"
                                                >✕</button>
                                            )}
                                        </div>
                                    ))}
                                </div>

                                {/* PRZYCISK DODAWANIA (tylko w zakładce MOJE) */}
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
                                    <label className="text-[10px] text-slate-500 uppercase font-bold">Nazwa</label>
                                    <input type="text" className="w-full border p-1.5 text-sm rounded focus:ring-1 focus:ring-blue-500 outline-none"
                                        value={newYachtData.name} onChange={e => setNewYachtData({...newYachtData, name: e.target.value})} />
                                </div>

                                <div className="grid grid-cols-2 gap-2">
                                    <div>
                                        <label className="text-[10px] text-slate-500 uppercase font-bold">Długość (m)</label>
                                        <input type="number" className="w-full border p-1.5 text-sm rounded focus:ring-1 focus:ring-blue-500 outline-none"
                                            value={newYachtData.length} onChange={e => setNewYachtData({...newYachtData, length: parseFloat(e.target.value)})} />
                                    </div>
                                    <div>
                                        <label className="text-[10px] text-slate-500 uppercase font-bold">Szerokość (m)</label>
                                        <input type="number" className="w-full border p-1.5 text-sm rounded focus:ring-1 focus:ring-blue-500 outline-none"
                                             value={newYachtData.beam} onChange={e => setNewYachtData({...newYachtData, beam: parseFloat(e.target.value)})} />
                                    </div>
                                    <div>
                                        <label className="text-[10px] text-slate-500 uppercase font-bold">Max Prędkość</label>
                                        <input type="number" className="w-full border p-1.5 text-sm rounded focus:ring-1 focus:ring-blue-500 outline-none"
                                             value={newYachtData.max_speed} onChange={e => setNewYachtData({...newYachtData, max_speed: parseFloat(e.target.value)})} />
                                    </div>
                                    <div>
                                        <label className="text-[10px] text-slate-500 uppercase font-bold">Max Wiatr</label>
                                        <input type="number" className="w-full border p-1.5 text-sm rounded focus:ring-1 focus:ring-blue-500 outline-none"
                                             value={newYachtData.max_wind_speed} onChange={e => setNewYachtData({...newYachtData, max_wind_speed: parseFloat(e.target.value)})} />
                                    </div>
                                </div>

                                <div className="flex gap-2 pt-2">
                                    <button onClick={() => setIsAddingYacht(false)} className="flex-1 py-2 bg-white border border-slate-300 text-slate-600 rounded text-xs font-bold hover:bg-slate-100">Anuluj</button>
                                    <button onClick={handleCreateYacht} className="flex-1 py-2 bg-blue-600 text-white rounded text-xs font-bold hover:bg-blue-700 shadow-sm">Zapisz Jacht</button>
                                </div>
                            </div>
                        )}
                    </div>
                )}
            </div>

            {/* SEKCJA 2: TRASA */}
            <div className="border-b border-slate-200">
                <button onClick={() => toggleSection('route')} className="p-4 w-full flex justify-between bg-slate-50 hover:bg-slate-100">
                    <span className="font-bold text-slate-800">📍 Trasa ({routePoints.length})</span>
                    <span className="text-slate-400">{expandedSection === 'route' ? '▲' : '▼'}</span>
                </button>
                {expandedSection === 'route' && (
                   <div className="p-4 bg-white max-h-[150px] overflow-y-auto custom-scrollbar">
                      {routePoints.length === 0 && <p className="text-xs text-slate-400 italic">Kliknij na mapie by dodać punkty.</p>}
                      {routePoints.map((p, i) => (
                        <div key={i} className="flex justify-between items-center text-xs text-slate-600 mb-1 border-b border-slate-50 pb-1 last:border-0">
                            <span className="font-mono">P{i}: {p[0].toFixed(4)}, {p[1].toFixed(4)}</span>
                        </div>
                      ))}
                      {routePoints.length > 0 && (
                        <button onClick={() => setRoutePoints([])} className="text-xs text-red-500 mt-2 hover:underline">Wyczyść wszystkie punkty</button>
                      )}
                   </div>
                )}
            </div>

            {/* ACTION BUTTON */}
            <div className="p-4 bg-slate-50 mt-auto border-t border-slate-200">
                <button
                    onClick={handleCalculateRoute}
                    disabled={!selectedYachtId || routePoints.length < 2 || isCalculating}
                    className="w-full py-3 bg-green-600 text-white rounded font-bold shadow hover:bg-green-700 disabled:bg-slate-300 disabled:cursor-not-allowed transition-all active:scale-[0.98]"
                >
                    {isCalculating ? 'PRZETWARZANIE DANYCH...' : 'OBLICZ TRASĘ 🏁'}
                </button>
            </div>

        </div>
      </div>
    </main>
  );
}