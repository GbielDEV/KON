"""
Media command handlers for KON Assistant.
"""
from voice_assistant.commands.registry import command
from backend.core.logger import kon_logger


@command("tocar_musica", description="Inicia reprodução de áudio ou mídia.")
def tocar_musica() -> dict:
    """
    Safely triggers audio playback or media player.
    """
    kon_logger.info("[COMMAND] Executando tocar_musica...")
    return {
        "success": True,
        "response_text": "Iniciando a reprodução de música.",
        "media": "default",
    }
