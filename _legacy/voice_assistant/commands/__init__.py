"""
Command Registry and execution handlers for KON.
"""
from voice_assistant.commands.registry import CommandRegistry, command, get_registry
import voice_assistant.commands.system_commands  # noqa: F401
import voice_assistant.commands.media_commands   # noqa: F401

__all__ = ["CommandRegistry", "command", "get_registry"]
