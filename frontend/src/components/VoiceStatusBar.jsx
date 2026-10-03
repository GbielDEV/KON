import React from 'react';

/**
 * VoiceStatusBar — Pure visual monitor of the KON voice pipeline state.
 * No buttons. No inputs. No manual interaction.
 * The user controls KON exclusively by voice.
 */

const STATE_DISPLAY = {
  BOOT: {
    icon: '⏳',
    label: 'Inicializando...',
    sublabel: 'Carregando modelos de IA. Aguarde um momento.',
  },
  IDLE: {
    icon: '🟢',
    label: 'Aguardando "Okay KON"',
    sublabel: 'O microfone está ativo. Fale "Okay KON" para iniciar.',
  },
  LISTENING: {
    icon: '🔵',
    label: 'Ouvindo...',
    sublabel: 'Fale o seu comando.',
  },
  THINKING: {
    icon: '🧠',
    label: 'Processando...',
    sublabel: 'Reconhecendo fala e interpretando o comando.',
  },
  EXECUTING: {
    icon: '⚙️',
    label: 'Executando...',
    sublabel: 'Ação em andamento no Windows.',
  },
  SPEAKING: {
    icon: '🔊',
    label: 'Falando...',
    sublabel: 'KON está respondendo por voz.',
  },
  ERROR: {
    icon: '🔴',
    label: 'Erro detectado',
    sublabel: 'Uma falha ocorreu no processamento.',
  },
};

export default function VoiceStatusBar({ state }) {
  const currentState = (state || 'IDLE').toUpperCase();
  const display = STATE_DISPLAY[currentState] || STATE_DISPLAY.IDLE;

  return (
    <div className={`voice-status-bar state-bar-${currentState.toLowerCase()}`}>
      <span className="voice-status-icon">{display.icon}</span>
      <div className="voice-status-text">
        <span className="voice-status-label">{display.label}</span>
        <span className="voice-status-sublabel">{display.sublabel}</span>
      </div>
    </div>
  );
}
