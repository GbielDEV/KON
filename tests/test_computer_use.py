"""
Unit and integration tests for KON Computer Use & Windows GUI automation.
Tests:
- Screen dimensions and active window detection
- Native Mouse control (move, click, double click, right click, scroll, drag)
- Native Keyboard control (typing text with PT-BR accents, special keys, hotkeys)
- Structured UI observation (observe_ui)
- Window Context Safety Guard (preventing action on unexpected windows)
- Browser control actions (tabs, navigation, page inspection)
- Multi-step execution chain (5+ consecutive actions)
"""
import pytest
from backend.computer.computer_use import (
    ComputerUseService,
    WindowContextMismatchError,
)
from backend.browser.browser import BrowserService
from backend.ai.tool_registry import get_tool_registry


# =====================================================================
# 1. Screen & Window Awareness
# =====================================================================

def test_get_screen_info():
    res = ComputerUseService.get_screen_info()
    assert res["success"] is True
    assert res["width"] > 0
    assert res["height"] > 0


def test_get_active_window_and_list_windows():
    active = ComputerUseService.get_active_window()
    assert "success" in active
    assert "hwnd" in active
    assert "bounds" in active

    all_windows = ComputerUseService.list_windows()
    assert all_windows["success"] is True
    assert "windows" in all_windows


# =====================================================================
# 2. Native Mouse Automation
# =====================================================================

def test_mouse_move_and_clicks():
    # Move mouse
    move_res = ComputerUseService.move_mouse(100, 100)
    assert move_res["success"] is True
    assert move_res["x"] == 100
    assert move_res["y"] == 100

    # Clicks
    click_res = ComputerUseService.click(100, 100, button="left")
    assert click_res["success"] is True
    assert click_res["button"] == "left"

    rclick_res = ComputerUseService.right_click(100, 100)
    assert rclick_res["success"] is True
    assert rclick_res["button"] == "right"

    dclick_res = ComputerUseService.double_click(100, 100)
    assert dclick_res["success"] is True

    # Scroll
    scroll_res = ComputerUseService.scroll(amount=-2)
    assert scroll_res["success"] is True
    assert scroll_res["amount"] == -2


# =====================================================================
# 3. Native Keyboard Automation & PT-BR Accents
# =====================================================================

def test_keyboard_typing_and_hotkey():
    # Type text with Portuguese accents
    text_sample = "Olá! Teste de digitação com acentuação e caracteres: ç, ã, õ, é, í, ó, ú."
    res_type = ComputerUseService.type_text(text_sample)
    assert res_type["success"] is True
    assert res_type["typed_length"] == len(text_sample)

    # Press special key
    res_key = ComputerUseService.press_key("escape")
    assert res_key["success"] is True
    assert res_key["key"] == "escape"

    # Hotkey combination (e.g. shift+tab)
    res_hotkey = ComputerUseService.hotkey(["shift", "tab"])
    assert res_hotkey["success"] is True


# =====================================================================
# 4. Structured UI Observation (Accessibility Tree)
# =====================================================================

def test_structured_ui_observation():
    obs = ComputerUseService.observe_ui(max_elements=15)
    assert obs["success"] is True
    assert "elements" in obs
    assert "window" in obs
    assert len(obs["elements"]) >= 1


# =====================================================================
# 5. Window Context Safety Guard (Window Mismatch Protection)
# =====================================================================

def test_window_context_mismatch_blocks_action():
    """
    Attempting a click or typing with an expected window that does NOT match
    the current active window must raise WindowContextMismatchError.
    """
    with pytest.raises(WindowContextMismatchError, match="Janela ativa inesperada"):
        ComputerUseService.click(100, 100, expected_window="JanelaInexistenteTotalmenteFalsaXYZ_12345")

    with pytest.raises(WindowContextMismatchError, match="Janela ativa inesperada"):
        ComputerUseService.type_text("texto perigoso", expected_window="BancoDoBrasilSeguroOnline")


# =====================================================================
# 6. Browser Control Tools
# =====================================================================

def test_browser_control_methods():
    # URL formatting in open_url
    res_url = BrowserService.open_url("google.com")
    assert res_url["success"] is True
    assert "https://google.com" in res_url["url"]

    # Search web
    res_search = BrowserService.search_web("Inteligência Artificial")
    assert res_search["success"] is True
    assert "google.com/search" in res_search["url"]

    # Tab switching and inspection
    res_tab = BrowserService.switch_browser_tab(direction="next")
    assert res_tab["success"] is True

    res_tab_idx = BrowserService.switch_browser_tab(index=1)
    assert res_tab_idx["success"] is True

    res_history = BrowserService.browser_go_back()
    assert res_history["success"] is True

    res_reload = BrowserService.browser_reload()
    assert res_reload["success"] is True


# =====================================================================
# 7. Multi-step Execution Chain (5+ Actions)
# =====================================================================

def test_multistep_consecutive_gui_actions():
    """Simulates a multi-step Computer Use task executing 5 consecutive actions."""
    registry = get_tool_registry()

    actions = [
        ("get_screen_info", {}),
        ("get_active_window", {}),
        ("move_mouse", {"x": 200, "y": 200}),
        ("scroll", {"amount": -1}),
        ("press_key", {"key": "escape"}),
        ("get_datetime", {}),
    ]

    for tool_name, args in actions:
        res = registry.execute_tool(tool_name, **args)
        assert res["success"] is True, f"Falha na etapa multi-step '{tool_name}': {res.get('error')}"
