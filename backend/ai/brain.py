"""
AI Brain and Tool Resolver integration for KON.
Bridges to backend.ai.planner.ToolResolver while preserving backward compatibility.
"""
from abc import ABC, abstractmethod
from typing import Dict, Any

from backend.ai.tool_registry import get_tool_registry
from backend.ai.planner import ToolResolver, PlanExecutor, ToolPlan, normalize_text


class BaseAIBrain(ABC):
    """Abstract AI Brain interface."""
    @abstractmethod
    async def process_intent(self, user_text: str) -> Dict[str, Any]:
        pass


class GenericCommandParser(BaseAIBrain):
    """
    General-purpose intent parser and tool resolver for KON.
    Understands free natural language in Brazilian Portuguese and translates into structured actions.
    """

    def __init__(self, tool_manager=None) -> None:
        self.registry = get_tool_registry()
        self.resolver = ToolResolver(registry=self.registry)
        self.executor = PlanExecutor(registry=self.registry)

    async def process_intent(self, user_text: str) -> Dict[str, Any]:
        """
        Parses a natural language query into a structured intent dict.
        """
        clean = normalize_text(user_text)
        if clean in ("ola kon", "ola", "oi kon", "oi", "bom dia", "boa tarde", "boa noite", "e ai kon", "e ai"):
            return {
                "intent": "greeting",
                "arguments": {},
                "confidence": 1.0,
                "needs_confirmation": False,
                "response_text": "Olá! Como posso ajudar você hoje?",
            }

        plan: ToolPlan = self.resolver.resolve(user_text)

        if not plan.success or not plan.steps:
            return {
                "intent": "unknown",
                "arguments": {"raw_text": user_text},
                "confidence": 0.0,
                "needs_confirmation": False,
                "response_text": "Não consegui reconhecer esse comando.",
            }

        first_step = plan.steps[0]
        tool_name = first_step.tool
        args = first_step.arguments

        # Return standardized structure matching both legacy and new expectations
        res = {
            "intent": tool_name,
            "tool": tool_name,
            "arguments": args,
            "steps": [s.__dict__ for s in plan.steps],
            "confidence": 1.0,
            "needs_confirmation": (self.registry.check_permission(tool_name) != "allow"),
        }

        if tool_name == "open_application":
            app_id = args.get("application", "")
            res["application"] = app_id
            display_name = "o Google Chrome" if app_id == "chrome" else app_id.title()
            res["response_text"] = f"Abrindo {display_name}."
        elif tool_name == "open_folder":
            folder_name = args.get("folder", "")
            res["folder"] = folder_name
            res["response_text"] = f"Abrindo a pasta {folder_name}."
        elif tool_name == "system_info":
            res["intent"] = "system_status"
            res["response_text"] = "Sistemas operacionais em ordem."
        elif tool_name == "create_folder":
            res["response_text"] = f"Criando pasta {args.get('name')}."
        else:
            res["response_text"] = f"Executando {tool_name}."


        return res


# Aliases for backward compatibility
DeterministicCommandParser = GenericCommandParser
MockAIBrain = GenericCommandParser
