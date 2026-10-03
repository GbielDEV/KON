"""
Comprehensive Unit & Security tests for KON Computer Control & Security Layer.
Tests:
- Path Traversal & Protected Directory blocking
- Sensitive file policies (.env, keys)
- ConfirmationManager lifecycle, expiration, token generation, and single-use validation
- Natural voice consent resolution (affirmative/negative)
- Out-of-context "sim" rejection
- Mass deletion blast radius & impact calculation (elevated to CRITICAL)
- Cancellation handling ("não", "cancela", "esquece")
- Audit logging verification in logs/audit_security.jsonl
"""
import time
import pytest

from backend.security.path_validator import PathSecurityValidator, PathSecurityError
from backend.security.file_policy import is_sensitive_file, validate_file_access
from backend.security.confirmation_manager import (
    ConfirmationManager,
    ConfirmationStatus,
    get_confirmation_manager,
)
from backend.security.audit_logger import AuditLogger
from backend.computer.files import FileManager
from backend.computer.system import SystemTelemetry
from backend.ai.tool_registry import get_tool_registry


# =====================================================================
# 1. Path Security & Traversal Protection
# =====================================================================

def test_path_traversal_detection_blocked():
    """Checks that any '..' sequence in paths is immediately caught and blocked."""
    malicious_paths = [
        r"downloads\..\..\Windows\System32\cmd.exe",
        r"..\..\boot.ini",
        r"C:\Users\Default\..\..\Windows",
        "folder/../../../etc/passwd",
    ]
    for p in malicious_paths:
        with pytest.raises(PathSecurityError, match=r"path traversal|fora"):
            PathSecurityValidator.sanitize_and_resolve(p, base_dir=r"C:\Users\Default\Downloads")


def test_protected_windows_directories_blocked_for_write(tmp_path):
    """Blocks write/delete operations targeting core Windows system directories."""
    protected_targets = [
        r"C:\Windows\System32\malicious.dll",
        r"C:\Program Files\teste.txt",
        "C:\\",
    ]
    for target in protected_targets:
        with pytest.raises(PathSecurityError):
            PathSecurityValidator.validate_safe_for_write(target)

        with pytest.raises(PathSecurityError):
            PathSecurityValidator.validate_safe_for_deletion(target)


def test_sensitive_file_blocking(tmp_path):
    """Verifies that credentials and secrets cannot be read, written, or deleted."""
    secret_file = tmp_path / ".env"
    secret_file.write_text("OPENAI_API_KEY=sk-test", encoding="utf-8")
    assert is_sensitive_file(secret_file)

    with pytest.raises(PermissionError):
        validate_file_access(secret_file, mode="read")

    with pytest.raises(PermissionError):
        validate_file_access(secret_file, mode="write")

    with pytest.raises(PermissionError):
        validate_file_access(secret_file, mode="delete")


# =====================================================================
# 2. Confirmation Manager, Expiration & Voice Consent
# =====================================================================

def test_confirmation_lifecycle_and_token():
    cm = ConfirmationManager(default_timeout_seconds=5.0)
    conf = cm.create_confirmation(
        tool="delete_file",
        arguments={"path": "teste.txt"},
        impact_summary="Excluir arquivo de teste",
        permission_level="CONFIRM",
    )
    assert conf.status == ConfirmationStatus.PENDING
    assert conf.confirmation_id is not None

    # User approves
    success, token, msg = cm.resolve_confirmation(conf.confirmation_id, approved=True)
    assert success is True
    assert token is not None
    assert conf.status == ConfirmationStatus.APPROVED

    # Token can only be used once
    assert cm.validate_authorization_token("delete_file", token) is True
    assert cm.validate_authorization_token("delete_file", token) is False  # Replay blocked


def test_confirmation_expiration():
    """A confirmation must expire after timeout and cannot be approved."""
    cm = ConfirmationManager(default_timeout_seconds=0.1)
    conf = cm.create_confirmation(
        tool="delete_file",
        arguments={"path": "teste.txt"},
        impact_summary="Excluir arquivo de teste",
        timeout_seconds=0.1,
    )
    time.sleep(0.15)
    assert conf.is_expired()

    # Attempting to approve an expired confirmation must fail
    success, token, msg = cm.resolve_confirmation(conf.confirmation_id, approved=True)
    assert success is False
    assert token is None
    assert "expirou" in msg.lower()
    assert conf.status == ConfirmationStatus.EXPIRED


