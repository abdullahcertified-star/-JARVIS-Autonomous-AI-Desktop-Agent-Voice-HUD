"""JARVIS Windows Command Knowledge Base & Safe Execution Subsystem.

Provides natural language intent mapping, structured command reference from the
Windows Command Master Reference, safe sandboxed execution for CMD and PowerShell,
dynamic parameter binding, four-tier risk classification, and natural language
result interpretation.
"""

from commands.database import CommandDatabase, get_command_db
from commands.safety import SafetyEngine, RiskLevel
from commands.executor import CommandExecutor
from commands.interpreter import ResultInterpreter
from commands.intent_matcher import IntentMatcher, CommandIntent

__all__ = [
    "CommandDatabase",
    "get_command_db",
    "SafetyEngine",
    "RiskLevel",
    "CommandExecutor",
    "ResultInterpreter",
    "IntentMatcher",
    "CommandIntent",
]
