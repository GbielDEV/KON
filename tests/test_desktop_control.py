"""
Automated unit tests for KON Full Desktop Control and Visual Computer Use.
Verifies application management, smooth mouse control, Portuguese Unicode typing,
UI Automation accessibility, contextual security, and natural language planner resolution.
"""
from unittest.mock import patch, MagicMock

from backend.computer.applications import ApplicationManager
from backend.computer.mouse import MouseController
from backend.computer.keyboard import KeyboardController
from backend.computer.screen import ScreenService
from backend.computer.uia import UIAutomationService
from backend.computer.computer_use import ComputerUseService
from backend.ai.tool_registry import get_tool_registry
from backend.ai.planner import ToolResolver


def test_application_discovery_and_listing():
    """Tests discovery of installed applications on Windows."""
    apps = ApplicationManager.discover_installed_applications()
    assert isinstance(apps, dict)
    assert len(apps) > 0  # Should find at least registry/common apps

    listing = ApplicationManager.list_installed_applications(query="chrome")
    assert listing["success"] is True
    assert "applications" in listing


def test_mouse_smooth_movement_and_bounds():
    """Tests smooth mouse interpolation, clamping and coordinates."""
    w, h = MouseController.get_screen_bounds()
    assert w > 0 and h > 0

    # Smooth movement clamped
    res = MouseController.move_mouse(x=100, y=150, smooth=True, steps=5)
    assert res["success"] is True
    assert res["x"] == 100
    assert res["y"] == 150

    # Out of bounds clamped to max
    res_clamped = MouseController.move_mouse(x=99999, y=99999, smooth=False)
    assert res_clamped["success"] is True
    assert res_clamped["x"] == w - 1
    assert res_clamped["y"] == h - 1


def test_mouse_down_and_up():
    """Tests mouse_down and mouse_up state primitives."""
    down_res = ComputerUseService.mouse_down(button="left")
    assert down_res["success"] is True

    up_res = ComputerUseService.mouse_up(button="left")
    assert up_res["success"] is True


def test_keyboard_portuguese_accents_and_string_hotkey():
    """Tests native typing of all Brazilian Portuguese special characters and string hotkeys."""
    pt_sample = "Configuração e Ação: maçã, café, avô, água, saída, coração, 100%!"
    type_res = KeyboardController.type_text(pt_sample)
    assert type_res["success"] is True
    assert type_res["typed_length"] == len(pt_sample)

    # String format hotkey "ctrl+l"
    hk_res = KeyboardController.hotkey("ctrl+l")
    assert hk_res["success"] is True
    assert "combination" in hk_res

    # List format hotkey ["alt", "tab"]
    hk_list_res = KeyboardController.hotkey(["alt", "tab"])
    assert hk_list_res["success"] is True


def test_screen_service_monitor_enumeration():
    """Tests screen resolution metrics and multi-monitor enumeration."""
    info = ScreenService.get_screen_info()
    assert info["success"] is True
    assert info["width"] > 0
    assert info["height"] > 0
    assert "monitors" in info
    assert info["monitors_count"] >= 1


def test_ui_automation_service_safe_fallback():
    """Tests that UIAutomationService returns structured data without crashing."""
    elements = UIAutomationService.inspect_window_elements(hwnd=0, max_elements=10)
    assert isinstance(elements, list)

    match = UIAutomationService.find_element("nonexistent_widget_12345")
    assert match is None


def test_contextual_security_blocks_destructive_clicks():
    """Tests that clicking on elements with destructive keywords enforces confirmation."""
    # Attempting to click on "Excluir Arquivo" must trigger confirmation requirement
    res = ComputerUseService.click_element("Excluir Todos os Arquivos")
    assert res["success"] is False
    assert res["error"] == "CONFIRMATION_REQUIRED"
    assert res.get("requires_confirmation") is True


