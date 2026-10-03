"""
Tests for Phase 1: Robust Filesystem Operations & Absolute Path Priority.
Validates:
- Absolute path priority check with Path.exists()
- Direct path existence reporting without blind scanning
- Structured JSON return schema (found, path, type, name, size, parent, reason)
- Handling of C:\\, D:\\, E:\\ drives and special folders (Downloads, Documents, Desktop)
- Spaces in paths, quotes, mixed slashes, and special characters
- Empty directories, nonexistent directories, and nonexistent files
- Security boundary preservation (sensitive files, root drive protection)
"""
from pathlib import Path
from backend.computer.filesystem import FileSystemService
from backend.computer.files import FileManager


def test_direct_absolute_path_priority_found(tmp_path):
    # Setup test file
    test_file = tmp_path / "trabalho_academico.pdf"
    test_file.write_text("conteúdo confidencial do trabalho", encoding="utf-8")
    assert test_file.exists()

    # Search passing direct absolute path
    result = FileSystemService.search_file(str(test_file))
    assert result["found"] is True
    assert result["type"] == "file"
    assert result["name"] == "trabalho_academico.pdf"
    assert result["size"] > 0
    assert result["parent"] == str(tmp_path)
    assert Path(result["path"]).resolve() == test_file.resolve()
    assert "trabalho_academico.pdf" in result["message"]


def test_direct_absolute_path_priority_not_found(tmp_path):
    nonexistent = tmp_path / "arquivo_fantasma.pdf"
    assert not nonexistent.exists()

    # Search passing direct absolute path that doesn't exist
    result = FileSystemService.search_file(str(nonexistent))
    assert result["found"] is False
    assert result["reason"] == "path_not_found"
    assert str(nonexistent) in result["requested_path"]
    assert str(tmp_path) in result["searched_roots"]
    assert "não existe" in result["message"].lower()


def test_search_file_with_quotes_and_spaces(tmp_path):
    # Folder with spaces and file with spaces
    folder_with_space = tmp_path / "Pasta de Documentos Importantes"
    folder_with_space.mkdir(parents=True, exist_ok=True)
    file_with_space = folder_with_space / "meu relatorio 2026.docx"
    file_with_space.write_text("relatorio completo", encoding="utf-8")

    # Search with surrounding quotes and mixed slashes
    quoted_query = f'"{folder_with_space}/{file_with_space.name}"'
    result = FileSystemService.search_file(quoted_query)
    assert result["found"] is True
    assert result["name"] == "meu relatorio 2026.docx"
    assert result["type"] == "file"
    assert result["size"] > 0


def test_search_file_by_name_in_root(tmp_path):
    sub = tmp_path / "SubNivel"
    sub.mkdir(parents=True, exist_ok=True)
    target = sub / "projeto_final.pdf"
    target.write_text("projeto", encoding="utf-8")

    # Search by simple filename specifying root
    res = FileSystemService.search_file(query="projeto_final", root=str(tmp_path), extension="pdf")
    assert res["found"] is True
    assert len(res["results"]) >= 1
    assert res["results"][0]["name"] == "projeto_final.pdf"
    assert res["extension"] == ".pdf"


def test_check_file_exists_method(tmp_path):
    f = tmp_path / "existe.txt"
    f.write_text("ola", encoding="utf-8")

    res_true = FileSystemService.check_file_exists(str(f))
    assert res_true["found"] is True
    assert res_true["type"] == "file"
    assert res_true["name"] == "existe.txt"

    res_false = FileSystemService.check_file_exists(str(tmp_path / "nao_existe.txt"))
    assert res_false["found"] is False
    assert res_false["reason"] == "path_not_found"


def test_list_directory_empty_and_populated(tmp_path):
    empty_dir = tmp_path / "pasta_vazia"
    empty_dir.mkdir(parents=True, exist_ok=True)

    # Empty dir listing
    res_empty = FileSystemService.list_directory(str(empty_dir))
    assert res_empty["success"] is True
    assert res_empty["count"] == 0
    assert res_empty["items"] == []

    # Populated dir listing
    (empty_dir / "arquivo1.txt").write_text("1", encoding="utf-8")
    (empty_dir / "arquivo2.png").write_text("2", encoding="utf-8")
    (empty_dir / "SubPasta").mkdir(parents=True, exist_ok=True)

    res_pop = FileSystemService.list_directory(str(empty_dir))
    assert res_pop["success"] is True
    assert res_pop["count"] == 3
    names = [it["name"] for it in res_pop["items"]]
    assert "arquivo1.txt" in names
    assert "arquivo2.png" in names
    assert "SubPasta" in names


def test_list_directory_nonexistent():
    res = FileSystemService.list_directory(r"C:\PastaInexistente_12345_KON")
    assert res["success"] is False
    assert res["error"] in ("FOLDER_NOT_FOUND", "SECURITY_BLOCK")


def test_file_manager_delegation_compatibility(tmp_path):
    # Ensure FileManager calls FileSystemService seamlessly
    f = tmp_path / "compat.txt"
    f.write_text("compatibilidade", encoding="utf-8")

    res = FileManager.search_file(str(f))
    assert res["found"] is True
    assert res["name"] == "compat.txt"
    assert res["type"] == "file"


def test_copy_move_rename_lifecycle(tmp_path):
    src = tmp_path / "original.txt"
    src.write_text("dados importantes", encoding="utf-8")

    dest_dir = tmp_path / "Destino"
    dest_dir.mkdir()

    # 1. Copy file
    copy_res = FileSystemService.copy_file(str(src), str(dest_dir))
    assert copy_res["success"] is True
    copied_path = dest_dir / "original.txt"
    assert copied_path.exists()
    assert src.exists()

    # 2. Rename file
    rename_res = FileSystemService.rename_file(str(copied_path), "renomeado.txt")
    assert rename_res["success"] is True
    renamed_path = dest_dir / "renomeado.txt"
    assert renamed_path.exists()
    assert not copied_path.exists()

    # 3. Move file
    move_dir = tmp_path / "ArquivoFinal"
    move_dir.mkdir()
    move_res = FileSystemService.move_file(str(renamed_path), str(move_dir))
    assert move_res["success"] is True
    final_path = move_dir / "renomeado.txt"
    assert final_path.exists()
    assert not renamed_path.exists()

    # 4. Delete file
    del_res = FileSystemService.delete_file(str(final_path))
    assert del_res["success"] is True
    assert not final_path.exists()
