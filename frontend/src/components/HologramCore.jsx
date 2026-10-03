import React from 'react';

export default function HologramCore({ state, description }) {
  const currentState = (state || 'IDLE').toUpperCase();

  return (
    <div className={`hologram-container state-${currentState.toLowerCase()}`}>
      <div className="hologram-stage">
        {/* Ambient background glow ring */}
        <div className="ambient-glow" />

        {/* Outer Tech Ring with Segmented Dashes */}
        <div className="ring ring-outer">
          <svg viewBox="0 0 300 300" className="svg-ring">
            <circle
              cx="150"
              cy="150"
              r="140"
              stroke="currentColor"
              strokeWidth="1.5"
              strokeDasharray="4 8"
              fill="none"
              opacity="0.4"
            />
            <circle
              cx="150"
              cy="150"
              r="132"
              stroke="currentColor"
              strokeWidth="2"
              strokeDasharray="20 40 80 40"
              fill="none"
              opacity="0.7"
            />
          </svg>
        </div>

        {/* Middle Counter-Rotating Data Ring */}
        <div className="ring ring-middle">
          <svg viewBox="0 0 300 300" className="svg-ring">
            <circle
              cx="150"
              cy="150"
              r="105"
              stroke="currentColor"
              strokeWidth="2"
              strokeDasharray="12 24"
              fill="none"
              opacity="0.6"
            />
            {/* Tech markers */}
            <line x1="150" y1="35" x2="150" y2="48" stroke="currentColor" strokeWidth="3" />
            <line x1="150" y1="252" x2="150" y2="265" stroke="currentColor" strokeWidth="3" />
            <line x1="35" y1="150" x2="48" y2="150" stroke="currentColor" strokeWidth="3" />
            <line x1="252" y1="150" x2="265" y2="150" stroke="currentColor" strokeWidth="3" />
          </svg>
        </div>

        {/* Dynamic Pulse Waves (Listening / Speaking) */}
        <div className="pulse-wave pulse-wave-1" />
        <div className="pulse-wave pulse-wave-2" />

        {/* Inner Reactor Ring */}
        <div className="ring ring-inner">
          <svg viewBox="0 0 300 300" className="svg-ring">
            <circle
              cx="150"
              cy="150"
              r="75"
              stroke="currentColor"
              strokeWidth="2.5"
              strokeDasharray="8 6"
              fill="none"
              opacity="0.85"
            />
          </svg>
        </div>

        {/* Central Luminous Core */}
        <div className="core-orb">
          <div className="core-inner-glow" />
          <div className="core-center-point">
            <div className="point-dot" />
          </div>
        </div>

        {/* Dynamic State Audio Bars (for SPEAKING & LISTENING) */}
        {currentState === 'SPEAKING' && (
          <div className="audio-visualizer-bars">
            <span className="bar b1"></span>
            <span className="bar b2"></span>
            <span className="bar b3"></span>
            <span className="bar b4"></span>
            <span className="bar b5"></span>
            <span className="bar b6"></span>
            <span className="bar b7"></span>
          </div>
        )}
      </div>

      {/* State Label & Subtext */}
      <div className="hologram-labels">
        <div className="state-badge">
          <span className="state-name">{currentState}</span>
        </div>
        <h2 className="state-description">{description || 'KON está aguardando'}</h2>
        <div className="state-subtext">
          {currentState === 'BOOT' && 'Inicializando subsistemas de IA...'}
          {currentState === 'IDLE' && 'Aguardando wake word "Okay KON"'}
          {currentState === 'LISTENING' && 'Capturando áudio do usuário...'}
          {currentState === 'THINKING' && 'Reconhecendo fala e interpretando o comando...'}
          {currentState === 'EXECUTING' && 'Executando ação no Windows...'}
          {currentState === 'SPEAKING' && 'KON está respondendo por voz...'}
          {currentState === 'ERROR' && 'Falha ou exceção detectada no fluxo'}
        </div>
      </div>
    </div>
  );
}
