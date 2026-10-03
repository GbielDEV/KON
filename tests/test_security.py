"""
Unit tests for KON Security subsystem (file_policy & subprocess_sandbox).
"""
import pytest
from backend.security.file_policy import is_sensitive_file, filter_sensitive_paths, validate_file_access
from backend.security.subprocess_sandbox import build_safe_env, run_safe_command, SandboxResult


def test_file_policy_sensitive_extensions():
    assert is_sensitive_file(".env")
    assert is_sensitive_file("id_rsa")
    assert is_sensitive_file("server.key")
    assert is_sensitive_file("db.kdbx")
    assert not is_sensitive_file("document.txt")
    assert not is_sensitive_file("report.pdf")


def test_file_policy_filter_paths():
    paths = ["test.txt", ".env", "main.py", "secret.key"]
    filtered = filter_sensitive_paths(paths)
    assert [p.name for p in filtered] == ["test.txt", "main.py"]


def test_file_policy_validation(tmp_path):
    safe_file = tmp_path / "data.json"
    safe_file.write_text('{"a": 1}')
    assert validate_file_access(safe_file) is True

    secret_file = tmp_path / ".env"
    secret_file.write_text("API_KEY=123")
    with pytest.raises(PermissionError):
        validate_file_access(secret_file)


def test_subprocess_sandbox_safe_env():
    env = build_safe_env(extra={"CUSTOM_VAR": "val"})
    assert "CUSTOM_VAR" in env
    assert env["CUSTOM_VAR"] == "val"
    assert "PATH" in env or "Path" in env


def test_subprocess_sandbox_run_command():
    res = run_safe_command(["cmd.exe", "/c", "echo", "KON_TEST"])
    assert isinstance(res, SandboxResult)
    assert res.returncode == 0
    assert "KON_TEST" in res.stdout