def test_computer_use_orchestrator():
    """Tests high-level computer_use orchestrator execution."""
    ComputerUseService.reset_safety_counters()
    result = ComputerUseService.computer_use(
        goal="Verificar tela e rolar",
        steps=[
            {"action": "move_mouse", "x": 200, "y": 200},
            {"action": "scroll", "amount": -2},
        ]
    )
    assert result["success"] is True
    assert result["total_steps"] == 2
    assert len(result["executed_steps"]) == 2


def test_tool_registry_contains_new_desktop_tools():
    """Verifies that all newly required desktop control tools are properly registered."""
    registry = get_tool_registry()

    expected_tools = [
        "open_application", "close_application", "list_installed_applications", "switch_window",
        "move_mouse", "click", "double_click", "right_click", "mouse_down", "mouse_up", "drag", "scroll",
        "type_text", "press_key", "hotkey",
        "take_screenshot", "get_screen_info", "get_active_window", "observe_ui", "find_ui_element", "click_element",
        "open_url", "new_browser_tab", "close_browser_tab", "switch_browser_tab", "browser_go_back", "browser_go_forward",
        "computer_use",
    ]

    for tool_name in expected_tools:
        assert registry.has_tool(tool_name), f"Ferramenta '{tool_name}' não está registrada no ToolRegistry!"


def test_planner_resolves_desktop_control_natural_language():
    """Tests that spoken natural language phrases map accurately to desktop control tools."""
    resolver = ToolResolver()

    # 1. Switch window
    plan1 = resolver.resolve("troque para o VS Code")
    assert plan1.success is True
    assert plan1.steps[0].tool == "switch_window"
    assert plan1.steps[0].arguments["target"] == "code"

    # 2. Type text
    plan2 = resolver.resolve("digite Olá, como você está?")
    assert plan2.success is True
    assert plan2.steps[0].tool == "type_text"
    assert "Olá, como você está?" in plan2.steps[0].arguments["text"]

    # 3. Press key / Hotkey
    plan3 = resolver.resolve("pressione Ctrl+L")
    assert plan3.success is True
    assert plan3.steps[0].tool == "hotkey"
    assert "ctrl+l" in plan3.steps[0].arguments["keys"]

    # 4. Browser new tab
    plan4 = resolver.resolve("abra uma nova aba")
    assert plan4.success is True
    assert plan4.steps[0].tool == "new_browser_tab"

    # 5. Scroll
    plan5 = resolver.resolve("role a tela para baixo")
    assert plan5.success is True
    assert plan5.steps[0].tool == "scroll"
    assert plan5.steps[0].arguments["amount"] == -4

    # 6. Compound calculator operation
    plan6 = resolver.resolve("abra a calculadora e faça 25 vezes 8")
    assert plan6.success is True
    assert len(plan6.steps) >= 2
    assert plan6.steps[0].tool == "open_application"
    assert plan6.steps[0].arguments["application"] == "calc"
    assert any(s.tool == "type_text" and "25*8" in s.arguments.get("text", "") for s in plan6.steps)


def test_open_application_window_verification_mock():
    """Tests that open_application initiates process and polls for window readiness."""
    with patch("subprocess.Popen") as mock_popen, \
         patch("backend.computer.windows.WindowsService.list_windows") as mock_list, \
         patch("backend.computer.windows.WindowsService.focus_window") as mock_focus:

        mock_proc = MagicMock()
        mock_proc.pid = 9999
        mock_popen.return_value = mock_proc

        mock_list.return_value = {
            "success": True,
            "windows": [
                {"hwnd": 1234, "title": "Calculadora", "process": "calc.exe"}
            ]
        }

        res = ApplicationManager.open_application("calc", wait_for_window=True, timeout=1.0)
        assert res["success"] is True
        assert res["ready"] is True
        assert res["window"] == "Calculadora"
        mock_popen.assert_called_once()
        mock_focus.assert_called_once_with("Calculadora")
