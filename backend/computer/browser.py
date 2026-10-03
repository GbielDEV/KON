"""
Browser Control Integration for Computer Use.
Bridges BrowserService into backend.computer layer with deterministic and GUI navigation.
"""
from __future__ import annotations

from typing import Dict, Any, Optional
from backend.browser.browser import BrowserService


class ComputerBrowser:
    """
    Browser control layer for Computer Use.
    """

    @classmethod
    def open_url(cls, url: str) -> Dict[str, Any]:
        """Opens URL deterministically in default browser."""
        return BrowserService.open_url(url)

    @classmethod
    def search_web(cls, query: str) -> Dict[str, Any]:
        """Searches query on the web."""
        return BrowserService.search_web(query)

    @classmethod
    def new_tab(cls, url: Optional[str] = None) -> Dict[str, Any]:
        """Opens a new browser tab."""
        return BrowserService.new_browser_tab(url)

    @classmethod
    def close_tab(cls) -> Dict[str, Any]:
        """Closes the current browser tab."""
        return BrowserService.close_browser_tab()

    @classmethod
    def switch_tab(cls, index: Optional[int] = None, direction: str = "next") -> Dict[str, Any]:
        """Switches browser tab."""
        return BrowserService.switch_browser_tab(index=index, direction=direction)

    @classmethod
    def navigate(cls, url: str) -> Dict[str, Any]:
        """Navigates to URL via address bar."""
        return BrowserService.navigate_browser(url)

    @classmethod
    def go_back(cls) -> Dict[str, Any]:
        """Goes back in history."""
        return BrowserService.browser_go_back()

    @classmethod
    def go_forward(cls) -> Dict[str, Any]:
        """Goes forward in history."""
        return BrowserService.browser_go_forward()

    @classmethod
    def reload(cls) -> Dict[str, Any]:
        """Reloads active page."""
        return BrowserService.browser_reload()

    @classmethod
    def read_page(cls) -> Dict[str, Any]:
        """Inspects accessible elements in active browser window."""
        return BrowserService.browser_read_page()
