"""
Command Registry Pattern for KON Assistant.
Validates permissions via ToolManager and strictly avoids eval/exec or arbitrary shell commands.
"""
from typing import Callable, Dict, Any, Optional
import functools
from backend.core.logger import kon_logger
from backend.ai.tool_manager import ToolManager, PermissionLevel


class CommandRegistry:
    """
    Central registry for intent-mapped commands.
    Ensures only pre-registered, validated functions can be dispatched.
    """

    def __init__(self, tool_manager: Optional[ToolManager] = None) -> None:
        self._handlers: Dict[str, Callable] = {}
        self._permissions: Dict[str, PermissionLevel] = {}
        self.tool_manager = tool_manager or ToolManager()

    def register(
        self,
        intent_name: str,
        handler: Callable,
        permission: PermissionLevel = PermissionLevel.SAFE,
        description: str = "",
    ) -> None:
        """
        Registers a command handler for a given intent name.
        """
        if not callable(handler):
            raise ValueError(f"Handler para '{intent_name}' deve ser chamável.")

        self._handlers[intent_name] = handler
        self._permissions[intent_name] = permission

        # Sync registration with ToolManager
        self.tool_manager.register_tool(
            name=intent_name,
            description=description or f"Comando para intent {intent_name}",
            permission=permission,
            handler=handler,
        )
        kon_logger.debug(f"[COMMAND] Comando '{intent_name}' registrado (Permissão: {permission.value}).")

    def has_command(self, intent_name: str) -> bool:
        return intent_name in self._handlers

    def dispatch(self, intent: str, slots: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Safely executes a registered command.
        No eval, no exec, and no arbitrary shell construction.
        """
        if not intent or intent not in self._handlers:
            kon_logger.warning(f"[COMMAND] Comando '{intent}' não encontrado no registro.")
            return {
                "success": False,
                "intent": intent,
                "error": "COMMAND_NOT_FOUND",
                "response_text": "Desculpe, não possuo comando registrado para essa solicitação.",
            }

        handler = self._handlers[intent]
        permission = self._permissions.get(intent, PermissionLevel.SAFE)

        # Check ToolManager permission
        tool_def = self.tool_manager.get_tool(intent)
        perm = tool_def.permission if tool_def else permission
        if perm == PermissionLevel.CRITICAL:
            kon_logger.warning(f"[COMMAND] Comando '{intent}' requer confirmação crítica.")
            return {
                "success": False,
                "intent": intent,
                "needs_confirmation": True,
                "response_text": f"O comando {intent} requer confirmação de segurança.",
            }

        kon_logger.info(f"[COMMAND] Executando {intent}")
        slots_args = slots or {}

        try:
            # Execute handler with kwargs or without arguments if none expected
            import inspect
            sig = inspect.signature(handler)
            if len(sig.parameters) == 0:
                result = handler()
            else:
                result = handler(**slots_args)

            # Standardize response structure
            if isinstance(result, dict) and "response_text" in result:
                return {
                    "success": result.get("success", True),
                    "intent": intent,
                    "response_text": result["response_text"],
                    "data": result,
                }
            elif isinstance(result, str):
                return {
                    "success": True,
                    "intent": intent,
                    "response_text": result,
                    "data": {"message": result},
                }
            else:
                return {
                    "success": True,
                    "intent": intent,
                    "response_text": "Comando executado com sucesso.",
                    "data": result,
                }

        except Exception as exc:
            kon_logger.error(f"[COMMAND] Erro ao executar comando '{intent}': {exc}")
            return {
                "success": False,
                "intent": intent,
                "error": str(exc),
                "response_text": "Ocorreu um erro durante a execução do comando.",
            }


# Default singleton registry
_GLOBAL_REGISTRY = CommandRegistry()


def get_registry() -> CommandRegistry:
    return _GLOBAL_REGISTRY


def command(intent_name: str, permission: PermissionLevel = PermissionLevel.SAFE, description: str = ""):
    """
    Decorator for registering intent handlers.
    Example:
        @command("informar_horario")
        def informar_horario():
            return "Agora são 15 horas."
    """
    def decorator(func: Callable):
        _GLOBAL_REGISTRY.register(intent_name, func, permission=permission, description=description)
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            return func(*args, **kwargs)
        return wrapper
    return decorator
