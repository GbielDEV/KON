"""
System command implementations for KON Assistant.
Safe Windows actions without arbitrary shell execution.
"""
from datetime import datetime
from voice_assistant.commands.registry import command
from backend.computer.applications import ApplicationManager
from backend.browser.browser import BrowserService
from backend.core.logger import kon_logger


@command("abrir_navegador", description="Abre o navegador padrão de internet de forma segura.")
def abrir_navegador() -> dict:
    """
    Safely opens the browser.
    Tries Chrome first via ApplicationManager (if installed), otherwise opens default browser via BrowserService.
    """
    kon_logger.info("[COMMAND] Executando abertura de navegador...")

    # Try Chrome if available in allowed applications
    chrome_res = ApplicationManager.open_application("chrome")
    if chrome_res.get("success"):
        return {
            "success": True,
            "response_text": "Abrindo o navegador.",
            "target": "chrome",
        }

    # Fallback to system default browser
    browser_res = BrowserService.open_url("https://www.google.com")
    return {
        "success": browser_res.get("success", True),
        "response_text": "Abrindo o navegador de internet.",
        "target": "default_browser",
    }


@command("informar_horario", description="Informa o horário atual do sistema em português brasileiro.")
def informar_horario() -> dict:
    """
    Returns current Windows local time formatted naturally in Brazilian Portuguese.
    """
    now = datetime.now()
    hour = now.hour
    minute = now.minute

    hour_str = "1 hora" if hour == 1 else f"{hour} horas"
    if minute == 0:
        speech = f"Agora são exatamente {hour_str}."
    elif minute == 1:
        speech = f"Agora são {hour_str} e 1 minuto."
    else:
        speech = f"Agora são {hour_str} e {minute} minutos."

    kon_logger.info(f"[COMMAND] Horário formatado: {speech}")
    return {
        "success": True,
        "response_text": speech,
        "hour": hour,
        "minute": minute,
    }


@command("abrir_pasta", description="Abre uma pasta no Explorador de Arquivos do Windows.")
def abrir_pasta(folder: str = "Downloads") -> dict:
    from backend.computer.files import FileManager
    kon_logger.info(f"[COMMAND] Executando abertura de pasta: {folder}")
    res = FileManager.open_folder(folder)
    return {
        "success": res.get("success", True),
        "response_text": f"Abrindo a pasta {folder}.",
        "target": folder,
    }
