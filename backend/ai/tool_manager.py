"""
Tool Manager and Security Permission Framework for KON.
Integrates remembered permission decisions adapted from OpenJarvis approval_store.
"""
from enum import Enum
from typing import Callable, Dict, Any, Optional
from pydantic import BaseModel

from backend.core.logger import kon_logger


class PermissionLevel(str, Enum):
    """
    Security execution level required for tools.
    """
    SAFE = "SAFE"          # Can execute automatically without confirmation
    CONFIRM = "CONFIRM"    # Requires user confirmation
    CRITICAL = "CRITICAL"  # Always requires explicit double-confirmation (e.g. shutdown)


class ToolDefinition(BaseModel):
    name: str
    description: str
    permission: PermissionLevel
    parameters_schema: Dict[str, Any] = {}


class ToolManager:
    """
    Registry for assistant tools and permission verification.
    Supports remembered permission decisions (OpenJarvis approval_store pattern).
    """
    def __init__(self, memory_manager=None) -> None:
        self._tools: Dict[str, ToolDefinition] = {}
        self._handlers: Dict[str, Callable] = {}
        self._memory = memory_manager
        self._register_default_tools()

    def register_tool(
        self,
        name: str,
        description: str,
        permission: PermissionLevel,
        handler: Callable,
        schema: Optional[Dict[str, Any]] = None
    ) -> None:
        tool_def = ToolDefinition(
            name=name,
            description=description,
            permission=permission,
            parameters_schema=schema or {}
        )
        self._tools[name] = tool_def
        self._handlers[name] = handler

    def _register_default_tools(self) -> None:
        """
        Registers core tool signatures for V1 (to be fully hooked up in Phase 6).
        """
        self.register_tool(
            name="open_application",
            description="Abre um aplicativo instalado no Windows.",
            permission=PermissionLevel.SAFE,
            handler=lambda app: f"TODO: open_application({app})"
        )
        self.register_tool(
            name="open_folder",
            description="Abre uma pasta no Explorador de Arquivos.",
            permission=PermissionLevel.SAFE,
            handler=lambda folder: f"TODO: open_folder({folder})"
        )
        self.register_tool(
            name="open_url",
            description="Abre uma URL no navegador padrão.",
            permission=PermissionLevel.SAFE,
            handler=lambda url: f"TODO: open_url({url})"
        )
        self.register_tool(
            name="system_info",
            description="Obtém informações do computador.",
            permission=PermissionLevel.SAFE,
            handler=lambda: "TODO: system_info"
        )
        self.register_tool(
            name="shutdown",
            description="Desliga o computador.",
            permission=PermissionLevel.CRITICAL,
            handler=lambda: "TODO: shutdown"
        )

    def get_tool(self, name: str) -> Optional[ToolDefinition]:
        return self._tools.get(name)

    def list_tools(self) -> Dict[str, Any]:
        return {name: tool.model_dump() for name, tool in self._tools.items()}

    def check_permission(self, tool_name: str) -> str:
        """
        Evaluates whether a tool can be executed based on its permission level
        and any remembered user decisions.

        Returns:
            "allow"    — Execute immediately (SAFE or remembered approval)
            "ask"      — Requires real-time user confirmation
            "deny"     — Remembered denial or blocked
            "critical" — Always requires explicit confirmation regardless of memory
        """
        tool = self._tools.get(tool_name)
        if not tool:
            return "deny"

        if tool.permission == PermissionLevel.SAFE:
            return "allow"

        if tool.permission == PermissionLevel.CRITICAL:
            return "critical"

        # CONFIRM level — check remembered permission
        if self._memory:
            remembered = self._memory.get_remembered_permission(tool_name)
            if remembered == "always_approve":
                kon_logger.info(
                    f"[SECURITY] Permissão lembrada para '{tool_name}': aprovação automática"
                )
                return "allow"
            elif remembered == "always_deny":
                kon_logger.info(
                    f"[SECURITY] Permissão lembrada para '{tool_name}': negação automática"
                )
                return "deny"

        return "ask"

    def remember_decision(self, tool_name: str, decision: str) -> None:
        """
        Persists a user's permission decision for a tool.
        Valid decisions: 'always_approve', 'always_deny', 'ask'
        """
        if self._memory and decision in ("always_approve", "always_deny", "ask"):
            self._memory.remember_permission(tool_name, decision)

    def execute_tool(self, tool_name: str, **kwargs) -> Dict[str, Any]:
        """
        Executes a tool by name after verifying permissions.
        Returns a result dict with 'success', 'result' or 'error' keys.
        """
        tool = self._tools.get(tool_name)
        handler = self._handlers.get(tool_name)

        if not tool or not handler:
            return {"success": False, "error": f"Ferramenta '{tool_name}' não encontrada."}

        permission = self.check_permission(tool_name)
        if permission == "deny":
            return {"success": False, "error": "PERMISSION_DENIED", "tool": tool_name}
        if permission in ("ask", "critical"):
            return {
                "success": False,
                "error": "CONFIRMATION_REQUIRED",
                "tool": tool_name,
                "permission_level": tool.permission.value,
            }

        try:
            result = handler(**kwargs) if kwargs else handler()
            return {"success": True, "tool": tool_name, "result": result}
        except Exception as exc:
            kon_logger.error(f"[TOOL] Erro ao executar '{tool_name}': {exc}")
            return {"success": False, "tool": tool_name, "error": str(exc)}
