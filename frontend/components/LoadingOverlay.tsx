'use client';

interface LoadingOverlayProps {
  message?: string;
  progress?: number;
}

export default function LoadingOverlay({ message = 'Przetwarzanie...', progress = 0 }: LoadingOverlayProps) {
  // Determine current step based on progress
  const currentStep = progress < 33 ? 0 : progress < 66 ? 1 : progress < 100 ? 2 : 3;
  
  const steps = [
    { label: 'Siatka', icon: '◇', description: 'Tworzenie siatki nawigacyjnej' },
    { label: 'Pogoda', icon: '◈', description: 'Pobieranie danych pogodowych' },
    { label: 'Trasa', icon: '◆', description: 'Obliczanie optymalnej trasy' }
  ];

  return (
    <>
      <style dangerouslySetInnerHTML={{ __html: `
        @keyframes loading-spin-slow {
          from { transform: rotate(0deg); }
          to { transform: rotate(360deg); }
        }
        @keyframes loading-spin-reverse {
          from { transform: rotate(360deg); }
          to { transform: rotate(0deg); }
        }
        @keyframes loading-pulse-slow {
          0%, 100% { opacity: 0.1; transform: scale(1); }
          50% { opacity: 0.2; transform: scale(1.05); }
        }
        @keyframes loading-pulse-slower {
          0%, 100% { opacity: 0.1; transform: scale(1); }
          50% { opacity: 0.15; transform: scale(1.08); }
        }
        @keyframes loading-ping-slow {
          0% { transform: scale(1); opacity: 0.3; }
          50% { transform: scale(1.15); opacity: 0.1; }
          100% { transform: scale(1); opacity: 0.3; }
        }
        @keyframes loading-wave-draw {
          0% { stroke-dasharray: 0 1000; }
          50% { stroke-dasharray: 500 1000; }
          100% { stroke-dasharray: 0 1000; stroke-dashoffset: -1000; }
        }
        @keyframes loading-boat-sail {
          0%, 100% { transform: translateY(0) rotate(-2deg); }
          50% { transform: translateY(-8px) rotate(2deg); }
        }
        @keyframes loading-step-pulse {
          0%, 100% { box-shadow: 0 0 0 0 rgba(34, 211, 238, 0.4); }
          50% { box-shadow: 0 0 0 10px rgba(34, 211, 238, 0); }
        }
        @keyframes loading-progress-glow {
          0%, 100% { filter: brightness(1); }
          50% { filter: brightness(1.3); }
        }
      `}} />

      <div
        className="fixed inset-0 z-[9999] flex items-center justify-center"
        style={{ backgroundColor: '#050a12' }}
      >
        {/* Gradient orbs background */}
        <div className="absolute inset-0 overflow-hidden">
          <div
            className="absolute top-1/4 -left-20 w-96 h-96 rounded-full blur-3xl"
            style={{
              backgroundColor: 'rgba(37, 99, 235, 0.1)',
              animation: 'loading-pulse-slow 4s ease-in-out infinite'
            }}
          />
          <div
            className="absolute bottom-1/4 -right-20 w-80 h-80 rounded-full blur-3xl"
            style={{
              backgroundColor: 'rgba(6, 182, 212, 0.1)',
              animation: 'loading-pulse-slower 5s ease-in-out infinite'
            }}
          />
          <div
            className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[600px] h-[600px] rounded-full blur-3xl"
            style={{ backgroundColor: 'rgba(30, 58, 138, 0.15)' }}
          />
        </div>

        {/* Main content container */}
        <div className="relative flex flex-col items-center">

          {/* Compass animation */}
          <div className="relative mb-8">
            {/* Outer rotating ring */}
            <div className="absolute inset-0 flex items-center justify-center">
              <div
                className="w-48 h-48 rounded-full"
                style={{
                  border: '1px solid rgba(59, 130, 246, 0.2)',
                  animation: 'loading-spin-slow 20s linear infinite'
                }}
              />
            </div>

            {/* Middle pulsing ring */}
            <div className="absolute inset-0 flex items-center justify-center">
              <div
                className="w-36 h-36 rounded-full"
                style={{
                  border: '2px solid rgba(34, 211, 238, 0.3)',
                  animation: 'loading-ping-slow 3s ease-in-out infinite'
                }}
              />
            </div>

            {/* Compass rose */}
            <div
              className="relative w-32 h-32"
              style={{ animation: 'loading-spin-slow 8s linear infinite' }}
            >
              {/* Cardinal directions */}
              {[0, 90, 180, 270].map((angle) => (
                <div
                  key={angle}
                  className="absolute top-1/2 left-1/2 w-1 h-12"
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

              {/* Intercardinal directions */}
              {[45, 135, 225, 315].map((angle) => (
                <div
                  key={angle}
                  className="absolute top-1/2 left-1/2 w-0.5 h-8"
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

              {/* Center with boat */}
              <div
                className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 text-3xl"
                style={{ animation: 'loading-boat-sail 2s ease-in-out infinite' }}
              >
              </div>
            </div>

            {/* Orbiting dots */}
            <div
              className="absolute inset-0 flex items-center justify-center"
              style={{ animation: 'loading-spin-reverse 10s linear infinite' }}
            >
              <div className="relative w-44 h-44">
                {[0, 120, 240].map((angle) => (
                  <div
                    key={angle}
                    className="absolute top-1/2 left-1/2 w-2 h-2"
                    style={{
                      transform: `rotate(${angle}deg) translateY(-88px)`,
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
          </div>

          {/* Status message */}
          <h3
            className="text-xl font-medium mb-6 text-center"
            style={{ color: '#e2e8f0' }}
          >
            {message}
          </h3>

          {/* Progress bar */}
          <div className="w-72 mb-8">
            <div
              className="h-1.5 rounded-full overflow-hidden"
              style={{ backgroundColor: 'rgba(30, 41, 59, 0.8)' }}
            >
              <div
                className="h-full rounded-full transition-all duration-700 ease-out"
                style={{
                  width: `${progress}%`,
                  background: 'linear-gradient(to right, #3b82f6, #22d3ee, #10b981)',
                  animation: 'loading-progress-glow 2s ease-in-out infinite'
                }}
              />
            </div>
            <div className="flex justify-between mt-2 text-xs" style={{ color: 'rgba(148, 163, 184, 0.8)' }}>
              <span>0%</span>
              <span className="font-medium" style={{ color: '#22d3ee' }}>{progress}%</span>
              <span>100%</span>
            </div>
          </div>

          {/* Step indicators */}
          <div className="flex items-center gap-4 mb-8">
            {steps.map((step, idx) => {
              const isActive = idx === currentStep;
              const isCompleted = idx < currentStep;
              
              return (
                <div key={idx} className="flex items-center">
                  {/* Step circle */}
                  <div className="flex flex-col items-center">
                    <div
                      className="w-12 h-12 rounded-full flex items-center justify-center text-lg font-bold transition-all duration-500"
                      style={{
                        backgroundColor: isCompleted 
                          ? 'rgba(16, 185, 129, 0.2)' 
                          : isActive 
                            ? 'rgba(34, 211, 238, 0.2)' 
                            : 'rgba(30, 41, 59, 0.5)',
                        border: `2px solid ${
                          isCompleted 
                            ? '#10b981' 
                            : isActive 
                              ? '#22d3ee' 
                              : 'rgba(71, 85, 105, 0.5)'
                        }`,
                        color: isCompleted 
                          ? '#10b981' 
                          : isActive 
                            ? '#22d3ee' 
                            : 'rgba(148, 163, 184, 0.5)',
                        boxShadow: isActive 
                          ? '0 0 20px rgba(34, 211, 238, 0.3)' 
                          : 'none',
                        animation: isActive ? 'loading-step-pulse 2s ease-in-out infinite' : 'none'
                      }}
                    >
                      {isCompleted ? '✓' : step.icon}
                    </div>
                    <span
                      className="mt-2 text-xs font-medium transition-colors duration-300"
                      style={{
                        color: isCompleted 
                          ? '#10b981' 
                          : isActive 
                            ? '#22d3ee' 
                            : 'rgba(148, 163, 184, 0.5)'
                      }}
                    >
                      {step.label}
                    </span>
                  </div>

                  {/* Connector line */}
                  {idx < steps.length - 1 && (
                    <div
                      className="w-12 h-0.5 mx-2 rounded-full transition-colors duration-500"
                      style={{
                        backgroundColor: isCompleted 
                          ? '#10b981' 
                          : 'rgba(71, 85, 105, 0.3)'
                      }}
                    />
                  )}
                </div>
              );
            })}
          </div>

          {/* Wave lines */}
          <div className="w-80 h-12 overflow-hidden opacity-50">
            <svg className="w-full h-full" viewBox="0 0 320 48">
              <defs>
                <linearGradient id="loadingWaveGradient" x1="0%" y1="0%" x2="100%" y2="0%">
                  <stop offset="0%" stopColor="transparent" />
                  <stop offset="50%" stopColor="#22d3ee" />
                  <stop offset="100%" stopColor="transparent" />
                </linearGradient>
              </defs>
              <path
                d="M0 24 Q40 8 80 24 T160 24 T240 24 T320 24"
                fill="none"
                stroke="url(#loadingWaveGradient)"
                strokeWidth="2"
                style={{ animation: 'loading-wave-draw 3s ease-in-out infinite' }}
              />
              <path
                d="M0 36 Q40 20 80 36 T160 36 T240 36 T320 36"
                fill="none"
                stroke="url(#loadingWaveGradient)"
                strokeWidth="1.5"
                opacity="0.6"
                style={{ animation: 'loading-wave-draw 3s ease-in-out infinite', animationDelay: '0.3s' }}
              />
            </svg>
          </div>

          {/* Hint text */}
          <p
            className="mt-6 text-xs text-center max-w-xs"
            style={{ color: 'rgba(148, 163, 184, 0.6)' }}
          >
            Obliczenia mogą potrwać do kilku minut dla skomplikowanych tras...
          </p>
        </div>

        {/* Corner accents */}
        <div className="absolute top-6 left-6 w-12 h-12">
          <div className="absolute top-0 left-0 w-6 h-px" style={{ background: 'linear-gradient(to right, rgba(96, 165, 250, 0.4), transparent)' }} />
          <div className="absolute top-0 left-0 w-px h-6" style={{ background: 'linear-gradient(to bottom, rgba(96, 165, 250, 0.4), transparent)' }} />
        </div>
        <div className="absolute top-6 right-6 w-12 h-12">
          <div className="absolute top-0 right-0 w-6 h-px" style={{ background: 'linear-gradient(to left, rgba(96, 165, 250, 0.4), transparent)' }} />
          <div className="absolute top-0 right-0 w-px h-6" style={{ background: 'linear-gradient(to bottom, rgba(96, 165, 250, 0.4), transparent)' }} />
        </div>
        <div className="absolute bottom-6 left-6 w-12 h-12">
          <div className="absolute bottom-0 left-0 w-6 h-px" style={{ background: 'linear-gradient(to right, rgba(96, 165, 250, 0.4), transparent)' }} />
          <div className="absolute bottom-0 left-0 w-px h-6" style={{ background: 'linear-gradient(to top, rgba(96, 165, 250, 0.4), transparent)' }} />
        </div>
        <div className="absolute bottom-6 right-6 w-12 h-12">
          <div className="absolute bottom-0 right-0 w-6 h-px" style={{ background: 'linear-gradient(to left, rgba(96, 165, 250, 0.4), transparent)' }} />
          <div className="absolute bottom-0 right-0 w-px h-6" style={{ background: 'linear-gradient(to top, rgba(96, 165, 250, 0.4), transparent)' }} />
        </div>
      </div>
    </>
  );
}