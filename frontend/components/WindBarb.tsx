'use client';

import React from 'react';

interface WindBarbProps {
  speed: number;        // prędkość wiatru w węzłach
  direction: number;    // kierunek skąd wieje wiatr (0-360°)
  size?: number;        // rozmiar barba w px
  color?: string;       // kolor
  animated?: boolean;   // czy animować
}

/**
 * WindBarb - standardowe oznaczenie meteorologiczne wiatru
 * 
 * Konwencja:
 * - Krótka kreska (half barb) = 5 węzłów
 * - Długa kreska (full barb) = 10 węzłów  
 * - Trójkąt/flaga (pennant) = 50 węzłów
 * - Kółko = cisza (< 2.5 kt)
 * 
 * Kierunek: barb wskazuje skąd wieje wiatr
 */
export default function WindBarb({ 
  speed, 
  direction, 
  size = 40, 
  color = '#1e40af',
  animated = false 
}: WindBarbProps) {
  
  // Zaokrąglij do najbliższych 5 węzłów
  const roundedSpeed = Math.round(speed / 5) * 5;
  
  // Oblicz składowe
  const pennants = Math.floor(roundedSpeed / 50);        // flagi (50 kt)
  const fullBarbs = Math.floor((roundedSpeed % 50) / 10); // długie kreski (10 kt)
  const halfBarbs = Math.floor((roundedSpeed % 10) / 5);  // krótkie kreski (5 kt)
  
  // Cisza - kółko
  if (roundedSpeed < 3) {
    return (
      <svg 
        width={size} 
        height={size} 
        viewBox="0 0 40 40"
        className={animated ? 'wind-barb-calm' : ''}
      >
        <circle 
          cx="20" 
          cy="20" 
          r="8" 
          fill="none" 
          stroke={color} 
          strokeWidth="2"
        />
        <circle 
          cx="20" 
          cy="20" 
          r="3" 
          fill={color}
        />
      </svg>
    );
  }
  
  // Buduj elementy barba
  const elements: React.ReactNode[] = [];
  let yOffset = 4; // Start od góry
  
  // Kółko na końcu (punkt obserwacji)
  elements.push(
    <circle 
      key="base" 
      cx="20" 
      cy="36" 
      r="3" 
      fill={color}
    />
  );
  
  // Linia główna (trzon)
  elements.push(
    <line 
      key="shaft" 
      x1="20" 
      y1="36" 
      x2="20" 
      y2="4" 
      stroke={color} 
      strokeWidth="2"
      strokeLinecap="round"
    />
  );
  
  // Dodaj flagi (pennants) - 50 kt każda
  for (let i = 0; i < pennants; i++) {
    elements.push(
      <polygon 
        key={`pennant-${i}`}
        points={`20,${yOffset} 32,${yOffset + 4} 20,${yOffset + 8}`}
        fill={color}
      />
    );
    yOffset += 8;
  }
  
  // Dodaj długie kreski (full barbs) - 10 kt każda
  for (let i = 0; i < fullBarbs; i++) {
    elements.push(
      <line 
        key={`full-${i}`}
        x1="20" 
        y1={yOffset + 2} 
        x2="32" 
        y2={yOffset - 2}
        stroke={color} 
        strokeWidth="2"
        strokeLinecap="round"
      />
    );
    yOffset += 6;
  }
  
  // Dodaj krótkie kreski (half barbs) - 5 kt każda
  for (let i = 0; i < halfBarbs; i++) {
    elements.push(
      <line 
        key={`half-${i}`}
        x1="20" 
        y1={yOffset + 2} 
        x2="26" 
        y2={yOffset - 1}
        stroke={color} 
        strokeWidth="2"
        strokeLinecap="round"
      />
    );
    yOffset += 5;
  }
  
  return (
    <svg 
      width={size} 
      height={size} 
      viewBox="0 0 40 40"
      style={{ 
        transform: `rotate(${direction}deg)`,
        transformOrigin: 'center center',
        transition: animated ? 'transform 0.5s ease-out' : 'none'
      }}
      className={animated ? 'wind-barb-animated' : ''}
    >
      {elements}
    </svg>
  );
}

/**
 * WindBarbLegend - legenda do wind barbs
 */
export function WindBarbLegend({ className = '' }: { className?: string }) {
  const examples = [
    { speed: 0, label: 'Cisza' },
    { speed: 5, label: '5 kt' },
    { speed: 10, label: '10 kt' },
    { speed: 15, label: '15 kt' },
    { speed: 25, label: '25 kt' },
    { speed: 50, label: '50 kt' },
  ];
  
  return (
    <div className={`bg-white/90 backdrop-blur-sm rounded-lg p-3 shadow-lg ${className}`}>
      <div className="text-xs font-bold text-slate-700 mb-2 border-b pb-1">
        Barby wiatru
      </div>
      <div className="grid grid-cols-3 gap-2">
        {examples.map(({ speed, label }) => (
          <div key={speed} className="flex flex-col items-center">
            <WindBarb speed={speed} direction={0} size={30} />
            <span className="text-[10px] text-slate-500 mt-1">{label}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

/**
 * WindIndicator - kompaktowy wskaźnik wiatru z barbem i tekstem
 */
export function WindIndicator({ 
  speed, 
  direction,
  showText = true,
  size = 'md'
}: { 
  speed: number; 
  direction: number;
  showText?: boolean;
  size?: 'sm' | 'md' | 'lg';
}) {
  const sizes = {
    sm: { barb: 24, text: 'text-[10px]' },
    md: { barb: 36, text: 'text-xs' },
    lg: { barb: 48, text: 'text-sm' },
  };
  
  const { barb, text } = sizes[size];
  
  // Konwersja kierunku na nazwę
  const getDirectionName = (deg: number): string => {
    const dirs = ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW'];
    const index = Math.round(deg / 45) % 8;
    return dirs[index];
  };
  
  // Kolor w zależności od siły wiatru
  const getWindColor = (spd: number): string => {
    if (spd < 5) return '#94a3b8';      // slate-400 - cisza
    if (spd < 10) return '#22c55e';     // green-500 - lekki
    if (spd < 15) return '#3b82f6';     // blue-500 - umiarkowany
    if (spd < 20) return '#f59e0b';     // amber-500 - świeży
    if (spd < 30) return '#f97316';     // orange-500 - silny
    return '#ef4444';                    // red-500 - sztormowy
  };
  
  const color = getWindColor(speed);
  
  return (
    <div className="flex items-center gap-1">
      <WindBarb 
        speed={speed} 
        direction={direction} 
        size={barb} 
        color={color}
        animated
      />
      {showText && (
        <div className={`${text} font-mono`}>
          <div className="font-bold" style={{ color }}>
            {speed.toFixed(0)} kt
          </div>
          <div className="text-slate-400">
            {getDirectionName(direction)} ({direction.toFixed(0)}°)
          </div>
        </div>
      )}
    </div>
  );
}