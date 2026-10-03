import React, { useRef, useEffect } from 'react';

export default function EventConsole({ logs, onClear }) {
  const bottomRef = useRef(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [logs]);

  return (
    <aside className="event-console-panel">
      <div className="console-header">
        <div className="console-title">
          <span className="console-terminal-icon">❯_</span>
          <span>CONSOLE DE EVENTOS & LOGS</span>
          <span className="log-count">({logs.length})</span>
        </div>
        <button 
          className="console-clear-btn" 
          onClick={onClear} 
          title="Limpar logs visíveis"
        >
          LIMPAR
        </button>
      </div>

      <div className="console-body">
        {logs.length === 0 ? (
          <div className="empty-logs">
            Aguardando eventos do sistema KON...
          </div>
        ) : (
          logs.map((item, idx) => {
            const timeStr = item.timestamp 
              ? new Date(item.timestamp).toLocaleTimeString() 
              : '--:--:--';
            const levelClass = (item.level || 'INFO').toLowerCase();

            return (
              <div key={idx} className={`console-line level-${levelClass}`}>
                <span className="log-time font-mono">{timeStr}</span>
                <span className={`log-badge badge-${levelClass}`}>
                  [{item.level || 'LOG'}]
                </span>
                <span className="log-text font-mono">{item.message}</span>
              </div>
            );
          })
        )}
        <div ref={bottomRef} />
      </div>
    </aside>
  );
}
