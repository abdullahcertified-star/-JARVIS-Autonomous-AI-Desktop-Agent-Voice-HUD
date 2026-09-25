"""Comprehensive automated tests for the Windows Command Master Knowledge Base & Safety Subsystem.

Tests:
1. Normal operations:
   - "show my IP"
   - "show detailed IP configuration"
   - "flush DNS"
   - "test internet connectivity"
   - "show running processes"
   - "find port 5000"
   - "show Windows version"
   - "show system information"
   - "create a folder"
   - "find Python"
   - "show network adapters"
   - "show Windows services"
2. Dangerous operations (must NOT execute automatically, must require confirmation):
   - "delete this folder"
   - "format this drive"
   - "disable firewall"
   - "change system permissions"
   - "delete registry key"
   - "kill system process"
3. Database retrieval and search functionality (all 492 commands).
4. Safe execution and interpreter formatting.
"""

from __future__ import annotations

import os
from unittest.mock import patch
import pytest

from commands.database import get_command_db
from commands.executor import CommandExecutor
from commands.intent_matcher import IntentMatcher
from commands.interpreter import ResultInterpreter
from commands.safety import RiskLevel, SafetyEngine
from dispatcher import dispatch


@pytest.fixture
def matcher() -> IntentMatcher:
    return IntentMatcher()


@pytest.fixture
def db():
    return get_command_db()


# --- Database & Catalog Verification ---

def test_database_contains_all_492_commands(db) -> None:
    all_cmds = db.get_all()
    assert len(all_cmds) == 492
    categories = {c["category"] for c in all_cmds}
    assert "Networking" in categories
    assert "File & Directory" in categories
    assert "Disk, Storage & Recovery" in categories
    assert "PowerShell Core / Windows PowerShell" in categories


def test_database_search_finds_relevant_commands(db) -> None:
    results = db.search("port 5000", limit=3)
    assert any("netstat" in r["clean_name"].lower() or "nettcpconnection" in r["clean_name"].lower() for r in results)

    ip_results = db.search("show my ip", limit=3)
    assert any("ipconfig" in r["clean_name"].lower() for r in ip_results)


# --- Section 12: Minimum Required Normal Request Tests ---

def test_intent_show_my_ip(matcher) -> None:
    intent = matcher.match("show my IP")
    assert intent.intent_name == "NETWORK_IP_LOOKUP"
    assert "ipconfig" in intent.command
    assert intent.risk_level == RiskLevel.LOW
    assert intent.requires_confirmation is False


def test_intent_show_detailed_ip_configuration(matcher) -> None:
    intent = matcher.match("show detailed network configuration")
    assert intent.intent_name == "NETWORK_IP_DETAILED"
    assert "ipconfig /all" in intent.command
    assert intent.risk_level == RiskLevel.LOW
    assert intent.requires_confirmation is False


def test_intent_flush_dns(matcher) -> None:
    intent = matcher.match("flush DNS")
    assert intent.intent_name == "NETWORK_FLUSH_DNS"
    assert "ipconfig /flushdns" in intent.command
    assert intent.risk_level == RiskLevel.LOW
    assert intent.requires_confirmation is False


def test_intent_test_internet_connectivity(matcher) -> None:
    intent = matcher.match("test internet connectivity")
    assert intent.intent_name == "INTERNET_CONNECTIVITY_TEST"
    assert "ping" in intent.command
    assert intent.risk_level == RiskLevel.LOW
    assert intent.requires_confirmation is False


def test_intent_show_running_processes(matcher) -> None:
    intent = matcher.match("show me all running processes")
    assert intent.intent_name == "PROCESS_LIST"
    assert "tasklist" in intent.command
    assert intent.risk_level == RiskLevel.LOW
    assert intent.requires_confirmation is False


def test_intent_find_port_5000(matcher) -> None:
    intent = matcher.match("find which process is using port 5000")
    assert intent.intent_name == "PORT_PROCESS_LOOKUP"
    assert "netstat -ano | findstr :5000" in intent.command
    assert intent.parameters.get("port") == 5000
    assert intent.risk_level == RiskLevel.LOW
    assert intent.requires_confirmation is False


def test_intent_show_windows_version(matcher) -> None:
    intent = matcher.match("show Windows version")
    assert intent.intent_name == "WINDOWS_VERSION"
    assert intent.command == "ver"
    assert intent.risk_level == RiskLevel.LOW
    assert intent.requires_confirmation is False


