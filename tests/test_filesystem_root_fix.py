"""
Unit Tests for KON Filesystem Root Scoping, Decimal Stem Parsing,
Tiered Name Matching, Referential Open, and Access Policies.
"""
import os
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from backend.computer.filesystem import FileSystemService
from backend.computer.files import FileManager
from backend.computer.path_resolver import (
    UniversalPathResolver,
    parse_query_stem_and_ext,
    score_filename_match,
    WindowsKnownFolders,
)
from backend.ai.tool_registry import ToolRegistry, PermissionLevel
from backend.ai.gemini_tools import GeminiToolDispatcher


def test_parse_query_stem_and_ext():
    """Validates that decimal version numbers like 2.3 or 1.0 are kept in stem, not parsed as extensions."""
    stem, ext = parse_query_stem_and_ext("marketing de influencias 2.3")
    assert stem == "marketing de influencias 2.3"
    assert ext is None

    stem, ext = parse_query_stem_and_ext("versao 1.0")
    assert stem == "versao 1.0"
    assert ext is None

    stem, ext = parse_query_stem_and_ext("relatorio_financeiro.pdf")
    assert stem == "relatorio_financeiro"
    assert ext == "pdf"

    stem, ext = parse_query_stem_and_ext("documento.DOCX")
    assert stem == "documento"
    assert ext == "docx"


def test_score_filename_match_tiered():
    """Validates 6-stage tiered name matching prioritizing exact/normalized stem over fuzzy."""
    target_stem, target_ext = parse_query_stem_and_ext("marketing de influencias 2.3")

    # Match against 2.3.pdf -> stage should be normalized_stem with score >= 0.98
    score_23, stage_23 = score_filename_match(
        target_stem,
        target_ext,
        "Marketing de Influências 2.3.pdf",
        "Marketing de Influências 2.3",
        "pdf",
    )
    assert score_23 >= 0.98
    assert stage_23 == "normalized_stem"

    # Match against 2.2.pdf -> should NOT be normalized_stem, score < 0.85
    score_22, stage_22 = score_filename_match(
        target_stem,
        target_ext,
        "Marketing de Influências 2.2.pdf",
        "Marketing de Influências 2.2",
        "pdf",
    )
    assert score_22 < 0.85
    assert stage_22 != "normalized_stem"
    assert score_23 > score_22


def test_search_file_respects_root_downloads():
    """
    Validates that root='Downloads' resolves to the user's real Downloads folder
    and searches strictly within it without scanning whole drives.
    """
    downloads_path = WindowsKnownFolders.get_known_folders().get("downloads")
    if not downloads_path or not downloads_path.exists():
        pytest.skip("Pasta Downloads real não disponível neste ambiente.")

    res = FileSystemService.search_file("marketing de influencias 2.3", root="Downloads")
    assert res["found"] is True
    assert "Marketing de Influências 2.3" in res["name"]
    # The search must have searched within the resolved Downloads folder
    assert str(downloads_path).lower() in res["parent"].lower()


def test_search_file_nonexistent_root_fails_immediately():
    """Validates that a non-existent root returns root_not_found immediately without falling back to whole drives."""
    res = FileSystemService.search_file("marketing de influencias 2.3", root="PastaTotalmenteInexistente999XYZ")
    assert res["found"] is False
    assert res["success"] is False
    assert res["reason"] == "root_not_found"
    assert "PastaTotalmenteInexistente999XYZ" in res["message"]


def test_search_file_without_root_global_search():
    """Validates that without root, search_file scans user folders and accessible drives."""
    res = FileSystemService.search_file("marketing de influencias 2.3")
    assert res["found"] is True
    assert "Marketing de Influências 2.3" in res["name"]


def test_referential_open_file(monkeypatch):
    """Validates opening by reference ('abra', 'abra ele', '') to the last found file."""
    # 1. Locate file
    res = FileSystemService.search_file("marketing de influencias 2.3", root="Downloads")
    assert res["found"] is True

    opened_files = []
    monkeypatch.setattr(os, "startfile", lambda p: opened_files.append(str(p)))

    # 2. Open via 'abra'
    open_res = FileSystemService.open_file("abra")
    assert open_res["success"] is True
    assert "Marketing de Influências 2.3" in open_res["name"]
    assert len(opened_files) == 1

    # 3. Open via empty path
    open_res2 = FileSystemService.open_file("")
    assert open_res2["success"] is True
    assert "Marketing de Influências 2.3" in open_res2["name"]
    assert len(opened_files) == 2


def test_permission_policies():
    """Validates permission levels in ToolRegistry according to access policy."""
    registry = ToolRegistry()

    # Reading / Viewing / Searching / Locating / Opening -> SAFE
    safe_tools = [
        "open_file",
        "open_folder",
        "open_application",
        "launch_application",
        "search_file",
        "search_folder",
        "list_directory",
        "check_file_exists",
        "check_path",
        "get_file_info",
        "get_folder_info",
        "get_system_info",
        "get_disk_info",
        "get_processes",
        "get_datetime",
        "get_screen_info",
        "get_active_window",
        "list_windows",
        "focus_window",
        "maximize_window",
        "minimize_window",
        "restore_window",
        "move_mouse",
        "click",
    ]
    for t in safe_tools:
        spec = registry.get_tool(t)
        assert spec is not None, f"Tool '{t}' deve estar registrada."
        assert spec.permission == PermissionLevel.SAFE, f"Tool '{t}' deve ter nível SAFE."

    # Creating / Modifying / Closing -> CONFIRM
    confirm_tools = [
        "create_file",
        "create_folder",
        "move_file",
        "rename_file",
        "copy_file",
        "close_application",
        "close_window",
    ]
    for t in confirm_tools:
        spec = registry.get_tool(t)
        assert spec is not None, f"Tool '{t}' deve estar registrada."
        assert spec.permission == PermissionLevel.CONFIRM, f"Tool '{t}' deve ter nível CONFIRM."

    # Destructive / System -> CRITICAL
    critical_tools = [
        "delete_file",
        "shutdown_system",
        "restart_system",
    ]
    for t in critical_tools:
        spec = registry.get_tool(t)
        assert spec is not None, f"Tool '{t}' deve estar registrada."
        assert spec.permission == PermissionLevel.CRITICAL, f"Tool '{t}' deve ter nível CRITICAL."


def test_contextual_click_risk_assessment():
    """Validates that GeminiToolExecutor._assess_dynamic_risk escalates clicks targeting destructive actions."""
    registry = ToolRegistry()
    executor = GeminiToolDispatcher(registry=registry)

    # Standard click -> SAFE
    risk, summary = executor._assess_dynamic_risk("click", {"x": 100, "y": 200, "expected_window": "Bloco de Notas"})
    assert risk == "SAFE"

    # Click with destructive target -> escalates to CONFIRM
    risk_del, summary_del = executor._assess_dynamic_risk("click", {"target": "Botão Excluir Definitivamente"})
    assert risk_del == "CONFIRM"
    assert "exclusão ou alteração" in summary_del

    risk_rem, summary_rem = executor._assess_dynamic_risk("click", {"text": "Remover tudo do disco"})
    assert risk_rem == "CONFIRM"

    # Open file -> SAFE
    risk_open, _ = executor._assess_dynamic_risk("open_file", {"path": "documento.pdf"})
    assert risk_open == "SAFE"

    # Open app -> SAFE
    risk_app, _ = executor._assess_dynamic_risk("open_application", {"application": "chrome"})
    assert risk_app == "SAFE"
