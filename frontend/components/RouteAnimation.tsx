'use client';

import React, { useState, useEffect, useRef, useCallback } from 'react';
import { WindIndicator } from './WindBarb';

// Typy segmentów z backendu
interface RouteSegment {
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
  start_time?: string;
  end_time?: string;
}

interface RouteAnimationProps {
  segments: RouteSegment[];
  isPlaying: boolean;
  onPlayPause: () => void;
  onStop: () => void;
  onPositionChange: (position: [number, number], bearing: number, progress: number) => void;
  onSegmentChange?: (segmentIndex: number, segment: RouteSegment) => void;
}

// Stany animacji
type PlaybackSpeed = 1 | 2 | 4 | 8 | 16;

export default function RouteAnimation({
  segments,
  isPlaying,
  onPlayPause,
  onStop,
  onPositionChange,
  onSegmentChange
}: RouteAnimationProps) {
  const [progress, setProgress] = useState(0); // 0-1
  const [speed, setSpeed] = useState<PlaybackSpeed>(1);
  const [currentSegmentIndex, setCurrentSegmentIndex] = useState(0);
  const animationRef = useRef<number | null>(null);
  const lastTimeRef = useRef<number>(0);
  
  // Oblicz całkowity czas trasy
  const totalTimeSeconds = segments.reduce((sum, seg) => sum + seg.time_seconds, 0);
  
  // Znajdź segment i pozycję dla danego progressu
  const getPositionAtProgress = useCallback((prog: number): {
    position: [number, number];
    bearing: number;
    segmentIndex: number;
    segmentProgress: number;
  } => {
    if (segments.length === 0) {
      return { position: [0, 0], bearing: 0, segmentIndex: 0, segmentProgress: 0 };
    }
    
    const targetTime = prog * totalTimeSeconds;
    let accumulatedTime = 0;
    
    for (let i = 0; i < segments.length; i++) {
      const seg = segments[i];
      const segEndTime = accumulatedTime + seg.time_seconds;
      
      if (targetTime <= segEndTime || i === segments.length - 1) {
        // Jesteśmy w tym segmencie
        const segmentProgress = seg.time_seconds > 0 
          ? (targetTime - accumulatedTime) / seg.time_seconds 
          : 0;
        
        // Interpoluj pozycję
        const lat = seg.from.lat + (seg.to.lat - seg.from.lat) * Math.min(segmentProgress, 1);
        const lon = seg.from.lon + (seg.to.lon - seg.from.lon) * Math.min(segmentProgress, 1);
        
        return {
          position: [lat, lon],
          bearing: seg.bearing,
          segmentIndex: i,
          segmentProgress: Math.min(segmentProgress, 1)
        };
      }
      
      accumulatedTime = segEndTime;
    }
    
    // Fallback - koniec trasy
    const lastSeg = segments[segments.length - 1];
    return {
      position: [lastSeg.to.lat, lastSeg.to.lon],
      bearing: lastSeg.bearing,
      segmentIndex: segments.length - 1,
      segmentProgress: 1
    };
  }, [segments, totalTimeSeconds]);
  
  // Główna pętla animacji
  useEffect(() => {
    if (!isPlaying || segments.length === 0) {
      if (animationRef.current) {
        cancelAnimationFrame(animationRef.current);
        animationRef.current = null;
      }
      return;
    }
    
    const animate = (timestamp: number) => {
      if (!lastTimeRef.current) {
        lastTimeRef.current = timestamp;
      }
      
      const deltaMs = timestamp - lastTimeRef.current;
      lastTimeRef.current = timestamp;
      
      // Oblicz nowy progress
      // deltaMs to rzeczywisty czas, ale animujemy speed-krotnie szybciej
      const progressDelta = (deltaMs / 1000) * speed / totalTimeSeconds;
      
      setProgress(prev => {
        const newProgress = Math.min(prev + progressDelta, 1);
        
        // Jeśli dotarliśmy do końca
        if (newProgress >= 1) {
          onStop();
          return 1;
        }
        
        return newProgress;
      });
      
      animationRef.current = requestAnimationFrame(animate);
    };
    
    lastTimeRef.current = 0;
    animationRef.current = requestAnimationFrame(animate);
    
    return () => {
      if (animationRef.current) {
        cancelAnimationFrame(animationRef.current);
      }
    };
  }, [isPlaying, speed, totalTimeSeconds, onStop, segments.length]);
  
  // Update pozycji przy zmianie progressu
  useEffect(() => {
    const { position, bearing, segmentIndex, segmentProgress } = getPositionAtProgress(progress);
    onPositionChange(position, bearing, progress);
    
    if (segmentIndex !== currentSegmentIndex) {
      setCurrentSegmentIndex(segmentIndex);
      if (onSegmentChange && segments[segmentIndex]) {
        onSegmentChange(segmentIndex, segments[segmentIndex]);
      }
    }
  }, [progress, getPositionAtProgress, onPositionChange, onSegmentChange, currentSegmentIndex, segments]);
  
  // Formatowanie czasu
  const formatTime = (seconds: number): string => {
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    const s = Math.floor(seconds % 60);
    
    if (h > 0) {
      return `${h}:${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
    }
    return `${m}:${s.toString().padStart(2, '0')}`;
  };
  
  // Aktualny segment
  const currentSegment = segments[currentSegmentIndex];
  const currentTime = progress * totalTimeSeconds;
  const remainingTime = totalTimeSeconds - currentTime;
  
  // Nazwa punktu żeglarskiego
  const getPointOfSailName = (twa: number): string => {
    const absTwa = Math.abs(twa);
    if (absTwa < 30) return 'Martwa strefa';
    if (absTwa < 50) return 'Ostro';
    if (absTwa < 70) return 'Półwiatr ostry';
    if (absTwa < 110) return 'Półwiatr';
    if (absTwa < 150) return 'Baksztag';
    if (absTwa < 170) return 'Fordewind';
    return 'Z wiatrem';
  };
  
  // Kolor TWA
  const getTwaColor = (twa: number): string => {
    const absTwa = Math.abs(twa);
    if (absTwa < 30) return 'text-red-500';     // martwa strefa
    if (absTwa < 50) return 'text-orange-500';  // ostro
    if (absTwa < 110) return 'text-green-500';  // półwiatr - najlepszy
    if (absTwa < 150) return 'text-blue-500';   // baksztag
    return 'text-purple-500';                   // fordewind
  };
  
  // Reset
  const handleStop = () => {
    setProgress(0);
    setCurrentSegmentIndex(0);
    lastTimeRef.current = 0;
    onStop();
  };
  
  // Seek
  const handleSeek = (e: React.ChangeEvent<HTMLInputElement>) => {
    const newProgress = parseFloat(e.target.value);
    setProgress(newProgress);
  };
  
  if (segments.length === 0) {
    return null;
  }
  
  return (
    <div className="bg-slate-900/95 backdrop-blur-md rounded-xl shadow-2xl border border-slate-700 overflow-hidden">
      {/* Header z info o segmencie */}
      <div className="px-4 py-3 bg-gradient-to-r from-blue-900 to-slate-900 border-b border-slate-700">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="text-2xl">⛵</div>
            <div>
              <div className="text-sm font-bold text-white">
                Segment {currentSegmentIndex + 1}/{segments.length}
              </div>
              <div className="text-xs text-slate-400">
                {currentSegment ? getPointOfSailName(currentSegment.twa) : '-'}
              </div>
            </div>
          </div>
          
          {/* Wind indicator */}
          {currentSegment && (
            <WindIndicator 
              speed={currentSegment.wind_speed_knots}
              direction={currentSegment.wind_direction}
              size="md"
            />
          )}
        </div>
      </div>
      
      {/* Stats row */}
      {currentSegment && (
        <div className="px-4 py-2 grid grid-cols-4 gap-2 text-center bg-slate-800/50 border-b border-slate-700">
          <div>
            <div className="text-[10px] text-slate-500 uppercase">Kurs</div>
            <div className="text-sm font-bold text-white font-mono">
              {currentSegment.bearing.toFixed(0)}°
            </div>
          </div>
          <div>
            <div className="text-[10px] text-slate-500 uppercase">TWA</div>
            <div className={`text-sm font-bold font-mono ${getTwaColor(currentSegment.twa)}`}>
              {currentSegment.twa > 0 ? '+' : ''}{currentSegment.twa.toFixed(0)}°
            </div>
          </div>
          <div>
            <div className="text-[10px] text-slate-500 uppercase">Prędkość</div>
            <div className="text-sm font-bold text-emerald-400 font-mono">
              {currentSegment.boat_speed_knots.toFixed(1)} kt
            </div>
          </div>
          <div>
            <div className="text-[10px] text-slate-500 uppercase">Fale</div>
            <div className="text-sm font-bold text-cyan-400 font-mono">
              {currentSegment.wave_height_m.toFixed(1)} m
            </div>
          </div>
        </div>
      )}
      
      {/* Progress bar */}
      <div className="px-4 py-3">
        <div className="relative">
          <input
            type="range"
            min="0"
            max="1"
            step="0.001"
            value={progress}
            onChange={handleSeek}
            className="w-full h-2 bg-slate-700 rounded-lg appearance-none cursor-pointer
                       [&::-webkit-slider-thumb]:appearance-none
                       [&::-webkit-slider-thumb]:w-4
                       [&::-webkit-slider-thumb]:h-4
                       [&::-webkit-slider-thumb]:bg-blue-500
                       [&::-webkit-slider-thumb]:rounded-full
                       [&::-webkit-slider-thumb]:shadow-lg
                       [&::-webkit-slider-thumb]:cursor-pointer
                       [&::-webkit-slider-thumb]:transition-transform
                       [&::-webkit-slider-thumb]:hover:scale-110"
            style={{
              background: `linear-gradient(to right, 
                #3b82f6 0%, 
                #3b82f6 ${progress * 100}%, 
                #334155 ${progress * 100}%, 
                #334155 100%)`
            }}
          />
        </div>
        
        {/* Time display */}
        <div className="flex justify-between text-xs text-slate-400 mt-1 font-mono">
          <span>{formatTime(currentTime)}</span>
          <span className="text-slate-500">
            {(progress * 100).toFixed(1)}%
          </span>
          <span>-{formatTime(remainingTime)}</span>
        </div>
      </div>
      
      {/* Controls */}
      <div className="px-4 py-3 bg-slate-800/30 border-t border-slate-700 flex items-center justify-between">
        {/* Playback controls */}
        <div className="flex items-center gap-2">
          {/* Stop */}
          <button
            onClick={handleStop}
            className="w-10 h-10 rounded-full bg-slate-700 hover:bg-slate-600 
                       flex items-center justify-center text-white transition-colors"
            title="Stop"
          >
            <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor">
              <rect x="3" y="3" width="10" height="10" rx="1" />
            </svg>
          </button>
          
          {/* Play/Pause */}
          <button
            onClick={onPlayPause}
            className="w-14 h-14 rounded-full bg-blue-600 hover:bg-blue-500 
                       flex items-center justify-center text-white transition-all
                       shadow-lg shadow-blue-600/30 hover:shadow-blue-500/40
                       active:scale-95"
            title={isPlaying ? 'Pauza' : 'Odtwórz'}
          >
            {isPlaying ? (
              <svg width="24" height="24" viewBox="0 0 24 24" fill="currentColor">
                <rect x="6" y="5" width="4" height="14" rx="1" />
                <rect x="14" y="5" width="4" height="14" rx="1" />
              </svg>
            ) : (
              <svg width="24" height="24" viewBox="0 0 24 24" fill="currentColor">
                <path d="M8 5.14v14.72a1 1 0 001.5.86l11-7.36a1 1 0 000-1.72l-11-7.36a1 1 0 00-1.5.86z" />
              </svg>
            )}
          </button>
        </div>
        
        {/* Speed control */}
        <div className="flex items-center gap-1">
          <span className="text-xs text-slate-500 mr-2">Prędkość:</span>
          {([1, 2, 4, 8, 16] as PlaybackSpeed[]).map(s => (
            <button
              key={s}
              onClick={() => setSpeed(s)}
              className={`px-2 py-1 rounded text-xs font-bold transition-all
                ${speed === s 
                  ? 'bg-blue-600 text-white shadow-md' 
                  : 'bg-slate-700 text-slate-400 hover:bg-slate-600 hover:text-white'
                }`}
            >
              {s}x
            </button>
          ))}
        </div>
        
        {/* Total time */}
        <div className="text-right">
          <div className="text-xs text-slate-500">Całkowity czas</div>
          <div className="text-sm font-bold text-white font-mono">
            {formatTime(totalTimeSeconds)}
          </div>
        </div>
      </div>
    </div>
  );
}

