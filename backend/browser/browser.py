"""
Browser control service for KON Assistant.
Provides tab management, navigation, web searching, and page inspection.
"""
from __future__ import annotations

import time
import webbrowser
import urllib.parse
from typing import Dict, Any, Optional

from backend.core.logger import kon_logger


def _get_computer_use():
    from backend.computer.computer_use import ComputerUseService
    return ComputerUseService


class BrowserService:
    """
    Manages browser interactions and GUI tab navigation.
    """

    @classmethod
    def open_url(cls, url: str) -> Dict[str, Any]:
        """
        Opens a URL in the user's default browser.
        """
        clean_url = url.strip()
        if not clean_url.startswith(("http://", "https://")):
            clean_url = f"https://{clean_url}"
        try:
            kon_logger.info(f"[BROWSER] Abrindo URL: {clean_url}")
            webbrowser.open(clean_url)
            return {"success": True, "url": clean_url, "message": f"Abrindo {clean_url} no navegador."}
        except Exception as err:
            kon_logger.error(f"[BROWSER] Erro ao abrir URL: {err}")
            return {"success": False, "error": str(err), "url": clean_url}

    @classmethod
    def search_web(cls, query: str) -> Dict[str, Any]:
        """
        Performs a Google web search in the default browser.
        """
        encoded = urllib.parse.quote_plus(query.strip())
        url = f"https://www.google.com/search?q={encoded}"
        return cls.open_url(url)

    # Alias
    search = search_web

    @classmethod
    def new_browser_tab(cls, url: Optional[str] = None) -> Dict[str, Any]:
        """
        Opens a new tab in the browser. If a URL is provided, navigates to it.
        """
        if url:
            clean_url = url.strip()
            if not clean_url.startswith(("http://", "https://")):
                clean_url = f"https://{clean_url}"
            try:
                webbrowser.open_new_tab(clean_url)
                return {"success": True, "url": clean_url, "message": f"Nova aba aberta em {clean_url}."}
            except Exception as e:
                kon_logger.debug(f"[BROWSER] Falha no open_new_tab: {e}")

        # Fallback using keyboard shortcut Ctrl+T
        _get_computer_use().hotkey(["ctrl", "t"])
        if url:
            time.sleep(0.2)
            cls.navigate_browser(url)
            return {"success": True, "url": url, "message": f"Nova aba aberta e navegando para {url}."}
        return {"success": True, "message": "Nova aba do navegador aberta."}

    @classmethod
    def close_browser_tab(cls) -> Dict[str, Any]:
        """
        Closes the currently active browser tab using Ctrl+W.
        """
        _get_computer_use().hotkey(["ctrl", "w"])
        return {"success": True, "message": "Aba atual fechada."}

    @classmethod
    def switch_browser_tab(cls, index: Optional[int] = None, direction: str = "next") -> Dict[str, Any]:
        """
        Switches between browser tabs.
        If index is provided (1 to 8), uses Ctrl+1..8.
        If direction is 'previous' or 'prev', uses Ctrl+Shift+Tab.
        Otherwise uses Ctrl+Tab.
        """
        if index is not None and 1 <= int(index) <= 8:
            _get_computer_use().hotkey(["ctrl", str(index)])
            return {"success": True, "tab_index": index, "message": f"Alternado para a aba {index}."}

        clean_dir = direction.lower().strip()
        if clean_dir in ("previous", "prev", "anterior", "voltar"):
            _get_computer_use().hotkey(["ctrl", "shift", "tab"])
            return {"success": True, "direction": "previous", "message": "Alternado para a aba anterior."}
        else:
            _get_computer_use().hotkey(["ctrl", "tab"])
            return {"success": True, "direction": "next", "message": "Alternado para a próxima aba."}

    @classmethod
    def navigate_browser(cls, url: str) -> Dict[str, Any]:
        """
        Navigates to a URL in the currently focused browser window by focusing
        the address bar (Ctrl+L), typing the URL, and pressing Enter.
        """
        clean_url = url.strip()
        if not clean_url.startswith(("http://", "https://")):
            clean_url = f"https://{clean_url}"

        # Focus address bar
        _get_computer_use().hotkey(["ctrl", "l"])
        time.sleep(0.1)
        # Type URL
        _get_computer_use().type_text(clean_url)
        time.sleep(0.05)
        # Press Enter
        _get_computer_use().press_key("enter")

        return {"success": True, "url": clean_url, "message": f"Navegando para {clean_url}."}

    @classmethod
    def browser_go_back(cls) -> Dict[str, Any]:
        """Navigates back in browser history (Alt+Left)."""
        _get_computer_use().hotkey(["alt", "left"])
        return {"success": True, "message": "Voltando para a página anterior no navegador."}

    @classmethod
    def browser_go_forward(cls) -> Dict[str, Any]:
        """Navigates forward in browser history (Alt+Right)."""
        _get_computer_use().hotkey(["alt", "right"])
        return {"success": True, "message": "Avançando para a próxima página no navegador."}

    @classmethod
    def browser_reload(cls) -> Dict[str, Any]:
        """Reloads the current page (Ctrl+R)."""
        _get_computer_use().hotkey(["ctrl", "r"])
        return {"success": True, "message": "Página recarregada."}

    @classmethod
    def browser_read_page(cls) -> Dict[str, Any]:
        """
        Inspects accessible UI elements of the active browser window.
        """
        active = _get_computer_use().get_active_window()
        obs = _get_computer_use().observe_ui(max_elements=30)
        return {
            "success": True,
            "browser_window": active.get("title", ""),
            "elements_count": obs.get("elements_found", 0),
            "elements": obs.get("elements", []),
            "message": f"Leitura da página ativa concluída: '{active.get('title')}'.",
        }
