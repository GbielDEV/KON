"""
Unit tests for FileManager safe operations and security policy.
"""
from pathlib import Path
from backend.computer.files import FileManager
from backend.security.file_policy import is_sensitive_file


def test_create_and_delete_test_folder(tmp_path):
    res_create = FileManager.create_folder(name="TesteKON_Temp", parent=str(tmp_path))
    assert res_create["success"] is True
    folder_path = Path(res_create["path"])
    assert folder_path.exists()
    assert folder_path.is_dir()

    # Create dummy file inside
    dummy_file = folder_path / "teste.txt"
    dummy_file.write_text("conteúdo de teste", encoding="utf-8")
    assert dummy_file.exists()

    # Rename file
    res_rename = FileManager.rename_file(str(dummy_file), "teste_renomeado.txt")
    assert res_rename["success"] is True
    renamed_file = folder_path / "teste_renomeado.txt"
    assert renamed_file.exists()
    assert not dummy_file.exists()

    # Delete file
    res_del = FileManager.delete_file(str(renamed_file))
    assert res_del["success"] is True
    assert not renamed_file.exists()


def test_sensitive_file_policy_blocks_operations(tmp_path):
    sensitive_file = tmp_path / ".env"
    sensitive_file.write_text("SECRET=123", encoding="utf-8")
    assert is_sensitive_file(sensitive_file)

    # Deleting or reading sensitive file via FileManager must fail
    res_read = FileManager.read_file(str(sensitive_file))
    assert res_read["success"] is False
    assert res_read["error"] == "SECURITY_BLOCK"

    res_del = FileManager.delete_file(str(sensitive_file))
    assert res_del["success"] is False
    assert res_del["error"] == "SECURITY_BLOCK"


def test_format_system_info():
    info = FileManager.format_system_info(metric="ram")
    assert info["success"] is True
    assert "ram_percent" in info
    assert "memória" in info["message"].lower() or "ram" in info["message"].lower()
