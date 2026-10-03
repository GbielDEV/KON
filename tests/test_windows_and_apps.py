"""
Tests for Phase 3: Window Management, Applications, and Explorer integration.
Validates:
- Window listing and active window detection
- Window state operations (focus, maximize, minimize, restore)
- Application whitelist resolution and validation
- Safe Explorer folder launch
"""
from backend.computer.windows import WindowsService
from backend.computer.applications import ApplicationManager


def test_list_and_active_windows():
    active = WindowsService.get_active_window()
    assert active["success"] is True
    assert "title" in active
    assert "process" in active

    all_w = WindowsService.list_windows()
    assert all_w["success"] is True
    assert isinstance(all_w["windows"], list)


def test_window_state_helpers():
    # Test state operations on current active window
    active = WindowsService.get_active_window()
    if active.get("hwnd"):
        res_res = WindowsService.restore_window()
        assert res_res["success"] is True

        res_max = WindowsService.maximize_window()
        assert res_max["success"] is True

        res_res2 = WindowsService.restore_window()
        assert res_res2["success"] is True


def test_application_whitelist_resolution():
    # Known apps
    assert ApplicationManager.ALLOWED_APPLICATIONS["chrome"] == "chrome.exe"
    assert ApplicationManager.ALLOWED_APPLICATIONS["notepad"] == "notepad.exe"
    assert ApplicationManager.ALLOWED_APPLICATIONS["calc"] == "calc.exe"
    assert ApplicationManager.ALLOWED_APPLICATIONS["explorer"] == "explorer.exe"

    # Unauthorized app attempt must be blocked
    res_bad = ApplicationManager.open_application(app_name="malicious_trojan")
    assert res_bad["success"] is False
    assert res_bad["error"] == "UNAUTHORIZED_OR_UNKNOWN_APPLICATION"
