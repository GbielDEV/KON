"""
Tests for Phase 2: Mouse, Keyboard, and Screen modules.
Validates:
- Mouse bounds clamping and event firing (move, click, double click, right click, scroll)
- Native keyboard typing with Portuguese accents (ç, ã, é, ó), special keys, and hotkeys
- Screen resolution metrics and screenshot generation with metadata
"""
from pathlib import Path
from backend.computer.mouse import MouseController
from backend.computer.keyboard import KeyboardController
from backend.computer.screen import ScreenService


def test_screen_service_info_and_hash():
    info = ScreenService.get_screen_info()
    assert info["success"] is True
    assert info["width"] > 0
    assert info["height"] > 0

    s_hash = ScreenService.get_screen_hash()
    assert isinstance(s_hash, str)
    assert len(s_hash) == 32  # md5 hex length


def test_mouse_controller_metrics_and_clamping():
    pos = MouseController.get_mouse_position()
    assert pos["success"] is True
    assert "x" in pos and "y" in pos

    # Move mouse inside valid bounds
    res_move = MouseController.move_mouse(150, 150)
    assert res_move["success"] is True
    assert res_move["x"] == 150
    assert res_move["y"] == 150

    # Move mouse with values exceeding bounds -> should be clamped, not crash
    screen_w, screen_h = MouseController.get_screen_bounds()
    res_clamped = MouseController.move_mouse(screen_w + 1000, screen_h + 1000)
    assert res_clamped["success"] is True
    assert res_clamped["x"] <= screen_w - 1
    assert res_clamped["y"] <= screen_h - 1


def test_mouse_clicks_and_scroll():
    # Left click
    c_res = MouseController.click(150, 150, button="left")
    assert c_res["success"] is True
    assert c_res["button"] == "left"

    # Right click
    rc_res = MouseController.right_click(150, 150)
    assert rc_res["success"] is True
    assert rc_res["button"] == "right"

    # Double click
    dc_res = MouseController.double_click(150, 150)
    assert dc_res["success"] is True

    # Mouse down / up
    assert MouseController.mouse_down(button="left")["success"] is True
    assert MouseController.mouse_up(button="left")["success"] is True

    # Scroll
    s_res = MouseController.scroll(amount=-2)
    assert s_res["success"] is True
    assert s_res["amount"] == -2


def test_keyboard_typing_and_portuguese_accents():
    text_sample = "KON testando acentuação: ação, café, avô, água, maçã."
    res = KeyboardController.type_text(text_sample)
    assert res["success"] is True
    assert res["typed_length"] == len(text_sample)

    # Special key press
    key_res = KeyboardController.press_key("escape")
    assert key_res["success"] is True
    assert key_res["key"] == "escape"

    # Hotkey execution
    hk_res = KeyboardController.hotkey(["shift", "tab"])
    assert hk_res["success"] is True
    assert hk_res["combination"] == ["shift", "tab"]


def test_take_screenshot_creates_valid_file(tmp_path):
    target = tmp_path / "test_screen.png"
    res = ScreenService.take_screenshot(output_path=str(target))
    assert res["success"] is True
    assert Path(res["path"]).exists()
    assert res["size_bytes"] > 0
    assert res["width"] > 0
    assert res["height"] > 0