def test_voice_consent_natural_recognition():
    cm = ConfirmationManager()

    # Affirmative expressions
    affirmatives = ["Sim", "pode", "pode fazer", "manda", "confirmo", "positivo", "claro, pode sim"]
    for text in affirmatives:
        assert cm.parse_natural_consent(text) is True, f"Falha ao reconhecer afirmativo: '{text}'"

    # Negative expressions
    negatives = ["Não", "cancela", "esquece", "deixa pra lá", "para", "não faça isso", "negativo"]
    for text in negatives:
        assert cm.parse_natural_consent(text) is False, f"Falha ao reconhecer negativo: '{text}'"

    # Unrelated speech (out of context)
    unrelated = ["Que horas são?", "Abra o Chrome", "Como está o clima?", "E aí"]
    for text in unrelated:
        assert cm.parse_natural_consent(text) is None, f"Texto não relacionado foi interpretado como consentimento: '{text}'"


def test_out_of_context_confirmation_rejection():
    """An affirmative response when NO confirmation is pending must NOT authorize anything."""
    cm = ConfirmationManager()
    # Ensure no pending confirmation
    cm._pending.clear()
    cm._active_id = None

    success, token, msg = cm.resolve_confirmation(confirmation_id=None, approved=True)
    assert success is False
    assert token is None
    assert "Nenhuma confirmação pendente" in msg


def test_confirmation_cancellation_flow():
    """User cancels an action with 'não' / 'cancela'."""
    cm = ConfirmationManager()
    conf = cm.create_confirmation(
        tool="delete_file",
        arguments={"path": "relatorio.pdf"},
        impact_summary="Excluir relatorio.pdf",
    )

    success, token, msg = cm.resolve_confirmation(conf.confirmation_id, approved=False)
    assert success is True
    assert token is None
    assert conf.status == ConfirmationStatus.REJECTED
    assert "cancelada" in msg.lower()


# =====================================================================
# 3. Mass Deletion Blast Radius & Impact Calculation
# =====================================================================

def test_mass_deletion_impact_calculation(tmp_path):
    """
    Creating a directory with multiple files (> 5) must calculate total files,
    total bytes, and elevate risk level to CRITICAL.
    """
    test_dir = tmp_path / "Downloads_Simulado"
    test_dir.mkdir()

    for i in range(12):
        f = test_dir / f"arquivo_{i}.txt"
        f.write_text("Conteúdo de teste para cálculo de impacto" * 10, encoding="utf-8")

    impact = FileManager.calculate_deletion_impact(str(test_dir))
    assert impact["exists"] is True
    assert impact["is_directory"] is True
    assert impact["file_count"] == 12
    assert impact["total_size_bytes"] > 0
    assert impact["risk_level"] == "CRITICAL"
    assert "12 arquivo(s)" in impact["impact_summary"]
    assert "permanentemente" in impact["impact_summary"]


# =====================================================================
# 4. Safe Operations (No Confirmation Needed)
# =====================================================================

def test_safe_windows_tools():
    """System tools must execute without confirmation and return structured data."""
    sys_info = FileManager.format_system_info(metric="cpu")
    assert sys_info["success"] is True
    assert "cpu_percent" in sys_info

    disk_info = SystemTelemetry.get_disk_info()
    assert disk_info["success"] is True
    assert "disks" in disk_info
    assert len(disk_info["disks"]) > 0

    datetime_info = SystemTelemetry.get_datetime()
    assert datetime_info["success"] is True
    assert "date" in datetime_info
    assert "time" in datetime_info
    assert "weekday" in datetime_info


# =====================================================================
# 5. Audit Logging Verification
# =====================================================================

def test_audit_logger_records_and_retrieves(tmp_path):
    log_file = tmp_path / "audit_test.jsonl"
    logger = AuditLogger(log_path=log_file)

    logger.log_event(
        tool="delete_file",
        arguments={"path": "C:\\teste.txt", "api_key": "secret123"},
        risk_level="CRITICAL",
        decision="CONFIRM",
        confirmation_required=True,
        user_confirmation=True,
        execution_result="Sucesso: Arquivo excluído com sucesso.",
    )

    records = logger.read_recent_logs(limit=10)
    assert len(records) == 1
    rec = records[0]
    assert rec["tool"] == "delete_file"
    assert rec["risk_level"] == "CRITICAL"
    assert rec["decision"] == "CONFIRM"
    assert rec["user_confirmation"] is True
    assert rec["arguments"]["api_key"] == "[REDACTED]"
    assert rec["arguments"]["path"] == "C:\\teste.txt"


