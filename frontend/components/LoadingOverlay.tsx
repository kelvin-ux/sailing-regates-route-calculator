export default function LoadingOverlay() {
  return (
    <div className="absolute inset-0 z-[2000] bg-slate-900/60 backdrop-blur-sm flex flex-col items-center justify-center text-white">
      {/* Kontener animacji */}
      <div className="w-80 bg-slate-700 rounded-full h-4 mb-4 overflow-hidden shadow-lg border border-slate-600">
        {/* Pasek postępu z animacją infinite */}
        <div className="h-full bg-blue-500 animate-[loading_2s_ease-in-out_infinite] w-1/2 rounded-full relative">
          <div className="absolute inset-0 bg-white/30 animate-pulse"></div>
        </div>
      </div>

      <h2 className="text-2xl font-bold mb-2 tracking-wide">Przetwarzanie danych</h2>
      <p className="text-slate-300 text-sm animate-pulse">Analiza warunków pogodowych i wyznaczanie trasy...</p>

      {/* Styl dla animacji paska (można też dodać w globals.css, ale tu dla szybkości w style tagu) */}
      <style jsx>{`
        @keyframes loading {
          0% { transform: translateX(-100%); }
          50% { transform: translateX(100%); }
          100% { transform: translateX(-100%); }
        }
      `}</style>
    </div>
  );
}