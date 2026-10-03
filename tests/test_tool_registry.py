"""
Unit tests for the declarative ToolRegistry and permission enforcement.
"""
from backend.ai.tool_registry import ToolRegistry, ToolSpec, PermissionLevel


def test_tool_registration_and_discovery():
    registry = ToolRegistry()
    assert registry.has_tool("open_application")
    assert registry.has_tool("open_folder")
    assert registry.has_tool("create_folder")
    assert registry.has_tool("search_file")
    assert registry.has_tool("delete_file")

    spec = registry.get_tool("create_folder")
    assert spec is not None
    assert "name" in spec.parameters
    assert spec.permission == PermissionLevel.CONFIRM


def test_tool_custom_registration():
    registry = ToolRegistry()

    spec = ToolSpec(
        name="custom_math_tool",
        description="Calcula o dobro de um número",
        parameters={"value": {"type": "integer", "description": "Valor numérico"}},
        required_parameters=["value"],
        permission=PermissionLevel.SAFE,
        handler=lambda value: {"success": True, "result": value * 2},
    )
    registry.register(spec)
    assert registry.has_tool("custom_math_tool")

    res = registry.execute_tool("custom_math_tool", value=21)
    assert res["success"] is True
    assert res["result"]["result"] == 42


def test_tool_permission_levels():
    registry = ToolRegistry()

    assert registry.check_permission("open_application") == "allow"
    assert registry.check_permission("open_folder") == "allow"
    assert registry.check_permission("search_file") == "allow"
    assert registry.check_permission("create_folder") in ("ask", "allow")
    assert registry.check_permission("delete_file") == "critical"
    assert registry.check_permission("shutdown_system") == "critical"


def test_openai_tool_schema_export():
    registry = ToolRegistry()
    schemas = registry.export_openai_tools()
    assert len(schemas) > 0

    names = [s["function"]["name"] for s in schemas]
    assert "open_application" in names
    assert "create_folder" in names
    assert "search_file" in names
