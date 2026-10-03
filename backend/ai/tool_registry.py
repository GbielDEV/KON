"""
Declarative Tool Registry for the KON Assistant.
Allows dynamic tool discovery, strict parameter typing, OpenAI-compatible schemas,
and permission enforcement (SAFE, CONFIRM, CRITICAL) without hardcoding intents.
Adapted from OpenJarvis core registry (Apache-2.0).
"""
from __future__ import annotations

from enum import Enum
from dataclasses import dataclass, field
from typing import Callable, Dict, Any, List, Optional
import inspect

from backend.core.logger import kon_logger


class PermissionLevel(str, Enum):
    SAFE = "SAFE"          # Can execute automatically without confirmation
    CONFIRM = "CONFIRM"    # Requires user confirmation or remembered approval
    CRITICAL = "CRITICAL"  # Always requires explicit confirmation (e.g. shutdown, delete)


@dataclass
class ToolSpec:
    """Declarative specification for a registered assistant tool."""
    name: str
    description: str
    parameters: Dict[str, Any] = field(default_factory=dict)
    required_parameters: List[str] = field(default_factory=list)
    permission: PermissionLevel = PermissionLevel.SAFE
    handler: Optional[Callable[..., Any]] = None
    timeout_seconds: float = 30.0
    category: str = "general"

    def to_openai_tool(self) -> Dict[str, Any]:
        """Exports tool definition to standard OpenAI Function Calling schema."""
        properties: Dict[str, Any] = {}
        for param_name, param_meta in self.parameters.items():
            if isinstance(param_meta, dict):
                properties[param_name] = {
                    "type": param_meta.get("type", "string"),
                    "description": param_meta.get("description", ""),
                }
                if "enum" in param_meta:
                    properties[param_name]["enum"] = param_meta["enum"]
            else:
                properties[param_name] = {
                    "type": str(param_meta),
                    "description": f"Parâmetro {param_name}",
                }

        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": self.required_parameters,
                },
            },
        }


