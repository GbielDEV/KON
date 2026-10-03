"""
Unit tests for MemoryManager permission memory and ToolManager permission enforcement.
"""
from backend.memory.memory import MemoryManager
from backend.ai.tool_manager import ToolManager, PermissionLevel


def test_permission_memory_store_and_check(tmp_path):
    db_file = tmp_path / "test_kon.db"
    mem = MemoryManager(db_path=db_file)

    # Initially no permission
    assert mem.get_remembered_permission("open_app") is None

    # Store approval
    mem.remember_permission("open_app", decision="always_approve")

    # Check again
    assert mem.get_remembered_permission("open_app") == "always_approve"

    # Different tool shouldn't match
    assert mem.get_remembered_permission("other_tool") is None

    # Clear
    mem.clear_permission("open_app")
    assert mem.get_remembered_permission("open_app") is None


def test_tool_manager_permission_levels(tmp_path):
    db_file = tmp_path / "test_kon.db"
    mem = MemoryManager(db_path=db_file)
    tm = ToolManager(memory_manager=mem)

    # Register test tools
    executed = []
    tm.register_tool(
        name="safe_action",
        description="Safe tool",
        permission=PermissionLevel.SAFE,
        handler=lambda: executed.append("safe")
    )
    tm.register_tool(
        name="confirm_action",
        description="Confirm tool",
        permission=PermissionLevel.CONFIRM,
        handler=lambda param="": executed.append(f"confirm_{param}")
    )
    tm.register_tool(
        name="critical_action",
        description="Critical tool",
        permission=PermissionLevel.CRITICAL,
        handler=lambda: executed.append("critical")
    )

    # SAFE tool check_permission -> allow
    assert tm.check_permission("safe_action") == "allow"
    res = tm.execute_tool("safe_action")
    assert res["success"] is True
    assert "safe" in executed

    # CONFIRM tool without remembered approval -> ask
    assert tm.check_permission("confirm_action") == "ask"
    res = tm.execute_tool("confirm_action", param="123")
    assert res["success"] is False
    assert res["error"] == "CONFIRMATION_REQUIRED"

    # Remember permission via ToolManager
    tm.remember_decision("confirm_action", "always_approve")

    # Now check should return allow and execute successfully
    assert tm.check_permission("confirm_action") == "allow"
    res = tm.execute_tool("confirm_action", param="123")
    assert res["success"] is True
    assert "confirm_123" in executed

    # CRITICAL tool always returns critical regardless of memory
    tm.remember_decision("critical_action", "always_approve")
    assert tm.check_permission("critical_action") == "critical"
