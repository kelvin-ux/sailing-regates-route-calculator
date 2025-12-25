'use client';

interface LoadingOverlayProps {
  message?: string;
  progress?: number;
}

export default function LoadingOverlay({ message = 'Przetwarzanie...', progress }: LoadingOverlayProps) {
  return (
    <div className="fixed inset-0 bg-black/60 backdrop-blur-sm z-[9999] flex items-center justify-center">
      <div className="bg-white rounded-xl shadow-2xl p-8 max-w-md w-full mx-4 text-center">
        {/* Animated sailing boat */}
        <div className="relative h-20 mb-6 overflow-hidden">
          <div className="animate-sailing absolute">
            <span className="text-6xl">⛵</span>
          </div>
          {/* Waves */}
          <div className="absolute bottom-0 left-0 right-0 h-4 flex">
            <div className="wave-animation flex-1 text-blue-400 text-2xl">〰️〰️〰️〰️〰️</div>
          </div>
        </div>

        {/* Message */}
        <h3 className="text-lg font-bold text-slate-800 mb-2">{message}</h3>

        {/* Progress bar */}
        {progress !== undefined && (
          <div className="w-full bg-slate-200 rounded-full h-3 mb-3 overflow-hidden">
            <div
              className="bg-gradient-to-r from-blue-500 to-green-500 h-3 rounded-full transition-all duration-500 ease-out"
              style={{ width: `${progress}%` }}
            />
          </div>
        )}

        {/* Step indicators */}
        <div className="flex justify-center gap-2 mt-4">
          <div className={`w-3 h-3 rounded-full transition-colors ${progress && progress >= 33 ? 'bg-blue-500' : 'bg-slate-300'}`} title="Mesh" />
          <div className={`w-3 h-3 rounded-full transition-colors ${progress && progress >= 66 ? 'bg-blue-500' : 'bg-slate-300'}`} title="Weather" />
          <div className={`w-3 h-3 rounded-full transition-colors ${progress && progress >= 100 ? 'bg-green-500' : 'bg-slate-300'}`} title="Route" />
        </div>

        <p className="text-xs text-slate-400 mt-4">
          Proszę czekać, obliczenia mogą potrwać kilka sekund...
        </p>
      </div>

      <style jsx>{`
        @keyframes sailing {
          0% { left: -60px; }
          100% { left: calc(100% + 60px); }
        }
        .animate-sailing {
          animation: sailing 3s ease-in-out infinite;
        }
        @keyframes wave {
          0%, 100% { transform: translateX(0); }
          50% { transform: translateX(-10px); }
        }
        .wave-animation {
          animation: wave 1.5s ease-in-out infinite;
        }
      `}</style>
    </div>
  );
}