class ToolRegistry:
    """
    Central registry for discovering, inspecting, and executing assistant tools.
    Supports runtime extension: new tools can be added without modifying the brain.
    """

    def __init__(self, memory_manager=None) -> None:
        self._tools: Dict[str, ToolSpec] = {}
        self._memory = memory_manager
        self._register_default_tools()

    def register(self, spec: ToolSpec) -> ToolSpec:
        """Registers a new tool specification."""
        if not spec.name:
            raise ValueError("O nome da ferramenta não pode ser vazio.")
        if not callable(spec.handler):
            raise ValueError(f"A ferramenta '{spec.name}' precisa de uma função executora (handler).")

        self._tools[spec.name] = spec
        kon_logger.debug(f"[TOOL_REGISTRY] Ferramenta registrada: '{spec.name}' ({spec.permission.value})")
        return spec

    def get_tool(self, name: str) -> Optional[ToolSpec]:
        return self._tools.get(name)

    def has_tool(self, name: str) -> bool:
        return name in self._tools

    def list_tools(self) -> Dict[str, ToolSpec]:
        return dict(self._tools)

    def export_openai_tools(self) -> List[Dict[str, Any]]:
        """Returns the complete list of tools in OpenAI function calling schema format."""
        return [tool.to_openai_tool() for tool in self._tools.values()]

    def check_permission(self, tool_name: str, **kwargs: Any) -> str:
        """
        Evaluates whether a tool can be executed based on its permission level
        and remembered user approval in SQLite.
        Returns: 'allow', 'ask', 'deny', 'critical'
        """
        tool = self._tools.get(tool_name)
        if not tool:
            return "deny"

        if tool.permission == PermissionLevel.SAFE:
            return "allow"

        if tool.permission == PermissionLevel.CRITICAL:
            return "critical"

        # CONFIRM level: check remembered decisions
        if self._memory:
            target_path = (
                kwargs.get("path")
                or kwargs.get("folder")
                or kwargs.get("source")
                or kwargs.get("destination")
                or kwargs.get("root")
            )
            remembered = self._memory.get_remembered_permission(tool_name, target_path=target_path)
            if remembered == "always_approve":
                kon_logger.info(f"[SECURITY] Permissão lembrada para '{tool_name}': aprovação automática")
                return "allow"
            elif remembered == "always_deny":
                kon_logger.info(f"[SECURITY] Permissão lembrada para '{tool_name}': negação automática")
                return "deny"

        return "ask"

    def execute_tool(
        self,
        tool_name: str,
        authorization_token: Optional[str] = None,
        **kwargs: Any
    ) -> Dict[str, Any]:
        """
        Executes a registered tool by name after validating permissions and arguments.
        Supports authorization_token issued by ConfirmationManager to authorize CONFIRM/CRITICAL operations.
        """
        tool = self._tools.get(tool_name)
        if not tool or not tool.handler:
            return {
                "success": False,
                "tool": tool_name,
                "error": "TOOL_NOT_FOUND",
                "message": f"Ferramenta '{tool_name}' não encontrada no registro.",
            }

        # Check if authorization_token was passed in kwargs
        auth_token = authorization_token or kwargs.pop("authorization_token", None)

        perm = self.check_permission(tool_name)
        if perm == "deny":
            return {
                "success": False,
                "tool": tool_name,
                "error": "PERMISSION_DENIED",
                "message": f"Execução de '{tool_name}' bloqueada pela política de segurança.",
            }

        # If confirmation is required, verify if a valid authorization token was issued by Security Layer
        if perm in ("ask", "critical"):
            from backend.security.confirmation_manager import get_confirmation_manager
            cm = get_confirmation_manager()
            is_authorized = cm.validate_authorization_token(tool_name, auth_token, arguments=kwargs)
            if not is_authorized:
                return {
                    "success": False,
                    "tool": tool_name,
                    "error": "CONFIRMATION_REQUIRED",
                    "permission_level": tool.permission.value,
                    "message": f"A ferramenta '{tool_name}' requer autorização explícita do usuário.",
                }

        try:
            # Match parameters using inspect signature with alias resolution
            sig = inspect.signature(tool.handler)
            has_var_keyword = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values())

            if has_var_keyword:
                bound_kwargs = dict(kwargs)
            else:
                bound_kwargs = {}
                for param_name in sig.parameters:
                    if param_name in kwargs:
                        bound_kwargs[param_name] = kwargs[param_name]
                    # Common parameter aliases
                    elif param_name in ("app_name", "app") and "application" in kwargs:
                        bound_kwargs[param_name] = kwargs["application"]
                    elif param_name == "application" and "app_name" in kwargs:
                        bound_kwargs[param_name] = kwargs["app_name"]
                    elif param_name in ("folder_identifier", "path") and "folder" in kwargs:
                        bound_kwargs[param_name] = kwargs["folder"]
                    elif param_name == "folder" and "folder_identifier" in kwargs:
                        bound_kwargs[param_name] = kwargs["folder_identifier"]

            kon_logger.info(f"[EXEC] Executando ferramenta '{tool_name}' com argumentos: {bound_kwargs}")
            raw_result = tool.handler(**bound_kwargs)

            if isinstance(raw_result, dict):
                return {
                    "success": raw_result.get("success", True),
                    "tool": tool_name,
                    "result": raw_result,
                    "response_text": raw_result.get("message") or raw_result.get("response_text"),
                }
            elif isinstance(raw_result, str):
                return {
                    "success": True,
                    "tool": tool_name,
                    "result": raw_result,
                    "response_text": raw_result,
                }
            else:
                return {
                    "success": True,
                    "tool": tool_name,
                    "result": raw_result,
                    "response_text": "Operação realizada com sucesso.",
                }

        except Exception as exc:
            kon_logger.error(f"[EXEC] Erro ao executar '{tool_name}': {exc}")
            return {
                "success": False,
                "tool": tool_name,
                "error": str(exc),
                "message": f"Erro durante a execução de {tool_name}: {exc}",
            }

    def _register_default_tools(self) -> None:
        """Registers the comprehensive suite of Windows, Files, System, Computer Use, and Browser tools."""
        from backend.computer.applications import ApplicationManager
        from backend.computer.files import FileManager
        from backend.computer.system import SystemTelemetry
        from backend.computer.computer_use import ComputerUseService
        from backend.browser.browser import BrowserService

        # -------------------------------------------------------------
        # 1. System Tools
        # -------------------------------------------------------------
        self.register(ToolSpec(
            name="get_system_info",
            description="Retorna informações de telemetria do sistema (uso de CPU, uso de memória RAM, uptime).",
            parameters={
                "metric": {"type": "string", "description": "Métrica específica: 'cpu', 'memory', 'ram', 'uptime' ou 'all'"}
            },
            required_parameters=[],
            permission=PermissionLevel.SAFE,
            handler=lambda metric=None: FileManager.format_system_info(metric),
            category="system"
        ))

        # Alias system_info -> get_system_info
        self.register(ToolSpec(
            name="system_info",
            description="Retorna informações de telemetria do sistema (uso de CPU, memória RAM, uptime).",
            parameters={
                "metric": {"type": "string", "description": "Métrica: 'cpu', 'memory', 'ram', 'uptime' ou 'all'"}
            },
            required_parameters=[],
            permission=PermissionLevel.SAFE,
            handler=lambda metric=None: FileManager.format_system_info(metric),
            category="system"
        ))

        self.register(ToolSpec(
            name="get_disk_info",
            description="Retorna o espaço livre e total das unidades de disco rígido e armazenamento.",
            parameters={},
            required_parameters=[],
            permission=PermissionLevel.SAFE,
            handler=SystemTelemetry.get_disk_info,
            category="system"
        ))

        self.register(ToolSpec(
            name="get_processes",
            description="Lista os processos em execução no Windows, ordenados por consumo ou filtrados por nome.",
            parameters={
                "search": {"type": "string", "description": "Nome ou trecho do processo a filtrar (opcional)"},
                "limit": {"type": "integer", "description": "Número máximo de processos a retornar (padrão: 10)"}
            },
            required_parameters=[],
            permission=PermissionLevel.SAFE,
            handler=SystemTelemetry.get_processes,
            category="system"
        ))

        self.register(ToolSpec(
            name="get_datetime",
            description="Retorna a data atual, hora exata, dia da semana e fuso horário.",
            parameters={},
            required_parameters=[],
            permission=PermissionLevel.SAFE,
            handler=SystemTelemetry.get_datetime,
            category="system"
        ))

        self.register(ToolSpec(
            name="shutdown_system",
            description="Desliga o computador de forma controlada.",
            parameters={},
            required_parameters=[],
            permission=PermissionLevel.CRITICAL,
            handler=lambda: {"success": True, "message": "Comando de desligamento executado após confirmação."},
            category="system"
        ))

        self.register(ToolSpec(
            name="restart_system",
            description="Reinicia o computador de forma controlada.",
            parameters={},
            required_parameters=[],
            permission=PermissionLevel.CRITICAL,
            handler=lambda: {"success": True, "message": "Comando de reinicialização executado após confirmação."},
            category="system"
        ))

        # -------------------------------------------------------------
        # 2. Application Tools
        # -------------------------------------------------------------
        self.register(ToolSpec(
            name="open_application",
            description="Abre um aplicativo instalado no Windows (ex: Chrome, Bloco de Notas, Calculadora, VS Code).",
            parameters={
                "application": {"type": "string", "description": "Nome ou identificador do aplicativo (ex: 'chrome', 'notepad', 'calc', 'code')"}
            },
            required_parameters=["application"],
            permission=PermissionLevel.SAFE,
            handler=ApplicationManager.open_application,
            category="computer"
        ))

        self.register(ToolSpec(
            name="launch_application",
            description="Inicia ou abre um aplicativo instalado no Windows.",
            parameters={
                "application": {"type": "string", "description": "Nome ou identificador do aplicativo (ex: 'chrome', 'notepad', 'calc', 'code')"}
            },
            required_parameters=["application"],
            permission=PermissionLevel.SAFE,
            handler=ApplicationManager.open_application,
            category="computer"
        ))

        self.register(ToolSpec(
            name="close_application",
            description="Fecha processos de um aplicativo em execução no Windows.",
            parameters={
                "application": {"type": "string", "description": "Nome do aplicativo a fechar (ex: 'chrome', 'notepad', 'calc')"}
            },
            required_parameters=["application"],
            permission=PermissionLevel.CONFIRM,
            handler=ApplicationManager.close_application,
            category="computer"
        ))

        self.register(ToolSpec(
            name="list_installed_applications",
            description="Descobre e lista os aplicativos e programas instalados no Windows.",
            parameters={
                "query": {"type": "string", "description": "Filtro por nome do aplicativo (opcional)"}
            },
            required_parameters=[],
            permission=PermissionLevel.SAFE,
            handler=ApplicationManager.list_installed_applications,
            category="computer"
        ))

        self.register(ToolSpec(
            name="switch_window",
            description="Alterna o foco para a janela de um aplicativo específico no Windows.",
            parameters={
                "target": {"type": "string", "description": "Nome do aplicativo ou título da janela para alternar"}
            },
            required_parameters=["target"],
            permission=PermissionLevel.SAFE,
            handler=ApplicationManager.switch_window,
            category="computer"
        ))

        # -------------------------------------------------------------
        # 3. File & Directory Tools
        # -------------------------------------------------------------
        self.register(ToolSpec(
            name="search_file",
            description="Pesquisa arquivos no computador por nome, extensão ou pasta.",
            parameters={
                "query": {"type": "string", "description": "Texto ou termo a buscar no nome do arquivo"},
                "root": {"type": "string", "description": "Pasta raiz da pesquisa (padrão: Downloads ou Documentos)"},
                "extension": {"type": "string", "description": "Extensão do arquivo (ex: 'pdf', 'txt', 'png')"}
            },
            required_parameters=["query"],
            permission=PermissionLevel.SAFE,
            handler=FileManager.search_file,
            category="filesystem"
        ))

        self.register(ToolSpec(
            name="list_directory",
            description="Lista os arquivos e subpastas existentes em um diretório ou pasta especial (ex: Downloads, Documentos).",
            parameters={
                "path": {"type": "string", "description": "Caminho ou nome da pasta a listar (ex: 'Downloads', 'Documentos', 'Desktop')"}
            },
            required_parameters=[],
            permission=PermissionLevel.SAFE,
            handler=FileManager.list_directory,
            category="filesystem"
        ))

        self.register(ToolSpec(
            name="open_file",
            description="Abre um arquivo no programa padrão do Windows.",
            parameters={
                "path": {"type": "string", "description": "Caminho completo ou nome do arquivo"}
            },
            required_parameters=["path"],
            permission=PermissionLevel.SAFE,
            handler=FileManager.open_file,
            category="filesystem"
        ))

        self.register(ToolSpec(
            name="open_folder",
            description="Abre uma pasta no Explorador de Arquivos do Windows (ex: Downloads, Documentos, Desktop).",
            parameters={
                "folder": {"type": "string", "description": "Nome da pasta ou caminho"}
            },
            required_parameters=["folder"],
            permission=PermissionLevel.SAFE,
            handler=FileManager.open_folder,
            category="filesystem"
        ))

        self.register(ToolSpec(
            name="create_file",
            description="Cria um novo arquivo de texto no sistema com conteúdo opcional.",
            parameters={
                "path": {"type": "string", "description": "Caminho e nome do arquivo a ser criado"},
                "content": {"type": "string", "description": "Conteúdo textual inicial (opcional)"}
            },
            required_parameters=["path"],
            permission=PermissionLevel.CONFIRM,
            handler=FileManager.create_file,
            category="filesystem"
        ))

        self.register(ToolSpec(
            name="create_folder",
            description="Cria uma nova pasta no sistema de arquivos.",
            parameters={
                "name": {"type": "string", "description": "Nome da nova pasta a ser criada"},
                "parent": {"type": "string", "description": "Pasta de destino (ex: 'Downloads', 'Documentos')"}
            },
            required_parameters=["name"],
            permission=PermissionLevel.CONFIRM,
            handler=FileManager.create_folder,
            category="filesystem"
        ))

        self.register(ToolSpec(
            name="copy_file",
            description="Copia um arquivo de um local para outro.",
            parameters={
                "source": {"type": "string", "description": "Caminho do arquivo de origem"},
                "destination": {"type": "string", "description": "Pasta ou caminho de destino"}
            },
            required_parameters=["source", "destination"],
            permission=PermissionLevel.CONFIRM,
            handler=FileManager.copy_file,
            category="filesystem"
        ))

        self.register(ToolSpec(
            name="move_file",
            description="Move um arquivo de um local para outro.",
            parameters={
                "source": {"type": "string", "description": "Caminho do arquivo de origem"},
                "destination": {"type": "string", "description": "Pasta ou caminho de destino"}
            },
            required_parameters=["source", "destination"],
            permission=PermissionLevel.CONFIRM,
            handler=FileManager.move_file,
            category="filesystem"
        ))

        self.register(ToolSpec(
            name="rename_file",
            description="Renomeia um arquivo ou pasta.",
            parameters={
                "path": {"type": "string", "description": "Caminho atual do arquivo"},
                "new_name": {"type": "string", "description": "Novo nome do arquivo"}
            },
            required_parameters=["path", "new_name"],
            permission=PermissionLevel.CONFIRM,
            handler=FileManager.rename_file,
            category="filesystem"
        ))

        self.register(ToolSpec(
            name="delete_file",
            description="Exclui um arquivo ou pasta do computador de forma segura com autorização prévia.",
            parameters={
                "path": {"type": "string", "description": "Caminho do arquivo ou pasta a ser excluído"}
            },
            required_parameters=["path"],
            permission=PermissionLevel.CRITICAL,
            handler=FileManager.delete_file,
            category="filesystem"
        ))

        self.register(ToolSpec(
            name="check_file_exists",
            description="Verifica de forma imediata e determinística se um caminho de arquivo ou pasta existe no sistema (Path.exists()).",
            parameters={
                "path": {"type": "string", "description": "Caminho completo ou relativo a verificar"}
            },
            required_parameters=["path"],
            permission=PermissionLevel.SAFE,
            handler=FileManager.check_file_exists,
            category="filesystem"
        ))

        self.register(ToolSpec(
            name="search_folder",
            description="Pesquisa pastas no computador por nome ou pasta raiz.",
            parameters={
                "query": {"type": "string", "description": "Nome ou termo a buscar na pasta"},
                "root": {"type": "string", "description": "Pasta raiz da pesquisa (opcional)"}
            },
            required_parameters=["query"],
            permission=PermissionLevel.SAFE,
            handler=FileManager.search_folder,
            category="filesystem"
        ))

        self.register(ToolSpec(
            name="check_path",
            description="Verifica de forma imediata se um caminho de arquivo ou pasta existe no sistema.",
            parameters={
                "path": {"type": "string", "description": "Caminho a verificar"}
            },
            required_parameters=["path"],
            permission=PermissionLevel.SAFE,
            handler=FileManager.check_path,
            category="filesystem"
        ))

        self.register(ToolSpec(
            name="get_file_info",
            description="Obtém informações estruturadas e metadados de um arquivo.",
            parameters={
                "path": {"type": "string", "description": "Caminho do arquivo"}
            },
            required_parameters=["path"],
            permission=PermissionLevel.SAFE,
            handler=FileManager.get_file_info,
            category="filesystem"
        ))

        self.register(ToolSpec(
            name="get_folder_info",
            description="Obtém informações estruturadas e metadados de uma pasta.",
            parameters={
                "path": {"type": "string", "description": "Caminho da pasta"}
            },
            required_parameters=["path"],
            permission=PermissionLevel.SAFE,
            handler=FileManager.get_folder_info,
            category="filesystem"
        ))

        self.register(ToolSpec(
            name="hybrid_find_file",
            description="Busca híbrida de arquivos: tenta primeiro o filesystem determinístico e, se não encontrar, utiliza o Explorador de Arquivos visualmente.",
            parameters={
                "filename": {"type": "string", "description": "Nome ou trecho do arquivo a localizar"},
                "fallback_to_explorer": {"type": "boolean", "description": "Se verdadeiro, abre o Explorer caso não encontre no filesystem (padrão: true)"}
            },
            required_parameters=["filename"],
            permission=PermissionLevel.SAFE,
            handler=ComputerUseService.hybrid_find_file,
            category="filesystem"
        ))

        # -------------------------------------------------------------
        # 4. Computer Use & Windows GUI Tools
        # -------------------------------------------------------------
        self.register(ToolSpec(
            name="get_screen_info",
            description="Obtém informações e resolução da tela e monitores do computador.",
            parameters={},
            required_parameters=[],
            permission=PermissionLevel.SAFE,
            handler=ComputerUseService.get_screen_info,
            category="computer_use"
        ))

        self.register(ToolSpec(
            name="get_active_window",
            description="Identifica qual janela e aplicativo estão ativos em primeiro plano na tela.",
            parameters={},
            required_parameters=[],
            permission=PermissionLevel.SAFE,
            handler=ComputerUseService.get_active_window,
            category="computer_use"
        ))

        self.register(ToolSpec(
            name="list_windows",
            description="Lista as janelas visíveis abertas no Windows com seus títulos e processos.",
            parameters={
                "query": {"type": "string", "description": "Filtro opcional por título ou processo"}
            },
            required_parameters=[],
            permission=PermissionLevel.SAFE,
            handler=ComputerUseService.list_windows,
            category="computer_use"
        ))

        self.register(ToolSpec(
            name="focus_window",
            description="Coloca uma janela específica em primeiro plano pelo título ou nome do processo.",
            parameters={
                "title_or_process": {"type": "string", "description": "Nome da janela ou do aplicativo para focar"}
            },
            required_parameters=["title_or_process"],
            permission=PermissionLevel.SAFE,
            handler=ComputerUseService.focus_window,
            category="computer_use"
        ))

        self.register(ToolSpec(
            name="maximize_window",
            description="Maximiza uma janela específica ou a janela atualmente ativa.",
            parameters={
                "title_or_process": {"type": "string", "description": "Título ou processo da janela a maximizar (opcional)"}
            },
            required_parameters=[],
            permission=PermissionLevel.SAFE,
            handler=ComputerUseService.maximize_window,
            category="computer_use"
        ))

        self.register(ToolSpec(
            name="minimize_window",
            description="Minimiza uma janela específica ou a janela atualmente ativa.",
            parameters={
                "title_or_process": {"type": "string", "description": "Título ou processo da janela a minimizar (opcional)"}
            },
            required_parameters=[],
            permission=PermissionLevel.SAFE,
            handler=ComputerUseService.minimize_window,
            category="computer_use"
        ))

        self.register(ToolSpec(
            name="restore_window",
            description="Restaura uma janela minimizada ou maximizada para o tamanho normal.",
            parameters={
                "title_or_process": {"type": "string", "description": "Título ou processo da janela a restaurar (opcional)"}
            },
            required_parameters=[],
            permission=PermissionLevel.SAFE,
            handler=ComputerUseService.restore_window,
            category="computer_use"
        ))

        self.register(ToolSpec(
            name="close_window",
            description="Fecha uma janela específica ou a janela ativa de forma controlada.",
            parameters={
                "title_or_process": {"type": "string", "description": "Título ou processo da janela a fechar (opcional)"}
            },
            required_parameters=[],
            permission=PermissionLevel.CONFIRM,
            handler=ComputerUseService.close_window,
            category="computer_use"
        ))

        self.register(ToolSpec(
            name="move_mouse",
            description="Move o cursor do mouse para coordenadas específicas (x, y) na tela.",
            parameters={
                "x": {"type": "integer", "description": "Posição horizontal em pixels"},
                "y": {"type": "integer", "description": "Posição vertical em pixels"}
            },
            required_parameters=["x", "y"],
            permission=PermissionLevel.SAFE,
            handler=ComputerUseService.move_mouse,
            category="computer_use"
        ))

        self.register(ToolSpec(
            name="click",
            description="Clica com o mouse nas coordenadas especificadas (ou na posição atual). Suporta verificação de janela esperada.",
            parameters={
                "x": {"type": "integer", "description": "Posição horizontal (opcional)"},
                "y": {"type": "integer", "description": "Posição vertical (opcional)"},
                "button": {"type": "string", "description": "'left', 'right' ou 'middle' (padrão: left)"},
                "expected_window": {"type": "string", "description": "Título esperado da janela ativa para proteção contra foco errado (opcional)"}
            },
            required_parameters=[],
            permission=PermissionLevel.SAFE,
            handler=ComputerUseService.click,
            category="computer_use"
        ))

        self.register(ToolSpec(
            name="double_click",
            description="Executa um clique duplo com o botão esquerdo do mouse.",
            parameters={
                "x": {"type": "integer", "description": "Posição horizontal (opcional)"},
                "y": {"type": "integer", "description": "Posição vertical (opcional)"},
                "expected_window": {"type": "string", "description": "Janela esperada para segurança (opcional)"}
            },
            required_parameters=[],
            permission=PermissionLevel.SAFE,
            handler=ComputerUseService.double_click,
            category="computer_use"
        ))

        self.register(ToolSpec(
            name="right_click",
            description="Executa um clique com o botão direito do mouse para abrir menus de contexto.",
            parameters={
                "x": {"type": "integer", "description": "Posição horizontal (opcional)"},
                "y": {"type": "integer", "description": "Posição vertical (opcional)"},
                "expected_window": {"type": "string", "description": "Janela esperada para segurança (opcional)"}
            },
            required_parameters=[],
            permission=PermissionLevel.SAFE,
            handler=ComputerUseService.right_click,
            category="computer_use"
        ))

        self.register(ToolSpec(
            name="drag",
            description="Arrasta o mouse pressionado de um ponto inicial (start_x, start_y) até um destino (end_x, end_y).",
            parameters={
                "start_x": {"type": "integer", "description": "Posição X inicial"},
                "start_y": {"type": "integer", "description": "Posição Y inicial"},
                "end_x": {"type": "integer", "description": "Posição X final"},
                "end_y": {"type": "integer", "description": "Posição Y final"},
                "expected_window": {"type": "string", "description": "Janela esperada para segurança (opcional)"},
            },
            required_parameters=["start_x", "start_y", "end_x", "end_y"],
            permission=PermissionLevel.SAFE,
            handler=ComputerUseService.drag,
            category="computer_use"
        ))

        self.register(ToolSpec(
            name="mouse_down",
            description="Pressiona e mantém pressionado um botão do mouse (ex: 'left' ou 'right').",
            parameters={
                "button": {"type": "string", "description": "Botão do mouse: 'left' ou 'right' (padrão: left)"}
            },
            required_parameters=[],
            permission=PermissionLevel.SAFE,
            handler=ComputerUseService.mouse_down,
            category="computer_use"
        ))

        self.register(ToolSpec(
            name="mouse_up",
            description="Solta um botão pressionado do mouse (ex: 'left' ou 'right').",
            parameters={
                "button": {"type": "string", "description": "Botão do mouse: 'left' ou 'right' (padrão: left)"}
            },
            required_parameters=[],
            permission=PermissionLevel.SAFE,
            handler=ComputerUseService.mouse_up,
            category="computer_use"
        ))

        self.register(ToolSpec(
            name="scroll",
            description="Rola a página ou janela verticalmente (positivo para cima, negativo para baixo).",
            parameters={
                "amount": {"type": "integer", "description": "Passos de rolagem (ex: -3 para rolar para baixo, 3 para rolar para cima)"}
            },
            required_parameters=[],
            permission=PermissionLevel.SAFE,
            handler=ComputerUseService.scroll,
            category="computer_use"
        ))

        self.register(ToolSpec(
            name="type_text",
            description="Digita texto no campo de entrada ativo do Windows, suportando caracteres especiais e acentuação brasileira.",
            parameters={
                "text": {"type": "string", "description": "Texto a ser digitado"},
                "expected_window": {"type": "string", "description": "Janela esperada para evitar digitar no aplicativo errado (opcional)"}
            },
            required_parameters=["text"],
            permission=PermissionLevel.SAFE,
            handler=ComputerUseService.type_text,
            category="computer_use"
        ))

        self.register(ToolSpec(
            name="press_key",
            description="Pressiona uma tecla especial do teclado (ex: enter, tab, escape, backspace, space, up, down).",
            parameters={
                "key": {"type": "string", "description": "Nome da tecla (ex: 'enter', 'tab', 'escape', 'backspace')"},
                "expected_window": {"type": "string", "description": "Janela esperada para segurança (opcional)"}
            },
            required_parameters=["key"],
            permission=PermissionLevel.SAFE,
            handler=ComputerUseService.press_key,
            category="computer_use"
        ))

        self.register(ToolSpec(
            name="hotkey",
            description="Executa um atalho de teclado composto (ex: ['ctrl', 'c'], ['alt', 'tab'], ou 'ctrl+l').",
            parameters={
                "keys": {"type": "array", "description": "Lista ou texto com as teclas do atalho (ex: ['ctrl', 't'] ou 'ctrl+l')"},
                "expected_window": {"type": "string", "description": "Janela esperada para segurança (opcional)"}
            },
            required_parameters=["keys"],
            permission=PermissionLevel.SAFE,
            handler=ComputerUseService.hotkey,
            category="computer_use"
        ))

        self.register(ToolSpec(
            name="observe_ui",
            description="Observa e inspeciona elementos interativos (botões, campos, links e suas coordenadas) na janela ativa antes de agir.",
            parameters={
                "max_elements": {"type": "integer", "description": "Limite máximo de elementos a inspecionar (padrão: 30)"}
            },
            required_parameters=[],
            permission=PermissionLevel.SAFE,
            handler=ComputerUseService.observe_ui,
            category="computer_use"
        ))

        self.register(ToolSpec(
            name="find_ui_element",
            description="Localiza um elemento interativo na tela pelo seu rótulo/texto e retorna suas coordenadas centrais.",
            parameters={
                "query": {"type": "string", "description": "Texto ou rótulo do elemento a encontrar (ex: 'Pesquisar', 'Fechar', 'OK')"},
                "control_type": {"type": "string", "description": "Tipo de controle opcional (ex: 'Button', 'Edit', 'Hyperlink')"}
            },
            required_parameters=["query"],
            permission=PermissionLevel.SAFE,
            handler=ComputerUseService.find_ui_element,
            category="computer_use"
        ))

        self.register(ToolSpec(
            name="click_element",
            description="Localiza um elemento na tela pelo nome/texto e clica sobre ele, com checagem contextual de segurança.",
            parameters={
                "query": {"type": "string", "description": "Nome ou rótulo do elemento a clicar (ex: 'Pesquisar', 'Minimizar')"},
                "button": {"type": "string", "description": "'left' ou 'right' (padrão: left)"},
                "expected_window": {"type": "string", "description": "Janela esperada para proteção contextual (opcional)"}
            },
            required_parameters=["query"],
            permission=PermissionLevel.SAFE,
            handler=ComputerUseService.click_element,
            category="computer_use"
        ))

        self.register(ToolSpec(
            name="computer_use",
            description="Orquestrador de Computer Use: executa uma sequência operacional no desktop seguindo o ciclo Observe->Act->Verify.",
            parameters={
                "goal": {"type": "string", "description": "Descrição do objetivo da operação"},
                "steps": {"type": "array", "description": "Lista de passos operacionais a executar em sequência"}
            },
            required_parameters=[],
            permission=PermissionLevel.SAFE,
            handler=ComputerUseService.computer_use,
            category="computer_use"
        ))

        self.register(ToolSpec(
            name="take_screenshot",
            description="Captura uma imagem da tela atual do computador.",
            parameters={
                "output_path": {"type": "string", "description": "Caminho para salvar o print (opcional)"}
            },
            required_parameters=[],
            permission=PermissionLevel.SAFE,
            handler=FileManager.take_screenshot,
            category="system"
        ))

        # -------------------------------------------------------------
        # 5. Browser Control Tools
        # -------------------------------------------------------------
        self.register(ToolSpec(
            name="open_url",
            description="Abre uma página web ou URL no navegador padrão.",
            parameters={
                "url": {"type": "string", "description": "Endereço web ou site (ex: 'https://youtube.com', 'google.com')"}
            },
            required_parameters=["url"],
            permission=PermissionLevel.SAFE,
            handler=BrowserService.open_url,
            category="browser"
        ))

        self.register(ToolSpec(
            name="search_web",
            description="Pesquisa um termo ou assunto na internet usando o navegador.",
            parameters={
                "query": {"type": "string", "description": "Termo a ser pesquisado na web"}
            },
            required_parameters=["query"],
            permission=PermissionLevel.SAFE,
            handler=BrowserService.search,
            category="browser"
        ))

        self.register(ToolSpec(
            name="new_browser_tab",
            description="Abre uma nova aba no navegador web com URL opcional.",
            parameters={
                "url": {"type": "string", "description": "URL para navegar na nova aba (opcional)"}
            },
            required_parameters=[],
            permission=PermissionLevel.SAFE,
            handler=BrowserService.new_browser_tab,
            category="browser"
        ))

        self.register(ToolSpec(
            name="close_browser_tab",
            description="Fecha a aba atualmente ativa no navegador.",
            parameters={},
            required_parameters=[],
            permission=PermissionLevel.SAFE,
            handler=BrowserService.close_browser_tab,
            category="browser"
        ))

        self.register(ToolSpec(
            name="switch_browser_tab",
            description="Alterna entre as abas do navegador (por índice numérico ou próxima/anterior).",
            parameters={
                "index": {"type": "integer", "description": "Número da aba de 1 a 8 (opcional)"},
                "direction": {"type": "string", "description": "'next' para próxima aba ou 'previous' para aba anterior"}
            },
            required_parameters=[],
            permission=PermissionLevel.SAFE,
            handler=BrowserService.switch_browser_tab,
            category="browser"
        ))

        self.register(ToolSpec(
            name="navigate_browser",
            description="Navega para uma URL na aba ativa do navegador digitando na barra de endereços.",
            parameters={
                "url": {"type": "string", "description": "Endereço web para navegar"}
            },
            required_parameters=["url"],
            permission=PermissionLevel.SAFE,
            handler=BrowserService.navigate_browser,
            category="browser"
        ))

        # -------------------------------------------------------------
        # 5. Persistent Browser Session Tools (Playwright Background Session)
        # -------------------------------------------------------------
        from backend.browser.session import get_browser_session, has_browser_session

        self.register(ToolSpec(
            name="browser_open",
            description="Abre ou navega para uma URL na sessão persistente do navegador do KON sem roubar foco nem usar mouse/teclado físico.",
            parameters={
                "url": {"type": "string", "description": "Endereço web ou site (ex: 'https://youtube.com', 'google.com')"}
            },
            required_parameters=["url"],
            permission=PermissionLevel.SAFE,
            handler=lambda url: get_browser_session().open(url),
            category="browser"
        ))

        self.register(ToolSpec(
            name="browser_search",
            description="Pesquisa no YouTube ou Google na sessão persistente do KON. Retorna lista de até 5 candidatos com título e URL. Se canais_only=True no YouTube, filtra por canais.",
            parameters={
                "query": {"type": "string", "description": "Termo de busca ou nome do canal"},
                "site": {"type": "string", "description": "'youtube' ou 'google' (padrão: 'youtube')", "enum": ["youtube", "google"]},
                "channels_only": {"type": "boolean", "description": "Se verdadeiro, busca apenas canais no YouTube"}
            },
            required_parameters=["query"],
            permission=PermissionLevel.SAFE,
            handler=lambda query, site="youtube", channels_only=False: get_browser_session().search(
                query=query, site=site, channels_only=channels_only
            ),
            category="browser"
        ))

        self.register(ToolSpec(
            name="browser_snapshot",
            description="Captura um snapshot semântico leve da página persistente (título, URL e até 25 elementos interativos com ID, role e texto).",
            parameters={},
            required_parameters=[],
            permission=PermissionLevel.SAFE,
            handler=lambda: get_browser_session().snapshot(),
            category="browser"
        ))

        self.register(ToolSpec(
            name="browser_click",
            description="Clica em um elemento semântico na página persistente sem mover o cursor físico do mouse. Opcionalmente verifica se navegou para o canal esperado.",
            parameters={
                "element_id": {"type": "integer", "description": "ID numérico do elemento obtido via browser_snapshot (1 a 25)"},
                "role": {"type": "string", "description": "Papel semântico do elemento (ex: 'link', 'button')"},
                "name": {"type": "string", "description": "Texto ou nome acessível do elemento a clicar"},
                "selector": {"type": "string", "description": "Seletor CSS ou texto alternativo do elemento"},
                "verify_channel": {"type": "string", "description": "Nome esperado do canal no YouTube para validação de integridade"}
            },
            required_parameters=[],
            permission=PermissionLevel.SAFE,
            handler=lambda element_id=None, role=None, name=None, selector=None, verify_channel=None: get_browser_session().click(
                element_id=element_id, role=role, name=name, selector=selector, verify_channel=verify_channel
            ),
            category="browser"
        ))

        self.register(ToolSpec(
            name="browser_type",
            description="Digita texto em um elemento na página persistente sem usar teclado físico.",
            parameters={
                "element_id": {"type": "integer", "description": "ID numérico do elemento obtido via browser_snapshot"},
                "selector": {"type": "string", "description": "Seletor CSS ou seletor do campo de texto"},
                "text": {"type": "string", "description": "Texto a ser digitado"},
                "submit": {"type": "boolean", "description": "Se verdadeiro, pressiona Enter após digitar"}
            },
            required_parameters=["text"],
            permission=PermissionLevel.SAFE,
            handler=lambda text, element_id=None, selector=None, submit=False: get_browser_session().type_text(
                text=text, element_id=element_id, selector=selector, submit=submit
            ),
            category="browser"
        ))

        def _smart_browser_go_back():
            if has_browser_session():
                return get_browser_session().go_back()
            return BrowserService.browser_go_back()

        def _smart_browser_reload():
            if has_browser_session():
                return get_browser_session().reload()
            return BrowserService.browser_reload()

        self.register(ToolSpec(
            name="browser_go_back",
            description="Volta para a página anterior no histórico do navegador.",
            parameters={},
            required_parameters=[],
            permission=PermissionLevel.SAFE,
            handler=_smart_browser_go_back,
            category="browser"
        ))

        self.register(ToolSpec(
            name="browser_go_forward",
            description="Avança para a próxima página no histórico do navegador.",
            parameters={},
            required_parameters=[],
            permission=PermissionLevel.SAFE,
            handler=BrowserService.browser_go_forward,
            category="browser"
        ))

        self.register(ToolSpec(
            name="browser_reload",
            description="Recarrega a página atual no navegador.",
            parameters={},
            required_parameters=[],
            permission=PermissionLevel.SAFE,
            handler=_smart_browser_reload,
            category="browser"
        ))

        self.register(ToolSpec(
            name="browser_read_page",
            description="Lê e inspeciona os elementos visíveis e estruturais da janela ativa do navegador.",
            parameters={},
            required_parameters=[],
            permission=PermissionLevel.SAFE,
            handler=BrowserService.browser_read_page,
            category="browser"
        ))


# Singleton default registry instance
_GLOBAL_TOOL_REGISTRY: Optional[ToolRegistry] = None


def get_tool_registry(memory_manager=None) -> ToolRegistry:
    global _GLOBAL_TOOL_REGISTRY
    if _GLOBAL_TOOL_REGISTRY is None:
        _GLOBAL_TOOL_REGISTRY = ToolRegistry(memory_manager=memory_manager)
    return _GLOBAL_TOOL_REGISTRY
