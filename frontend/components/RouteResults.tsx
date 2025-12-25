'use client';

import { useState } from 'react';

// Types for route result data
interface RouteVariant {
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
}

interface RouteResult {
  meshed_area_id: string;
  yacht: {
    id: string;
    name: string;
    type: string;
  };
  time_window: {
    start_time: string;
    end_time: string;
    num_checks: number;
  };
  variants_count: number;
  variants: RouteVariant[];
  best_variant: RouteVariant | null;
  validation: {
    navigable_vertices: number;
    total_vertices: number;
    coverage_percent: number;
    valid_weather_points: number;
    total_weather_points: number;
  };
  difficulty: {
    overall_score: number;
    level: string;
    best_variant_score: number;
    worst_variant_score: number;
    breakdown: Record<string, any>;
  };
}

interface RouteResultsProps {
  result: RouteResult;
  onClose: () => void;
  onViewVisualization: (meshedAreaId: string) => void;
}

// Helper: format time
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
  switch (level.toLowerCase()) {
    case 'easy': return 'text-green-600 bg-green-100';
    case 'moderate': return 'text-yellow-600 bg-yellow-100';
    case 'challenging': return 'text-orange-600 bg-orange-100';
    case 'difficult': return 'text-red-600 bg-red-100';
    case 'extreme': return 'text-purple-600 bg-purple-100';
    default: return 'text-slate-600 bg-slate-100';
  }
};

