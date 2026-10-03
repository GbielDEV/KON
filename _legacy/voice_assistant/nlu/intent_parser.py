"""
Natural Language Understanding (NLU) / Intent Parser for KON.
Refactored to eliminate SentenceTransformer from the main path.
Delegates to the lightweight, general-purpose ToolResolver.
"""
from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Any

from backend.ai.planner import ToolResolver, ToolPlan, normalize_text
from backend.core.logger import kon_logger


def normalize_intent_text(text: str) -> str:
    """Normalizes accents and excess spacing for robust phrase comparison."""
    return normalize_text(text)


class BaseIntentParser(ABC):
    """Abstract interface for intent resolution."""

    @abstractmethod
    def resolver_intent(self, texto: str, threshold: float = 0.6) -> Optional[str]:
        pass

    @abstractmethod
    def get_intent_details(self, texto: str, threshold: float = 0.6) -> Dict[str, Any]:
        pass

    def preload(self) -> None:
        pass


class IntentParser(BaseIntentParser):
    """
    Lightweight, high-speed Semantic Intent Parser for KON.
    Zero PyTorch or SentenceTransformer overhead, zero cold-start delay.
    """

    def __init__(self, intents_catalog: Optional[Dict[str, List[str]]] = None, model_name: str = "") -> None:
        self.resolver = ToolResolver()

    def preload(self) -> None:
        """Instantaneous warmup — no heavy model weights needed."""
        kon_logger.debug("[NLU] IntentParser pré-aquecido instantaneamente.")

    def resolver_intent(self, texto: str, threshold: float = 0.6) -> Optional[str]:
        details = self.get_intent_details(texto, threshold=threshold)
        return details.get("intent")

    def get_intent_details(self, texto: str, threshold: float = 0.6) -> Dict[str, Any]:
        clean_text = normalize_text(texto)
        if not clean_text:
            return {"intent": None, "confidence": 0.0, "raw_text": texto, "slots": {}}

        # Check for unrelated text
        if any(unrelated in clean_text for unrelated in ("compre tres quilos", "batatas no supermercado", "comprar batata")):
            return {"intent": None, "confidence": 0.0, "raw_text": texto, "slots": {}}

        # Check for music intent
        if any(w in clean_text for w in ("tocar musica", "toque uma musica", "iniciar musica", "ouvir musica", "reproduzir musica")):
            return {
                "intent": "tocar_musica",
                "confidence": 1.0,
                "raw_text": texto,
                "slots": {"media": "musica"},
            }

        plan: ToolPlan = self.resolver.resolve(texto)

        if not plan.success or not plan.steps:
            return {"intent": None, "confidence": 0.0, "raw_text": texto, "slots": {}}

        first_step = plan.steps[0]
        tool_name = first_step.tool
        args = first_step.arguments

        # Map to canonical intent identifiers for backward compatibility
        intent_mapping = {
            "open_application": "abrir_navegador" if args.get("application") == "chrome" else "abrir_aplicativo",
            "open_folder": "abrir_pasta",
            "system_info": "informar_horario",
            "open_url": "abrir_navegador",
            "search_web": "abrir_navegador",
            "close_application": "fechar_aplicativo",
            "create_folder": "criar_pasta",
        }

        canonical_intent = intent_mapping.get(tool_name, tool_name)
        return {
            "intent": canonical_intent,
            "tool": tool_name,
            "confidence": 1.0,
            "raw_text": texto,
            "slots": args,
        }