# =====================================================================
# 6. End-to-End Dispatcher & Token-Enforced Execution
# =====================================================================

@pytest.mark.anyio
async def test_dispatcher_authorized_deletion_flow(tmp_path):
    """
    When a user confirms a deletion, dispatcher executes the tool with token
    and the file is deleted.
    """
    from backend.ai.gemini_tools import GeminiToolDispatcher

    test_file = tmp_path / "arquivo_para_apagar.txt"
    test_file.write_text("conteúdo temporário", encoding="utf-8")
    assert test_file.exists()

    registry = get_tool_registry()

    # User confirms the request
    async def approve_request(req):
        return True

    dispatcher = GeminiToolDispatcher(registry=registry, on_confirmation_request=approve_request)

    class MockCall:
        id = "call_del_1"
        name = "delete_file"
        args = {"path": str(test_file)}

    responses = await dispatcher.execute_function_calls([MockCall()])
    assert len(responses) == 1
    assert "sucesso" in responses[0].response.get("result", "").lower()
    assert not test_file.exists()


@pytest.mark.anyio
async def test_dispatcher_rejected_deletion_preserves_file(tmp_path):
    """
    When a user cancels or rejects, file is preserved and Gemini receives cancellation.
    """
    from backend.ai.gemini_tools import GeminiToolDispatcher

    test_file = tmp_path / "arquivo_preservado.txt"
    test_file.write_text("conteúdo importante", encoding="utf-8")
    assert test_file.exists()

    registry = get_tool_registry()

    # User rejects the request
    async def reject_request(req):
        return False

    dispatcher = GeminiToolDispatcher(registry=registry, on_confirmation_request=reject_request)

    class MockCall:
        id = "call_del_2"
        name = "delete_file"
        args = {"path": str(test_file)}

    responses = await dispatcher.execute_function_calls([MockCall()])
    assert len(responses) == 1
    assert "cancelou" in responses[0].response.get("result", "").lower() or "não autorizou" in responses[0].response.get("result", "").lower()
    assert test_file.exists()  # File was NOT deleted!


def test_direct_execution_blocked_without_token(tmp_path):
    """Calling execute_tool directly for CONFIRM/CRITICAL tools without valid token must fail."""
    test_file = tmp_path / "teste_seguro.txt"
    test_file.write_text("dados", encoding="utf-8")

    registry = get_tool_registry()
    res = registry.execute_tool("delete_file", path=str(test_file))
    assert res["success"] is False
    assert res["error"] == "CONFIRMATION_REQUIRED"
    assert test_file.exists()

    # Now create valid confirmation and token
    cm = get_confirmation_manager()
    conf = cm.create_confirmation("delete_file", {"path": str(test_file)}, "Excluir")
    _, token, _ = cm.resolve_confirmation(conf.confirmation_id, approved=True)

    # Execute with valid token
    res_auth = registry.execute_tool("delete_file", authorization_token=token, path=str(test_file))
    assert res_auth["success"] is True
    assert not test_file.exists()


def test_file_operations_create_copy_move_delete(tmp_path):
    """Tests file operations (create_file, copy_file, move_file, list_directory)."""
    # 1. Create file
    new_f = tmp_path / "criado.txt"
    res_c = FileManager.create_file(str(new_f), content="Olá KON")
    assert res_c["success"] is True
    assert new_f.exists()

    # 2. Copy file
    copied_f = tmp_path / "copiado.txt"
    res_cp = FileManager.copy_file(str(new_f), str(copied_f))
    assert res_cp["success"] is True
    assert copied_f.exists()

    # 3. Move file
    moved_f = tmp_path / "movido.txt"
    res_mv = FileManager.move_file(str(copied_f), str(moved_f))
    assert res_mv["success"] is True
    assert moved_f.exists()
    assert not copied_f.exists()

    # 4. List directory
    res_list = FileManager.list_directory(str(tmp_path))
    assert res_list["success"] is True
    assert res_list["count"] >= 2
