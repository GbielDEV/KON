"""
Tests for Phase 5: Observe -> Act -> Observe -> Verify Loop & Failsafes.
Validates:
- Formal Observe-Act-Verify action cycle
- Action limit enforcement (failsafe at max actions)
- Window context verification preventing misclicks
- Hybrid file search (deterministic filesystem -> visual fallback)
"""
import pytest
from backend.computer.computer_use import (
    ComputerUseService,
    ComputerUseLimitExceededError,
    WindowContextMismatchError,
    COMPUTER_USE_MAX_ACTIONS,
)


def test_action_verification_cycle():
    ComputerUseService.reset_safety_counters()

    # Execute verified action (e.g. scroll)
    res = ComputerUseService.execute_action_with_verification(
        action_name="teste_scroll",
        action_callable=lambda: ComputerUseService.scroll(amount=-1),
        verify_visual_change=False,
    )
    assert res["success"] is True
    assert res["action"] == "teste_scroll"
    assert res["attempts"] >= 1


def test_failsafe_max_actions_limit():
    ComputerUseService.reset_safety_counters()

    # Simulate triggering actions until limit
    ComputerUseService._action_count = COMPUTER_USE_MAX_ACTIONS

    with pytest.raises(ComputerUseLimitExceededError):
        ComputerUseService.move_mouse(100, 100)

    # Reset cleans up
    ComputerUseService.reset_safety_counters()
    res_after_reset = ComputerUseService.move_mouse(100, 100)
    assert res_after_reset["success"] is True


def test_window_context_mismatch_blocks_execution():
    # If expected_window is something that is definitely not active, it must block
    fake_window = "JANELA_INEXISTENTE_99999_PROTECAO_KON"

    with pytest.raises(WindowContextMismatchError):
        ComputerUseService.click(100, 100, expected_window=fake_window)


def test_hybrid_search_finds_existing_file(tmp_path):
    sample = tmp_path / "trabalho_hibrido.pdf"
    sample.write_text("documento", encoding="utf-8")

    res = ComputerUseService.hybrid_find_file(str(sample))
    assert res["found"] is True
    assert res["discovery_mode"] == "deterministic_filesystem"
    assert "trabalho_hibrido.pdf" in res["name"]
