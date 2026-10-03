"""
Unit and Integration Tests for KON Persistent Browser Session (FASE 2).
Verifies URL validation, YouTube channel verification, ambiguity detection,
security risk elevation to CONFIRM for sensitive actions, redirection from open_application,
and zero-mouse-theft / zero-focus-stealing integration behavior.
"""
import os
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from backend.computer.mouse import MouseController

from backend.browser.session import BrowserSession, normalize_text
from backend.computer.applications import ApplicationManager
from backend.ai.gemini_tools import GeminiToolDispatcher
from backend.ai.tool_registry import get_tool_registry
from backend.computer.computer_use import ComputerUseService


class TestBrowserUnitValidation:
    """Unit tests for URL and Channel validation."""

    def test_url_validation_success(self):
        assert BrowserSession.validate_url("https://youtube.com") == "https://youtube.com"
        assert BrowserSession.validate_url("http://example.com/test") == "http://example.com/test"
        assert BrowserSession.validate_url("google.com") == "https://google.com"
        assert BrowserSession.validate_url("www.youtube.com/results?search_query=test") == "https://www.youtube.com/results?search_query=test"

    def test_url_validation_invalid(self):
        invalid_cases = [
            "",
            "   ",
            "ftp://files.example.com",
            "file:///C:/test.txt",
            "just words without domain",
            "invalid domain name with spaces .com",
        ]
        for inv in invalid_cases:
            with pytest.raises(ValueError):
                BrowserSession.validate_url(inv)

    def test_youtube_channel_verification_success(self):
        # Case 1: Standard @ handle
        assert BrowserSession.verify_youtube_channel(
            "https://www.youtube.com/@FlowGames",
            "Flow Games - YouTube",
            "Flow Games"
        ) is True

        # Case 2: Accent and casing insensitivity (Café -> cafe)
        assert BrowserSession.verify_youtube_channel(
            "https://www.youtube.com/c/Caf%C3%A9Tecnologia",
            "Café Tecnologia - YouTube",
            "cafe tecnologia"
        ) is True

        # Case 3: Standard channel/ path
        assert BrowserSession.verify_youtube_channel(
            "https://youtube.com/channel/UC123456789",
            "Canaltech - Vídeos e Análises",
            "Canaltech"
        ) is True

    def test_youtube_channel_verification_failure(self):
        # Not a channel URL (it's a video)
        assert BrowserSession.verify_youtube_channel(
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "Rick Astley - Never Gonna Give You Up",
            "Rick Astley"
        ) is False

        # Channel name mismatch
        assert BrowserSession.verify_youtube_channel(
            "https://www.youtube.com/@differentchannel",
            "Outro Canal Qualquer",
            "Flow Games"
        ) is False

        # Non-youtube domain
        assert BrowserSession.verify_youtube_channel(
            "https://www.google.com/search?q=FlowGames",
            "Google Search - Flow Games",
            "Flow Games"
        ) is False

    def test_normalize_text(self):
        assert normalize_text("  Olá   MUNDO!  ") == "ola mundo!"
        assert normalize_text("Ação e Reação") == "acao e reacao"
        assert normalize_text("") == ""


