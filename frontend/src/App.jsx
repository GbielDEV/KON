import React, { useState, useEffect, useCallback } from 'react';
import { konWs } from './services/websocket';
import StatusHeader from './components/StatusHeader';
import HologramCore from './components/HologramCore';
import EventConsole from './components/EventConsole';
import VoiceStatusBar from './components/VoiceStatusBar';
import './App.css';

export default function App() {
  const [isConnected, setIsConnected] = useState(false);
  const [assistantState, setAssistantState] = useState('BOOT');
  const [stateDescription, setStateDescription] = useState('KON está inicializando');
  const [telemetry, setTelemetry] = useState(null);
  const [logs, setLogs] = useState([]);
  const [pendingConfirmation, setPendingConfirmation] = useState(null);

  useEffect(() => {
    // 1. Connection updates
    const unsubConn = konWs.subscribe('connection', (data) => {
      setIsConnected(data.connected);
      if (data.connected) {
        setLogs((prev) => [
          ...prev,
          {
            level: 'INFO',
            message: 'Interface conectada ao backend KON (Gemini Live Engine).',
            timestamp: new Date().toISOString(),
          },
        ]);
      } else {
        setLogs((prev) => [
          ...prev,
          {
            level: 'WARN',
            message: 'Conexão perdida. Reconectando automaticamente...',
            timestamp: new Date().toISOString(),
          },
        ]);
      }
    });

    // 2. Assistant state changes
    const unsubState = konWs.subscribe('state', (data) => {
      setAssistantState(data.state);
      setStateDescription(data.description);
    });

    // 3. Streaming transcriptions (ADA V2 style)
    const unsubTrans = konWs.subscribe('transcription', (item) => {
      setLogs((prev) => {
        const last = prev[prev.length - 1];
        if (last && last.level === 'VOICE' && last.sender === item.sender) {
          return [
            ...prev.slice(0, -1),
            {
              ...last,
              message: last.message + item.text,
              timestamp: item.timestamp || last.timestamp,
            },
          ];
        }
        return [
          ...prev.slice(-150),
          {
            level: 'VOICE',
            sender: item.sender,
            message: `${item.sender === 'User' ? 'Você' : 'KON'}: ${item.text}`,
            timestamp: item.timestamp || new Date().toISOString(),
          },
        ];
      });
    });

    // 4. Tool confirmation requests (SAFE / CONFIRM / CRITICAL)
    const unsubConfirm = konWs.subscribe('confirmation', (req) => {
      setPendingConfirmation(req);
      setLogs((prev) => [
        ...prev.slice(-150),
        {
          level: 'WARN',
          message: `[SEGURANÇA] Ação '${req.tool}' (${req.permission}) aguardando autorização.`,
          timestamp: new Date().toISOString(),
        },
      ]);
    });

    // 5. Tool execution notifications
    const unsubExec = konWs.subscribe('executing', (exec) => {
      setLogs((prev) => [
        ...prev.slice(-150),
        {
          level: 'TOOL',
          message: `[EXECUÇÃO] Ferramenta '${exec.tool}' acionada no Windows.`,
          timestamp: new Date().toISOString(),
        },
      ]);
    });

    // 6. Real telemetry metrics
    const unsubTelem = konWs.subscribe('telemetry', (data) => {
      setTelemetry(data);
    });

    // 7. General logs broadcasted from backend
    const unsubLog = konWs.subscribe('log', (logItem) => {
      setLogs((prev) => [...prev.slice(-150), logItem]);
    });

    // 8. Command responses
    const unsubResp = konWs.subscribe('response', (resp) => {
      setLogs((prev) => [
        ...prev.slice(-150),
        {
          level: 'CMD',
          message: `KON: ${resp.message}`,
          timestamp: resp.timestamp || new Date().toISOString(),
        },
      ]);
    });

    // Initialize connection
    konWs.connect();

    return () => {
      unsubConn();
      unsubState();
      unsubTrans();
      unsubConfirm();
      unsubExec();
      unsubTelem();
      unsubLog();
      unsubResp();
    };
  }, []);

  const handleClearLogs = useCallback(() => {
    setLogs([]);
  }, []);

  const handleResolveConfirmation = (confirmed) => {
    if (!pendingConfirmation) return;
    konWs.confirmTool(pendingConfirmation.id, confirmed);
    setPendingConfirmation(null);
  };

  return (
    <div className="app-container">
      {/* Top Status & Telemetry Bar */}
      <StatusHeader isConnected={isConnected} telemetry={telemetry} />

      {/* Confirmation Modal for CONFIRM / CRITICAL operations */}
      {pendingConfirmation && (
        <div style={{
          position: 'absolute',
          top: '80px',
          left: '50%',
          transform: 'translateX(-50%)',
          zIndex: 100,
          background: 'rgba(10, 16, 28, 0.95)',
          border: '1px solid #00e5ff',
          boxShadow: '0 0 30px rgba(0, 229, 255, 0.4)',
          borderRadius: '12px',
          padding: '20px 30px',
          maxWidth: '500px',
          width: '90%',
          backdropFilter: 'blur(20px)',
          color: '#fff',
          fontFamily: 'sans-serif',
          textAlign: 'center'
        }}>
          <div style={{ color: '#00e5ff', fontWeight: 'bold', fontSize: '1.1rem', marginBottom: '8px', letterSpacing: '1px' }}>
            AUTORIZAÇÃO DE SEGURANÇA
          </div>
          <div style={{ fontSize: '0.9rem', color: '#ccc', marginBottom: '12px' }}>
            O KON solicita executar: <span style={{ color: '#fff', fontWeight: '600' }}>{pendingConfirmation.tool}</span>
          </div>
          {pendingConfirmation.description && (
            <div style={{ fontSize: '0.8rem', color: '#88a', marginBottom: '16px', fontStyle: 'italic' }}>
              {pendingConfirmation.description}
            </div>
          )}
          <div style={{ display: 'flex', gap: '15px', justifyContent: 'center' }}>
            <button
              onClick={(e) => {
                if (!e.isTrusted) {
                  console.warn("[SECURITY] Tentativa de clique não confiável (isTrusted=false) bloqueada.");
                  return;
                }
                handleResolveConfirmation(true);
              }}
              style={{
                background: 'linear-gradient(135deg, #00e5ff, #0088ff)',
                color: '#000',
                border: 'none',
                borderRadius: '6px',
                padding: '8px 22px',
                fontWeight: 'bold',
                cursor: 'pointer',
                letterSpacing: '1px'
              }}
            >
              AUTORIZAR
            </button>
            <button
              onClick={(e) => {
                if (!e.isTrusted) {
                  console.warn("[SECURITY] Tentativa de clique não confiável (isTrusted=false) bloqueada.");
                  return;
                }
                handleResolveConfirmation(false);
              }}
              style={{
                background: 'rgba(255, 50, 50, 0.2)',
                border: '1px solid rgba(255, 50, 50, 0.5)',
                color: '#ff6666',
                borderRadius: '6px',
                padding: '8px 22px',
                fontWeight: 'bold',
                cursor: 'pointer',
                letterSpacing: '1px'
              }}
            >
              NEGAR
            </button>
          </div>
        </div>
      )}

      {/* Main Visual Stage */}
      <main className="main-content">
        <div className="center-stage">
          <HologramCore 
            state={assistantState} 
            description={stateDescription} 
          />
        </div>

        <div className="side-console">
          <EventConsole 
            logs={logs} 
            onClear={handleClearLogs} 
          />
        </div>
      </main>

      {/* Bottom Voice Status Indicator */}
      <footer className="footer-voice-status">
        <VoiceStatusBar state={assistantState} />
      </footer>
    </div>
  );
}
