"""
Unit tests for LoopGuard adapted from OpenJarvis.
"""
from backend.ai.loop_guard import LoopGuard, LoopGuardConfig


def test_loop_guard_identical_calls():
    config = LoopGuardConfig(max_identical_calls=3)
    guard = LoopGuard(config=config)

    # 1st call: OK
    v1 = guard.check_call("open_folder", {"folder": "Downloads"})
    assert not v1.blocked

    # 2nd call: OK
    v2 = guard.check_call("open_folder", {"folder": "Downloads"})
    assert not v2.blocked

    # 3rd call: OK
    v3 = guard.check_call("open_folder", {"folder": "Downloads"})
    assert not v3.blocked

    # 4th call: BLOCKED (exceeded max_identical_calls=3)
    v4 = guard.check_call("open_folder", {"folder": "Downloads"})
    assert v4.blocked
    assert "repetida" in v4.reason


def test_loop_guard_ping_pong_detection():
    config = LoopGuardConfig(ping_pong_window=4)
    guard = LoopGuard(config=config)

    # Simulate A-B-A-B pattern
    guard.check_call("tool_A", "1")
    guard.check_call("tool_B", "2")
    guard.check_call("tool_A", "3")
    v = guard.check_call("tool_B", "4")

    assert v.blocked
    assert "ping-pong" in v.reason


def test_loop_guard_reset():
    config = LoopGuardConfig(max_identical_calls=2)
    guard = LoopGuard(config=config)

    guard.check_call("tool_X", {})
    guard.check_call("tool_X", {})
    v = guard.check_call("tool_X", {})
    assert v.blocked

    guard.reset()
    v_fresh = guard.check_call("tool_X", {})
    assert not v_fresh.blocked