/**
 * Kompaktowy przycisk do uruchomienia animacji (dla panelu bocznego)
 */
export function AnimationToggleButton({
  isAnimating,
  onClick,
  disabled = false
}: {
  isAnimating: boolean;
  onClick: () => void;
  disabled?: boolean;
}) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className={`
        w-full py-3 rounded-lg font-bold text-sm transition-all
        flex items-center justify-center gap-2
        ${disabled 
          ? 'bg-slate-300 text-slate-500 cursor-not-allowed'
          : isAnimating
            ? 'bg-orange-500 hover:bg-orange-600 text-white shadow-lg shadow-orange-500/30'
            : 'bg-gradient-to-r from-blue-600 to-cyan-600 hover:from-blue-500 hover:to-cyan-500 text-white shadow-lg shadow-blue-600/30'
        }
        active:scale-[0.98]
      `}
    >
      {isAnimating ? (
        <>
          <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor">
            <rect x="6" y="5" width="4" height="14" rx="1" />
            <rect x="14" y="5" width="4" height="14" rx="1" />
          </svg>
          Zatrzymaj animację
        </>
      ) : (
        <>
          <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor">
            <path d="M8 5.14v14.72a1 1 0 001.5.86l11-7.36a1 1 0 000-1.72l-11-7.36a1 1 0 00-1.5.86z" />
          </svg>
          Animuj trasę
        </>
      )}
    </button>
  );
}