export default function RouteResults({ result, onClose, onViewVisualization }: RouteResultsProps) {
  const [selectedVariantId, setSelectedVariantId] = useState<string | null>(
    result.best_variant?.variant_id || null
  );
  const [showAllVariants, setShowAllVariants] = useState(true);
  const [activeTab, setActiveTab] = useState<'variants' | 'details' | 'comparison'>('variants');

  const selectedVariant = result.variants.find(v => v.variant_id === selectedVariantId);

  // Find fastest and shortest variants
  const fastestVariant = result.variants.reduce((prev, curr) =>
    curr.total_time_hours < prev.total_time_hours ? curr : prev
  );
  const shortestVariant = result.variants.reduce((prev, curr) =>
    curr.total_distance_nm < prev.total_distance_nm ? curr : prev
  );

  return (
    <div className="fixed inset-0 bg-black/50 backdrop-blur-sm z-[2000] flex items-center justify-center p-4">
      <div className="bg-white rounded-xl shadow-2xl max-w-4xl w-full max-h-[90vh] flex flex-col overflow-hidden">

        {/* HEADER */}
        <div className="bg-gradient-to-r from-blue-600 to-green-600 text-white px-6 py-4 flex justify-between items-center">
          <div>
            <h2 className="text-xl font-bold flex items-center gap-2">
              🏁 Wyniki Obliczenia Trasy
            </h2>
            <p className="text-sm opacity-80">
              {result.yacht.name} • {result.variants_count} wariant{result.variants_count !== 1 ? 'ów' : ''}
            </p>
          </div>
          <button
            onClick={onClose}
            className="p-2 hover:bg-white/20 rounded-full transition-colors"
          >
            ✕
          </button>
        </div>

        {/* SUMMARY BAR */}
        <div className="bg-slate-50 px-6 py-3 border-b flex flex-wrap gap-4 text-sm">
          <div className="flex items-center gap-2">
            <span className="text-slate-500">Najszybsza:</span>
            <span className="font-bold text-green-600">{formatDuration(fastestVariant.total_time_hours)}</span>
          </div>
          <div className="flex items-center gap-2">
            <span className="text-slate-500">Najkrótsza:</span>
            <span className="font-bold text-blue-600">{shortestVariant.total_distance_nm.toFixed(1)} nm</span>
          </div>
          <div className="flex items-center gap-2">
            <span className="text-slate-500">Trudność:</span>
            <span className={`font-bold px-2 py-0.5 rounded text-xs ${getDifficultyColor(result.difficulty.level)}`}>
              {result.difficulty.level}
            </span>
          </div>
          <div className="ml-auto">
            <button
              onClick={() => onViewVisualization(result.meshed_area_id)}
              className="text-blue-600 hover:text-blue-800 font-medium flex items-center gap-1"
            >
              🗺️ Pełna wizualizacja →
            </button>
          </div>
        </div>

        {/* TABS */}
        <div className="flex border-b">
          {(['variants', 'details', 'comparison'] as const).map(tab => (
            <button
              key={tab}
              onClick={() => setActiveTab(tab)}
              className={`flex-1 py-3 text-sm font-medium transition-colors ${
                activeTab === tab 
                  ? 'text-blue-600 border-b-2 border-blue-600 bg-blue-50' 
                  : 'text-slate-500 hover:text-slate-700 hover:bg-slate-50'
              }`}
            >
              {tab === 'variants' && '📋 Warianty'}
              {tab === 'details' && '📊 Szczegóły'}
              {tab === 'comparison' && '⚖️ Porównanie'}
            </button>
          ))}
        </div>

        {/* CONTENT */}
        <div className="flex-1 overflow-y-auto p-4">

          {/* TAB: VARIANTS */}
          {activeTab === 'variants' && (
            <div className="space-y-3">
              {result.variants.map((variant, idx) => (
                <div
                  key={variant.variant_id}
                  onClick={() => setSelectedVariantId(variant.variant_id)}
                  className={`
                    p-4 rounded-lg border-2 cursor-pointer transition-all
                    ${selectedVariantId === variant.variant_id 
                      ? 'border-blue-500 bg-blue-50 shadow-md' 
                      : 'border-slate-200 hover:border-blue-300 hover:bg-slate-50'}
                  `}
                >
                  <div className="flex items-start justify-between">
                    <div className="flex items-center gap-3">
                      <div className={`
                        w-10 h-10 rounded-full flex items-center justify-center text-lg font-bold
                        ${variant.is_best ? 'bg-green-500 text-white' : 'bg-slate-200 text-slate-600'}
                      `}>
                        {idx + 1}
                      </div>
                      <div>
                        <div className="font-bold text-slate-800 flex items-center gap-2">
                          {formatDateTime(variant.departure_time)}
                          {variant.is_best && (
                            <span className="text-xs bg-green-500 text-white px-2 py-0.5 rounded-full">
                              BEST
                            </span>
                          )}
                        </div>
                        <div className="text-sm text-slate-500">
                          {formatDuration(variant.total_time_hours)} • {variant.total_distance_nm.toFixed(1)} nm
                        </div>
                      </div>
                    </div>

                    <div className="text-right">
                      <div className={`text-xs px-2 py-1 rounded ${getDifficultyColor(variant.difficulty_level)}`}>
                        {variant.difficulty_level}
                      </div>
                      <div className="text-xs text-slate-400 mt-1">
                        {variant.average_speed_knots.toFixed(1)} kt avg
                      </div>
                    </div>
                  </div>

                  {/* Stats row */}
                  <div className="mt-3 pt-3 border-t border-slate-200 grid grid-cols-4 gap-2 text-xs">
                    <div className="text-center">
                      <div className="text-slate-400">Wiatr</div>
                      <div className="font-bold">{variant.avg_wind_speed.toFixed(1)} kt</div>
                    </div>
                    <div className="text-center">
                      <div className="text-slate-400">Fale</div>
                      <div className="font-bold">{variant.avg_wave_height.toFixed(2)} m</div>
                    </div>
                    <div className="text-center">
                      <div className="text-slate-400">Zwroty</div>
                      <div className="font-bold">{variant.tacks_count}</div>
                    </div>
                    <div className="text-center">
                      <div className="text-slate-400">Przejścia</div>
                      <div className="font-bold">{variant.jibes_count}</div>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}

          {/* TAB: DETAILS */}
          {activeTab === 'details' && selectedVariant && (
            <div className="space-y-4">
              <h3 className="font-bold text-lg text-slate-800">
                Szczegóły wariantu: {formatDateTime(selectedVariant.departure_time)}
              </h3>

              <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
                <div className="bg-slate-50 rounded-lg p-4">
                  <div className="text-xs text-slate-500 uppercase">Czas podróży</div>
                  <div className="text-2xl font-bold text-slate-800">
                    {formatDuration(selectedVariant.total_time_hours)}
                  </div>
                </div>
                <div className="bg-slate-50 rounded-lg p-4">
                  <div className="text-xs text-slate-500 uppercase">Dystans</div>
                  <div className="text-2xl font-bold text-slate-800">
                    {selectedVariant.total_distance_nm.toFixed(2)} nm
                  </div>
                </div>
                <div className="bg-slate-50 rounded-lg p-4">
                  <div className="text-xs text-slate-500 uppercase">Śr. prędkość</div>
                  <div className="text-2xl font-bold text-slate-800">
                    {selectedVariant.average_speed_knots.toFixed(1)} kt
                  </div>
                </div>
                <div className="bg-blue-50 rounded-lg p-4">
                  <div className="text-xs text-blue-600 uppercase">Śr. wiatr</div>
                  <div className="text-2xl font-bold text-blue-800">
                    {selectedVariant.avg_wind_speed.toFixed(1)} kt
                  </div>
                </div>
                <div className="bg-cyan-50 rounded-lg p-4">
                  <div className="text-xs text-cyan-600 uppercase">Śr. fale</div>
                  <div className="text-2xl font-bold text-cyan-800">
                    {selectedVariant.avg_wave_height.toFixed(2)} m
                  </div>
                </div>
                <div className="bg-orange-50 rounded-lg p-4">
                  <div className="text-xs text-orange-600 uppercase">Trudność</div>
                  <div className="text-2xl font-bold text-orange-800">
                    {selectedVariant.difficulty_score}
                  </div>
                </div>
              </div>

              <div className="grid grid-cols-2 gap-4 mt-4">
                <div className="bg-amber-50 rounded-lg p-4">
                  <div className="text-xs text-amber-600 uppercase mb-2">Manewry</div>
                  <div className="flex justify-around">
                    <div className="text-center">
                      <div className="text-3xl font-bold text-amber-800">{selectedVariant.tacks_count}</div>
                      <div className="text-xs text-amber-600">Zwrotów</div>
                    </div>
                    <div className="text-center">
                      <div className="text-3xl font-bold text-amber-800">{selectedVariant.jibes_count}</div>
                      <div className="text-xs text-amber-600">Przejść</div>
                    </div>
                  </div>
                </div>
                <div className="bg-slate-50 rounded-lg p-4">
                  <div className="text-xs text-slate-500 uppercase mb-2">Segmenty</div>
                  <div className="text-center">
                    <div className="text-3xl font-bold text-slate-800">{selectedVariant.segments_count}</div>
                    <div className="text-xs text-slate-500">odcinków trasy</div>
                  </div>
                </div>
              </div>

              {/* Validation info */}
              <div className="mt-4 p-4 bg-slate-100 rounded-lg">
                <h4 className="font-bold text-sm text-slate-700 mb-2">📊 Walidacja</h4>
                <div className="grid grid-cols-2 gap-2 text-xs">
                  <div>
                    <span className="text-slate-500">Nawigowalne wierzchołki:</span>
                    <span className="ml-2 font-bold">
                      {result.validation.navigable_vertices}/{result.validation.total_vertices}
                      ({result.validation.coverage_percent.toFixed(1)}%)
                    </span>
                  </div>
                  <div>
                    <span className="text-slate-500">Punkty pogodowe:</span>
                    <span className="ml-2 font-bold">
                      {result.validation.valid_weather_points}/{result.validation.total_weather_points}
                    </span>
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* TAB: COMPARISON */}
          {activeTab === 'comparison' && (
            <div className="space-y-4">
              <h3 className="font-bold text-lg text-slate-800">Porównanie wariantów</h3>

              {/* Comparison table */}
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead className="bg-slate-100">
                    <tr>
                      <th className="px-3 py-2 text-left">#</th>
                      <th className="px-3 py-2 text-left">Wyjście</th>
                      <th className="px-3 py-2 text-right">Czas</th>
                      <th className="px-3 py-2 text-right">Dystans</th>
                      <th className="px-3 py-2 text-right">Prędkość</th>
                      <th className="px-3 py-2 text-right">Wiatr</th>
                      <th className="px-3 py-2 text-right">Fale</th>
                      <th className="px-3 py-2 text-center">Trudność</th>
                    </tr>
                  </thead>
                  <tbody>
                    {result.variants.map((v, idx) => (
                      <tr
                        key={v.variant_id}
                        className={`border-b ${v.is_best ? 'bg-green-50' : 'hover:bg-slate-50'}`}
                      >
                        <td className="px-3 py-2 font-bold">{idx + 1}</td>
                        <td className="px-3 py-2">
                          {formatDateTime(v.departure_time)}
                          {v.is_best && <span className="ml-1 text-green-600">⭐</span>}
                        </td>
                        <td className="px-3 py-2 text-right font-mono">
                          {formatDuration(v.total_time_hours)}
                        </td>
                        <td className="px-3 py-2 text-right font-mono">
                          {v.total_distance_nm.toFixed(1)} nm
                        </td>
                        <td className="px-3 py-2 text-right font-mono">
                          {v.average_speed_knots.toFixed(1)} kt
                        </td>
                        <td className="px-3 py-2 text-right font-mono">
                          {v.avg_wind_speed.toFixed(1)} kt
                        </td>
                        <td className="px-3 py-2 text-right font-mono">
                          {v.avg_wave_height.toFixed(2)} m
                        </td>
                        <td className="px-3 py-2 text-center">
                          <span className={`px-2 py-0.5 rounded text-xs ${getDifficultyColor(v.difficulty_level)}`}>
                            {v.difficulty_level}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              {/* Stats summary */}
              <div className="grid grid-cols-3 gap-4 mt-4">
                <div className="bg-green-50 rounded-lg p-4 text-center">
                  <div className="text-xs text-green-600 uppercase">Najszybszy</div>
                  <div className="font-bold text-green-800">
                    {formatDateTime(fastestVariant.departure_time)}
                  </div>
                  <div className="text-sm text-green-600">
                    {formatDuration(fastestVariant.total_time_hours)}
                  </div>
                </div>
                <div className="bg-blue-50 rounded-lg p-4 text-center">
                  <div className="text-xs text-blue-600 uppercase">Najkrótszy</div>
                  <div className="font-bold text-blue-800">
                    {formatDateTime(shortestVariant.departure_time)}
                  </div>
                  <div className="text-sm text-blue-600">
                    {shortestVariant.total_distance_nm.toFixed(1)} nm
                  </div>
                </div>
                <div className="bg-slate-50 rounded-lg p-4 text-center">
                  <div className="text-xs text-slate-500 uppercase">Różnica czasu</div>
                  <div className="font-bold text-slate-800">
                    {formatDuration(
                      Math.max(...result.variants.map(v => v.total_time_hours)) -
                      Math.min(...result.variants.map(v => v.total_time_hours))
                    )}
                  </div>
                  <div className="text-sm text-slate-500">max - min</div>
                </div>
              </div>
            </div>
          )}
        </div>

        {/* FOOTER */}
        <div className="border-t px-6 py-4 bg-slate-50 flex justify-between items-center">
          <div className="text-xs text-slate-500">
            ID: {result.meshed_area_id.slice(0, 8)}...
          </div>
          <div className="flex gap-3">
            <button
              onClick={() => onViewVisualization(result.meshed_area_id)}
              className="px-4 py-2 bg-blue-600 text-white rounded-lg font-medium hover:bg-blue-700 transition-colors"
            >
              🗺️ Otwórz mapę
            </button>
            <button
              onClick={onClose}
              className="px-4 py-2 bg-slate-200 text-slate-700 rounded-lg font-medium hover:bg-slate-300 transition-colors"
            >
              Zamknij
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}