import React, { useState, useEffect } from 'react';

export default function StatusHeader({ isConnected, telemetry }) {
  const [currentTime, setCurrentTime] = useState(new Date().toLocaleTimeString());

  useEffect(() => {
    const timer = setInterval(() => {
      setCurrentTime(new Date().toLocaleTimeString());
    }, 1000);
    return () => clearInterval(timer);
  }, []);

  const cpu = telemetry?.cpu_percent ?? 0;
  const ramPercent = telemetry?.ram_percent ?? 0;
  const ramUsed = telemetry?.ram_used_gb ?? '0.0';
  const ramTotal = telemetry?.ram_total_gb ?? '0.0';
  const uptime = telemetry?.uptime_formatted ?? '00:00:00';

  return (
    <header className="status-header">
      {/* Brand & Connection status */}
      <div className="header-left">
        <div className="brand-badge">
          <span className="brand-logo">KON</span>
          <span className="brand-version">v1.0</span>
        </div>
        
        <div className={`connection-pill ${isConnected ? 'online' : 'offline'}`}>
          <span className="status-indicator-dot"></span>
          <span className="status-indicator-text">
            {isConnected ? 'SISTEMA ONLINE' : 'DESCONECTADO'}
          </span>
        </div>

        {/* Microphone / Voice Status Pill */}
        <div 
          className={`mic-pill ${telemetry?.microphone_available ? 'mic-active' : 'mic-inactive'}`}
          title={`Dispositivo: ${telemetry?.microphone_device || 'Indisponível'}`}
        >
          <span className="mic-icon">🎙️</span>
          <span className="mic-text">
            {telemetry?.microphone_available ? 'MIC ONLINE' : 'MIC MOCK'}
          </span>
        </div>
      </div>

      {/* Real Hardware Telemetry */}
      <div className="header-center">
        <div className="metric-item" title="Uso real do Processador">
          <span className="metric-label">CPU</span>
          <div className="metric-bar-wrap">
            <div 
              className="metric-bar-fill cpu" 
              style={{ width: `${Math.min(cpu, 100)}%` }}
            />
          </div>
          <span className="metric-value">{cpu}%</span>
        </div>

        <div className="metric-divider">/</div>

        <div className="metric-item" title="Uso real de Memória RAM">
          <span className="metric-label">RAM</span>
          <div className="metric-bar-wrap">
            <div 
              className="metric-bar-fill ram" 
              style={{ width: `${Math.min(ramPercent, 100)}%` }}
            />
          </div>
          <span className="metric-value">{ramPercent}% ({ramUsed}GB)</span>
        </div>

        <div className="metric-divider">/</div>

        <div className="metric-item" title="Tempo de atividade do assistente">
          <span className="metric-label">UPTIME</span>
          <span className="metric-value font-mono">{uptime}</span>
        </div>
      </div>

      {/* Real Time Clock */}
      <div className="header-right">
        <div className="clock-display">
          <span className="clock-icon">◷</span>
          <span className="clock-text font-mono">{currentTime}</span>
        </div>
      </div>
    </header>
  );
}