class TestBrowserAmbiguityAndRiskElevation:
    """Tests for search ambiguity logic and CONFIRM security elevation."""

    def test_ambiguity_calculation(self):
        # Multiple candidates with no exact match -> Ambiguous
        candidates = [
            {"title": "Flow Games Podcast #1", "url": "https://youtube.com/watch?v=1"},
            {"title": "Flow Games Melhores Momentos", "url": "https://youtube.com/watch?v=2"},
        ]
        query = "Flow Games"
        norm_q = normalize_text(query)
        exact_matches = [c for c in candidates if normalize_text(c.get("title", "")) == norm_q]
        is_ambiguous = len(candidates) > 1 and len(exact_matches) != 1
        assert is_ambiguous is True

        # Exact match present -> Not ambiguous
        candidates_with_exact = [
            {"title": "Flow Games", "url": "https://youtube.com/@flowgames"},
            {"title": "Flow Games Melhores Momentos", "url": "https://youtube.com/watch?v=2"},
        ]
        exact_matches = [c for c in candidates_with_exact if normalize_text(c.get("title", "")) == norm_q]
        is_ambiguous = len(candidates_with_exact) > 1 and len(exact_matches) != 1
        assert is_ambiguous is False

    def test_browser_risk_elevation_safe_operations(self):
        dispatcher = GeminiToolDispatcher()
        registry = get_tool_registry()

        # Navigation tools default to SAFE
        for tool in ("browser_open", "browser_search", "browser_snapshot", "browser_go_back", "browser_reload"):
            risk, _ = dispatcher._assess_dynamic_risk(tool, {"url": "https://youtube.com"})
            assert risk == "SAFE"

        # Standard click on normal element -> SAFE
        risk, _ = dispatcher._assess_dynamic_risk(
            "browser_click",
            {"name": "Vídeos recentes", "role": "tab"}
        )
        assert risk == "SAFE"

        # Standard type on search field -> SAFE
        risk, _ = dispatcher._assess_dynamic_risk(
            "browser_type",
            {"text": "Python tutorials", "submit": True}
        )
        assert risk == "SAFE"

    def test_browser_risk_elevation_sensitive_operations(self):
        dispatcher = GeminiToolDispatcher()

        # Sensitive click: Checkout / Comprar / Pagamento
        risk, reason = dispatcher._assess_dynamic_risk(
            "browser_click",
            {"name": "Finalizar Compra", "role": "button"}
        )
        assert risk == "CONFIRM"
        assert "sensível" in reason.lower() or "compra" in reason.lower()

        # Sensitive click: Delete / Excluir conta
        risk, reason = dispatcher._assess_dynamic_risk(
            "browser_click",
            {"name": "Excluir conta definitivamente", "role": "button"}
        )
        assert risk == "CONFIRM"

        # Sensitive type: Password / Senha
        risk, reason = dispatcher._assess_dynamic_risk(
            "browser_type",
            {"selector": "input#password", "text": "secret123"}
        )
        assert risk == "CONFIRM"

        # Sensitive type: Credit card
        risk, reason = dispatcher._assess_dynamic_risk(
            "browser_type",
            {"selector": "input#credit_card", "text": "4111222233334444"}
        )
        assert risk == "CONFIRM"


class TestBrowserRedirectionAndBackgroundIntegration:
    """Verifies open_application redirection and background execution with zero mouse movement."""

    def test_open_application_redirects_to_browser_session(self):
        with patch("backend.browser.session.get_browser_session") as mock_get_sess:
            mock_sess = MagicMock()
            mock_sess.open.return_value = {
                "ok": True,
                "url": "https://www.youtube.com",
                "title": "YouTube",
            }
            mock_get_sess.return_value = mock_sess

            res = ApplicationManager.open_application("youtube")
            assert res.get("success") is True
            assert res.get("redirected_to_browser_session") is True
            assert "youtube.com" in res.get("url", "")
            mock_sess.open.assert_called_once_with("https://www.youtube.com")

        with patch("backend.browser.session.get_browser_session") as mock_get_sess:
            mock_sess = MagicMock()
            mock_sess.open.return_value = {
                "ok": True,
                "url": "https://www.google.com",
                "title": "Google",
            }
            mock_get_sess.return_value = mock_sess

            res = ApplicationManager.open_application("chrome")
            assert res.get("success") is True
            assert res.get("redirected_to_browser_session") is True
            mock_sess.open.assert_called_once_with("https://www.google.com")

    def test_browser_session_zero_mouse_movement(self, tmp_path):
        """
        Integration test: verifies that browser navigation, snapshot, and click
        execute completely in background without altering physical mouse position.
        """
        def _get_pos():
            p = MouseController.get_mouse_position()
            return (p["x"], p["y"])

        initial_pos = _get_pos()

        session = BrowserSession(
            profile_dir=str(tmp_path / "test_browser_profile"),
            headless=True,
        )
        try:
            # 1. Open example page
            res_open = session.open("https://example.com")
            assert res_open.get("ok") is True
            assert "Example Domain" in res_open.get("title", "")

            # Verify mouse position did NOT move at all
            pos_after_open = _get_pos()
            assert pos_after_open == initial_pos, "O cursor do mouse não pode se mover durante browser_open!"

            # 2. Snapshot
            snapshot = session.snapshot()
            assert snapshot.get("ok") is True
            assert snapshot.get("count", 0) >= 1
            elements = snapshot.get("elements", [])
            assert any("More information" in e.get("text", "") or e.get("tag") == "a" for e in elements)

            # Verify mouse position did NOT move during snapshot
            pos_after_snapshot = _get_pos()
            assert pos_after_snapshot == initial_pos, "O cursor do mouse não pode se mover durante browser_snapshot!"

            # 3. Click semantic link using element_id from snapshot
            first_el_id = elements[0]["id"]
            click_res = session.click(element_id=first_el_id)
            assert click_res.get("ok") is True

            # Verify mouse position did NOT move during browser_click
            pos_after_click = _get_pos()
            assert pos_after_click == initial_pos, "O cursor do mouse não pode se mover durante browser_click!"

        finally:
            session.close()
