"""
Browser integration module for KON Assistant.
"""
from backend.browser.browser import BrowserService
from backend.browser.session import (
    BrowserSession,
    get_browser_session,
    has_browser_session,
    close_browser_session,
)

__all__ = [
    "BrowserService",
    "BrowserSession",
    "get_browser_session",
    "has_browser_session",
    "close_browser_session",
]
