import React, { useState } from 'react';

const QUICK_COMMANDS = [
  { label: '🧪 Teste de voz (MOCK)', cmd: 'mock_wake' },
  { label: '📁 Downloads', cmd: 'abrir pasta downloads' },
  { label: '📝 Bloco de Notas', cmd: 'abrir bloco de notas' },
  { label: '🌐 Chrome', cmd: 'abrir google chrome' },
  { label: 'STATUS', cmd: 'status' },
  { label: 'TESTAR CICLO', cmd: 'test' },
];

export default function CommandBar({ onSendCommand, isConnected }) {
  const [inputVal, setInputVal] = useState('');

  const handleSubmit = (e) => {
    e.preventDefault();
    if (!inputVal.trim()) return;
    onSendCommand(inputVal.trim());
    setInputVal('');
  };

  const handleQuick = (cmd) => {
    onSendCommand(cmd);
  };

  return (
    <div className="command-bar-wrapper">
      {/* Quick State Simulation Buttons */}
      <div className="quick-actions-bar">
        <span className="quick-actions-label">Comandos Rápidos:</span>
        <div className="quick-buttons">
          {QUICK_COMMANDS.map((item) => (
            <button
              key={item.label}
              type="button"
              className="quick-btn"
              onClick={() => handleQuick(item.cmd)}
              disabled={!isConnected}
            >
              {item.label}
            </button>
          ))}
        </div>
      </div>

      {/* Main Terminal Input */}
      <form className="command-form" onSubmit={handleSubmit}>
        <div className="command-input-container">
          <span className="command-prompt-symbol">❯</span>
          <input
            type="text"
            className="command-input"
            placeholder={
              isConnected 
                ? 'Digite um comando (ex: status, test, open chrome, open downloads, listen)...' 
                : 'Aguardando conexão com o backend KON...'
            }
            value={inputVal}
            onChange={(e) => setInputVal(e.target.value)}
            disabled={!isConnected}
          />
          <button 
            type="submit" 
            className="command-send-btn" 
            disabled={!isConnected || !inputVal.trim()}
          >
            ENVIAR
          </button>
        </div>
      </form>
    </div>
  );
}
