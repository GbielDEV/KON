"""
Assistant States and Machine for KON Core.
"""
from enum import Enum
from typing import Dict


class AssistantState(str, Enum):
    """
    Standard operating states of the KON assistant.

    BOOT: Transient initialization state while heavy AI models are loading.
          During BOOT, no voice cycles, wake word processing, or tool execution
          are permitted. Transitions to IDLE automatically once preload completes.
    """
    BOOT = "BOOT"
    IDLE = "IDLE"
    LISTENING = "LISTENING"
    THINKING = "THINKING"
    EXECUTING = "EXECUTING"
    SPEAKING = "SPEAKING"
    ERROR = "ERROR"

    # Computer Use cycle states
    COMPUTER_OBSERVING = "COMPUTER_OBSERVING"
    COMPUTER_PLANNING = "COMPUTER_PLANNING"
    COMPUTER_ACTING = "COMPUTER_ACTING"
    COMPUTER_VERIFYING = "COMPUTER_VERIFYING"

    @property
    def description(self) -> str:
        """
        User-friendly localized description of the state.
        """
        descriptions: Dict[str, str] = {
            "BOOT": "KON está inicializando",
            "IDLE": "KON está aguardando",
            "LISTENING": "KON está ouvindo",
            "THINKING": "KON está processando",
            "EXECUTING": "KON está executando",
            "SPEAKING": "KON está respondendo",
            "ERROR": "KON encontrou um erro",
            "COMPUTER_OBSERVING": "KON está observando a tela",
            "COMPUTER_PLANNING": "KON está planejando a ação no computador",
            "COMPUTER_ACTING": "KON está interagindo com o computador",
            "COMPUTER_VERIFYING": "KON está verificando o resultado da ação",
        }
        return descriptions.get(self.value, "Estado desconhecido")

    @classmethod
    def from_string(cls, name: str) -> "AssistantState":
        """
        Safely convert a string into an AssistantState.
        """
        normalized = name.strip().upper()
        for state in cls:
            if state.value == normalized:
                return state
        raise ValueError(f"Invalid AssistantState: '{name}'. Valid states: {[s.value for s in cls]}")
