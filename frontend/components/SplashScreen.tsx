'use client';

import { useState, useEffect } from 'react';

interface SplashScreenProps {
  onFinish: () => void;
  minDuration?: number;
}

export default function SplashScreen({ onFinish, minDuration = 2500 }: SplashScreenProps) {
  const [phase, setPhase] = useState<'loading' | 'exit'>('loading');
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
    const timer = setTimeout(() => {
      setPhase('exit');
      setTimeout(onFinish, 800);
    }, minDuration);

    return () => clearTimeout(timer);
  }, [minDuration, onFinish]);

  if (!mounted) return null;

  return (
    <>
      <style dangerouslySetInnerHTML={{ __html: `
        @keyframes splash-spin-slow {
          from { transform: rotate(0deg); }
          to { transform: rotate(360deg); }
        }
        @keyframes splash-spin-very-slow {
          from { transform: rotate(0deg); }
          to { transform: rotate(360deg); }
        }
        @keyframes splash-spin-reverse {
          from { transform: rotate(360deg); }
          to { transform: rotate(0deg); }
        }
        @keyframes splash-ping-slow {
          0% { transform: scale(1); opacity: 0.3; }
          50% { transform: scale(1.1); opacity: 0.1; }
          100% { transform: scale(1); opacity: 0.3; }
        }
        @keyframes splash-pulse-slow {
          0%, 100% { opacity: 0.1; transform: scale(1); }
          50% { opacity: 0.2; transform: scale(1.05); }
        }
        @keyframes splash-pulse-slower {
          0%, 100% { opacity: 0.1; transform: scale(1); }
          50% { opacity: 0.15; transform: scale(1.08); }
        }
        @keyframes splash-wave-draw {
          0% { stroke-dasharray: 0 1000; }
          50% { stroke-dasharray: 500 1000; }
          100% { stroke-dasharray: 0 1000; stroke-dashoffset: -1000; }
        }
        @keyframes splash-progress-slide {
          0% { transform: translateX(-100%); }
          100% { transform: translateX(200%); }
        }
      `}} />

      <div
        className="fixed inset-0 z-[9999] flex items-center justify-center transition-opacity duration-700"
        style={{
          backgroundColor: '#050a12',
          opacity: phase === 'exit' ? 0 : 1
        }}
      >
        {/* Gradient orbs background */}
        <div className="absolute inset-0 overflow-hidden">
          <div
            className="absolute top-1/4 -left-20 w-96 h-96 rounded-full blur-3xl"
            style={{
              backgroundColor: 'rgba(37, 99, 235, 0.1)',
              animation: 'splash-pulse-slow 4s ease-in-out infinite'
            }}
          />
          <div
            className="absolute bottom-1/4 -right-20 w-80 h-80 rounded-full blur-3xl"
            style={{
              backgroundColor: 'rgba(6, 182, 212, 0.1)',
              animation: 'splash-pulse-slower 5s ease-in-out infinite'
            }}
          />
          <div
            className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[600px] h-[600px] rounded-full blur-3xl"
            style={{ backgroundColor: 'rgba(30, 58, 138, 0.2)' }}
          />
        </div>

        {/* Main animation container */}
        <div className="relative">

          {/* Outer rotating ring */}
          <div className="absolute inset-0 flex items-center justify-center">
            <div
              className="w-64 h-64 rounded-full"
              style={{
                border: '1px solid rgba(59, 130, 246, 0.2)',
                animation: 'splash-spin-very-slow 20s linear infinite'
              }}
            />
          </div>

          {/* Middle pulsing ring */}
          <div className="absolute inset-0 flex items-center justify-center">
            <div
              className="w-48 h-48 rounded-full"
              style={{
                border: '2px solid rgba(34, 211, 238, 0.3)',
                animation: 'splash-ping-slow 3s ease-in-out infinite'
              }}
            />
          </div>

          {/* Compass rose / Wind rose */}
          <div
            className="relative w-40 h-40"
            style={{ animation: 'splash-spin-slow 8s linear infinite' }}
          >
            {/* Cardinal directions - main points */}
            {[0, 90, 180, 270].map((angle) => (
              <div
                key={angle}
                className="absolute top-1/2 left-1/2 w-1 h-16"
                style={{
                  transform: `translateX(-50%) rotate(${angle}deg)`,
                  transformOrigin: 'center bottom'
                }}
              >
                <div
                  className="w-full h-full rounded-full"
                  style={{ background: 'linear-gradient(to top, #60a5fa, transparent)' }}
                />
              </div>
            ))}

            {/* Intercardinal directions - secondary points */}
            {[45, 135, 225, 315].map((angle) => (
              <div
                key={angle}
                className="absolute top-1/2 left-1/2 w-0.5 h-10"
                style={{
                  transform: `translateX(-50%) rotate(${angle}deg)`,
                  transformOrigin: 'center bottom'
                }}
              >
                <div
                  className="w-full h-full rounded-full"
                  style={{ background: 'linear-gradient(to top, rgba(34, 211, 238, 0.6), transparent)' }}
                />
              </div>
            ))}

            {/* Center dot */}
            <div
              className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-4 h-4 rounded-full"
              style={{
                backgroundColor: '#60a5fa',
                boxShadow: '0 0 20px rgba(96, 165, 250, 0.5)'
              }}
            />
          </div>

          {/* Orbiting dots */}
          <div
            className="absolute inset-0 flex items-center justify-center"
            style={{ animation: 'splash-spin-reverse 12s linear infinite' }}
          >
            <div className="relative w-56 h-56">
              {[0, 120, 240].map((angle, i) => (
                <div
                  key={angle}
                  className="absolute top-1/2 left-1/2 w-2 h-2"
                  style={{
                    transform: `rotate(${angle}deg) translateY(-110px)`,
                    transformOrigin: '0 0'
                  }}
                >
                  <div
                    className="w-2 h-2 rounded-full"
                    style={{
                      backgroundColor: '#22d3ee',
                      boxShadow: '0 0 10px rgba(34, 211, 238, 0.5)'
                    }}
                  />
                </div>
              ))}
            </div>
          </div>

          {/* Wave lines at bottom */}
          <div className="absolute -bottom-32 left-1/2 -translate-x-1/2 w-80 h-20 overflow-hidden opacity-40">
            <svg className="w-full h-full" viewBox="0 0 320 80">
              <defs>
                <linearGradient id="waveGradient" x1="0%" y1="0%" x2="100%" y2="0%">
                  <stop offset="0%" stopColor="transparent" />
                  <stop offset="50%" stopColor="#22d3ee" />
                  <stop offset="100%" stopColor="transparent" />
                </linearGradient>
              </defs>
              <path
                d="M0 40 Q40 20 80 40 T160 40 T240 40 T320 40"
                fill="none"
                stroke="url(#waveGradient)"
                strokeWidth="2"
                style={{ animation: 'splash-wave-draw 3s ease-in-out infinite' }}
              />
              <path
                d="M0 55 Q40 35 80 55 T160 55 T240 55 T320 55"
                fill="none"
                stroke="url(#waveGradient)"
                strokeWidth="1.5"
                opacity="0.6"
                style={{ animation: 'splash-wave-draw 3s ease-in-out infinite', animationDelay: '0.3s' }}
              />
              <path
                d="M0 70 Q40 50 80 70 T160 70 T240 70 T320 70"
                fill="none"
                stroke="url(#waveGradient)"
                strokeWidth="1"
                opacity="0.3"
                style={{ animation: 'splash-wave-draw 3s ease-in-out infinite', animationDelay: '0.6s' }}
              />
            </svg>
          </div>
        </div>

        {/* Progress line at bottom */}
        <div className="absolute bottom-16 left-1/2 -translate-x-1/2 w-48">
          <div className="h-px rounded-full overflow-hidden" style={{ backgroundColor: 'rgba(30, 41, 59, 0.5)' }}>
            <div
              className="h-full"
              style={{
                background: 'linear-gradient(to right, transparent, #22d3ee, transparent)',
                animation: 'splash-progress-slide 2s ease-in-out infinite'
              }}
            />
          </div>
        </div>

        {/* Corner accents */}
        <div className="absolute top-8 left-8 w-16 h-16">
          <div className="absolute top-0 left-0 w-8 h-px" style={{ background: 'linear-gradient(to right, rgba(96, 165, 250, 0.4), transparent)' }} />
          <div className="absolute top-0 left-0 w-px h-8" style={{ background: 'linear-gradient(to bottom, rgba(96, 165, 250, 0.4), transparent)' }} />
        </div>
        <div className="absolute top-8 right-8 w-16 h-16">
          <div className="absolute top-0 right-0 w-8 h-px" style={{ background: 'linear-gradient(to left, rgba(96, 165, 250, 0.4), transparent)' }} />
          <div className="absolute top-0 right-0 w-px h-8" style={{ background: 'linear-gradient(to bottom, rgba(96, 165, 250, 0.4), transparent)' }} />
        </div>
        <div className="absolute bottom-8 left-8 w-16 h-16">
          <div className="absolute bottom-0 left-0 w-8 h-px" style={{ background: 'linear-gradient(to right, rgba(96, 165, 250, 0.4), transparent)' }} />
          <div className="absolute bottom-0 left-0 w-px h-8" style={{ background: 'linear-gradient(to top, rgba(96, 165, 250, 0.4), transparent)' }} />
        </div>
        <div className="absolute bottom-8 right-8 w-16 h-16">
          <div className="absolute bottom-0 right-0 w-8 h-px" style={{ background: 'linear-gradient(to left, rgba(96, 165, 250, 0.4), transparent)' }} />
          <div className="absolute bottom-0 right-0 w-px h-8" style={{ background: 'linear-gradient(to top, rgba(96, 165, 250, 0.4), transparent)' }} />
        </div>
      </div>
    </>
  );
}