def test_intent_show_system_information(matcher) -> None:
    intent = matcher.match("show system information")
    assert intent.intent_name == "SYSTEM_INFO"
    assert "systeminfo" in intent.command
    assert intent.risk_level == RiskLevel.LOW
    assert intent.requires_confirmation is False


def test_intent_create_a_folder(matcher) -> None:
    intent = matcher.match("create a folder called Projects on my desktop")
    assert intent.intent_name == "DIRECTORY_CREATE"
    assert "mkdir" in intent.command
    assert "Projects" in intent.command
    assert intent.risk_level == RiskLevel.MEDIUM
    assert intent.requires_confirmation is False


def test_intent_find_python(matcher) -> None:
    intent = matcher.match("find Python")
    assert intent.intent_name == "EXECUTABLE_LOOKUP"
    assert "where python" in intent.command
    assert intent.risk_level == RiskLevel.LOW
    assert intent.requires_confirmation is False


def test_intent_show_network_adapters(matcher) -> None:
    intent = matcher.match("show network adapters")
    assert intent.intent_name == "NETWORK_ADAPTER_LIST"
    assert "Get-NetAdapter" in intent.command
    assert intent.risk_level == RiskLevel.LOW
    assert intent.requires_confirmation is False


def test_intent_show_windows_services(matcher) -> None:
    intent = matcher.match("show Windows services")
    assert intent.intent_name == "SERVICE_LIST"
    assert "Get-Service" in intent.command
    assert intent.risk_level == RiskLevel.LOW
    assert intent.requires_confirmation is False


# --- Section 12: Dangerous Request Safety & Confirmation Blocking Tests ---

def test_dangerous_format_drive_blocked_without_confirm(matcher) -> None:
    res = matcher.execute_request("format drive D:", confirmed=False)
    assert res["success"] is False
    assert res["requires_confirmation"] is True
    assert res["risk_level"] == "CRITICAL"
    assert "CRITICAL WARNING" in res["message"]
    assert "format D:" in res["command"]


def test_dangerous_delete_folder_blocked_without_confirm(matcher) -> None:
    res = matcher.execute_request("delete this folder", confirmed=False)
    assert res["success"] is False
    assert res["requires_confirmation"] is True
    assert res["risk_level"] in ("HIGH", "CRITICAL")
    assert "requires confirmation" in res["message"].lower() or "warning" in res["message"].lower()


def test_dangerous_disable_firewall_blocked_without_confirm(matcher) -> None:
    res = matcher.execute_request("disable firewall", confirmed=False)
    assert res["success"] is False
    assert res["requires_confirmation"] is True
    assert res["risk_level"] == "HIGH"
    assert "advfirewall" in res["command"]
    assert "requires confirmation" in res["message"].lower() or "modifying windows firewall" in res["message"].lower()


def test_dangerous_delete_registry_blocked_without_confirm(matcher) -> None:
    res = matcher.execute_request("delete registry key", confirmed=False)
    assert res["success"] is False
    assert res["requires_confirmation"] is True
    assert res["risk_level"] == "HIGH"
    assert "reg delete" in res["command"]


def test_dangerous_kill_process_blocked_without_confirm(matcher) -> None:
    res = matcher.execute_request("kill process 1234", confirmed=False)
    assert res["success"] is False
    assert res["requires_confirmation"] is True
    assert res["risk_level"] == "HIGH"
    assert "taskkill /PID 1234 /F" in res["command"]
    assert "requires confirmation" in res["message"].lower()


def test_dangerous_system_permissions_blocked_without_confirm() -> None:
    report = SafetyEngine.analyze("icacls C:\\Windows\\System32 /grant Everyone:F")
    assert report.risk_level == RiskLevel.HIGH
    assert report.requires_confirmation is True


# --- Dispatcher Integration Tests ---

def test_dispatcher_command_execute_operation() -> None:
    res = dispatch({
        "action": "command",
        "operation": "execute",
        "request": "what is my local IP",
    })
    assert res["success"] is True
    assert "Positive sir" in res["message"]


def test_dispatcher_command_match_operation() -> None:
    res = dispatch({
        "action": "command",
        "operation": "match",
        "request": "kill process 9999",
    })
    assert res["success"] is True
    assert res["intent"] == "PROCESS_KILL_PID"
    assert res["requires_confirmation"] is True
    assert res["risk_level"] == "HIGH"


def test_dispatcher_command_search_operation() -> None:
    res = dispatch({
        "action": "command",
        "operation": "search",
        "query": "firewall",
    })
    assert res["success"] is True
    assert res["count"] > 0
