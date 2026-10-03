"""
Suíte Universal de Testes de Resolução de Arquivos e Pastas do KON (TEST-FS-001 a TEST-FS-020).
Valida todos os requisitos de resolução determinística, hierarquia de 5 prioridades,
Windows Known Folders nativo, multi-unidade (C:, D:, E:), Unicode, desambiguação e segurança.
"""
from pathlib import Path
import os
import pytest

from backend.computer.path_resolver import (
    UniversalPathResolver,
    WindowsKnownFolders,
    DriveManager,
    PathNormalizer,
    PathAliasRegistry,
    SmartPathSearcher,
)
from backend.computer.filesystem import FileSystemService
from backend.computer.files import FileManager
from backend.computer.windows import WindowsService
from backend.computer.computer_use import ComputerUseService


# -----------------------------------------------------------------------------
# TEST-FS-001 — Caminho absoluto C:
# -----------------------------------------------------------------------------
def test_fs_001_caminho_absoluto_c(tmp_path):
    """TEST-FS-001: Resolução direta e imediata de caminho absoluto na unidade C:."""
    test_file = tmp_path / "documento_c.txt"
    test_file.write_text("conteúdo na unidade C", encoding="utf-8")
    assert test_file.exists()

    res = UniversalPathResolver.resolve_path(str(test_file))
    assert res["success"] is True
    assert res["found"] is True
    assert res["resolution_method"] == "explicit_path"
    assert res["type"] == "file"
    assert res["name"] == "documento_c.txt"
    assert Path(res["path"]).resolve() == test_file.resolve()


# -----------------------------------------------------------------------------
# TEST-FS-002 — Caminho absoluto D:
# -----------------------------------------------------------------------------
def test_fs_002_caminho_absoluto_d():
    """TEST-FS-002: Resolução direta de caminho absoluto na unidade D:."""
    # A máquina do usuário possui a pasta D:\Arquivos\Downloads configurada e ativa
    real_downloads = Path("D:/Arquivos/Downloads")
    if real_downloads.exists():
        res = UniversalPathResolver.resolve_path(str(real_downloads))
        assert res["success"] is True
        assert res["found"] is True
        assert res["resolution_method"] == "explicit_path"
        assert res["type"] == "directory"
        assert "D:" in res["path"].upper()
    else:
        # Fallback de teste se unidade D: for simulada
        d_path = "D:\\pasta_teste\\arquivo.pdf"
        res = UniversalPathResolver.resolve_path(d_path)
        assert res["resolution_method"] == "explicit_path"
        assert res["found"] is False
        assert res["reason"] == "path_not_found"


# -----------------------------------------------------------------------------
# TEST-FS-003 — Caminho absoluto E:
# -----------------------------------------------------------------------------
def test_fs_003_caminho_absoluto_e():
    """TEST-FS-003: Resolução direta de caminho absoluto na unidade E: (workspace KON)."""
    readme = Path("E:/KON/README.md")
    assert readme.exists(), "README.md do KON deve existir no drive E:"

    res = UniversalPathResolver.resolve_path(str(readme))
    assert res["success"] is True
    assert res["found"] is True
    assert res["resolution_method"] == "explicit_path"
    assert res["type"] == "file"
    assert res["name"] == "README.md"
    assert res["extension"] == ".md"
    assert Path(res["path"]).resolve() == readme.resolve()


# -----------------------------------------------------------------------------
# TEST-FS-004 — Caminho relativo
# -----------------------------------------------------------------------------
def test_fs_004_caminho_relativo(tmp_path):
    """TEST-FS-004: Resolução de caminho relativo com subpastas."""
    sub = tmp_path / "SubPasta"
    sub.mkdir(parents=True, exist_ok=True)
    f = sub / "relatorio_relativo.pdf"
    f.write_text("pdf relativo", encoding="utf-8")

    # Resolução relativa em relação a raízes
    rel_str = f"SubPasta\\relatorio_relativo.pdf"
    res = UniversalPathResolver.resolve_path(rel_str, search_roots=[tmp_path])
    assert res["found"] is True
    assert res["name"] == "relatorio_relativo.pdf"
    assert Path(res["path"]).resolve() == f.resolve()


# -----------------------------------------------------------------------------
# TEST-FS-005 — Pasta conhecida movida para outro disco
# -----------------------------------------------------------------------------
def test_fs_005_pasta_conhecida_movida():
    """TEST-FS-005: Resolução de 'Downloads' apontando para a localização real configurada no Windows."""
    kf = WindowsKnownFolders.get_known_folders()
    downloads_real = kf.get("downloads")
    assert downloads_real is not None
    assert downloads_real.exists()

    # O usuário tem Downloads em D:\Arquivos\Downloads
    assert str(downloads_real).startswith("D:") or downloads_real.exists()

    # Resolver através de string natural "Downloads"
    res = UniversalPathResolver.resolve_path("Downloads")
    assert res["success"] is True
    assert res["found"] is True
    assert res["resolution_method"] == "windows_known_folder"
    assert Path(res["path"]).resolve() == downloads_real.resolve()

    # Resolver através de "minha pasta downloads"
    res_speech = UniversalPathResolver.resolve_path("minha pasta downloads")
    assert res_speech["success"] is True
    assert res_speech["found"] is True
    assert res_speech["resolution_method"] == "windows_known_folder"
    assert Path(res_speech["path"]).resolve() == downloads_real.resolve()


# -----------------------------------------------------------------------------
# TEST-FS-006 — Arquivo com espaço no nome
# -----------------------------------------------------------------------------
def test_fs_006_arquivo_com_espaco(tmp_path):
    """TEST-FS-006: Arquivo com múltiplos espaços no nome e no diretório."""
    folder = tmp_path / "Pasta com Varios Espacos"
    folder.mkdir(parents=True, exist_ok=True)
    f = folder / "meu relatorio final de 2026.docx"
    f.write_text("conteudo docx", encoding="utf-8")

    # Com aspas
    quoted = f'"{f}"'
    res_quoted = UniversalPathResolver.resolve_path(quoted)
    assert res_quoted["found"] is True
    assert res_quoted["name"] == "meu relatorio final de 2026.docx"

    # Sem aspas direto
    res_direct = UniversalPathResolver.resolve_path(str(f))
    assert res_direct["found"] is True
    assert res_direct["name"] == "meu relatorio final de 2026.docx"


# -----------------------------------------------------------------------------
# TEST-FS-007 — Arquivo com acentos
# -----------------------------------------------------------------------------
def test_fs_007_arquivo_com_acentos(tmp_path):
    """TEST-FS-007: Arquivo com acentos e caracteres especiais Unicode."""
    f = tmp_path / "apresentação de matemática e ciências.pdf"
    f.write_text("conteúdo com acentuação", encoding="utf-8")

    # Busca com acentos exatos
    res1 = UniversalPathResolver.resolve_path(str(f))
    assert res1["found"] is True
    assert res1["name"] == "apresentação de matemática e ciências.pdf"

    # Busca por nome sem acento (tolerância fonética/STT)
    res2 = SmartPathSearcher.search_candidates("apresentacao de matematica e ciencias", roots=[tmp_path])
    assert len(res2) >= 1
    assert res2[0]["name"] == "apresentação de matemática e ciências.pdf"


# -----------------------------------------------------------------------------
# TEST-FS-008 — Arquivo com nome longo
# -----------------------------------------------------------------------------
def test_fs_008_arquivo_com_nome_longo(tmp_path):
    """TEST-FS-008: Arquivo com nome extremamente longo (> 120 caracteres)."""
    long_name = "projeto_academico_super_detalhado_com_especificacoes_tecnicas_completas_versao_final_revisada_2026_para_aprovacao_definitiva.pdf"
    f = tmp_path / long_name
    f.write_text("conteudo longo", encoding="utf-8")

    res = UniversalPathResolver.resolve_path(str(f))
    assert res["found"] is True
    assert res["name"] == long_name
    assert res["extension"] == ".pdf"


# -----------------------------------------------------------------------------
# TEST-FS-009 — Arquivo inexistente
# -----------------------------------------------------------------------------
def test_fs_009_arquivo_inexistente():
    """TEST-FS-009: Arquivo explícito inexistente retorna imediatamente sem busca cega."""
    inexistente = "C:\\pasta_inexistente_kon_12345\\arquivo_fantasma.pdf"
    res = UniversalPathResolver.resolve_path(inexistente)
    assert res["found"] is False
    assert res["reason"] == "path_not_found"
    assert res["resolution_method"] == "explicit_path"
    assert "não existe" in res["message"].lower()


# -----------------------------------------------------------------------------
# TEST-FS-010 — Pasta inexistente
# -----------------------------------------------------------------------------
def test_fs_010_pasta_inexistente():
    """TEST-FS-010: Tentativa de abrir pasta inexistente retorna erro estruturado preciso."""
    res = FileSystemService.open_folder(folder="C:\\diretorio_inexistente_xyz_98765")
    assert res["found"] is False
    assert res["success"] is False
    assert res["error"] == "FOLDER_NOT_FOUND"
    assert "não foi encontrada" in res["message"].lower()


# -----------------------------------------------------------------------------
# TEST-FS-011 — Dois arquivos com mesmo nome (Desambiguação)
# -----------------------------------------------------------------------------
def test_fs_011_dois_arquivos_mesmo_nome_desambiguacao(tmp_path):
    """TEST-FS-011: Dois arquivos com o mesmo nome em locais diferentes exigem desambiguação."""
    pasta_a = tmp_path / "Trabalhos"
    pasta_b = tmp_path / "Backup"
    pasta_a.mkdir(parents=True, exist_ok=True)
    pasta_b.mkdir(parents=True, exist_ok=True)

    file_a = pasta_a / "trabalho.pdf"
    file_b = pasta_b / "trabalho.pdf"
    file_a.write_text("trabalho original", encoding="utf-8")
    file_b.write_text("trabalho backup", encoding="utf-8")

    # Resolução por nome simples que está presente em duas pastas com mesmo score
    res = UniversalPathResolver.resolve_path("trabalho.pdf", search_roots=[pasta_a, pasta_b])
    assert res["found"] is True
    assert res["disambiguation_required"] is True
    assert len(res["candidates"]) >= 2
    candidate_parents = [c["parent"] for c in res["candidates"]]
    assert str(pasta_a) in candidate_parents
    assert str(pasta_b) in candidate_parents
    assert "qual você quer" in res["message"].lower()


# -----------------------------------------------------------------------------
# TEST-FS-012 — Nome parcial
# -----------------------------------------------------------------------------
def test_fs_012_nome_parcial(tmp_path):
    """TEST-FS-012: Busca por termo parcial encontra o arquivo correspondente."""
    f = tmp_path / "projeto_final_graduacao_2026.pdf"
    f.write_text("projeto completo", encoding="utf-8")

    candidates = SmartPathSearcher.search_candidates("projeto final graduacao", roots=[tmp_path])
    assert len(candidates) >= 1
    assert candidates[0]["name"] == "projeto_final_graduacao_2026.pdf"


# -----------------------------------------------------------------------------
# TEST-FS-013 — Diferença de maiúsculas/minúsculas
# -----------------------------------------------------------------------------
def test_fs_013_diferenca_maiusculas_minusculas(tmp_path):
    """TEST-FS-013: Insensibilidade a maiúsculas/minúsculas."""
    f = tmp_path / "DOCUMENTO_CONFIDENCIAL.TXT"
    f.write_text("confidencial", encoding="utf-8")

    # Busca em minúsculas
    res_lower = UniversalPathResolver.resolve_path(str(tmp_path / "documento_confidencial.txt"))
    assert res_lower["found"] is True
    assert res_lower["name"] == "DOCUMENTO_CONFIDENCIAL.TXT"

    # Busca com casing misto
    res_mixed = UniversalPathResolver.resolve_path(str(tmp_path / "DoCuMeNtO_CoNfIdEnCiAl.TxT"))
    assert res_mixed["found"] is True


# -----------------------------------------------------------------------------
# TEST-FS-014 — Pequena diferença de reconhecimento de voz / typo
# -----------------------------------------------------------------------------
def test_fs_014_diferenca_reconhecimento_voz(tmp_path):
    """TEST-FS-014: Tolerância a pequenas diferenças de voz (STT) ou digitação."""
    f = tmp_path / "trabalho_de_matematica.pdf"
    f.write_text("matematica", encoding="utf-8")

    # Usuário falou "trabalho matematica" ou com typo "trabalho de matemátca"
    candidates = SmartPathSearcher.search_candidates("trabalho matematica", roots=[tmp_path])
    assert len(candidates) >= 1
    assert candidates[0]["name"] == "trabalho_de_matematica.pdf"


# -----------------------------------------------------------------------------
# TEST-FS-015 — Arquivo em unidade diferente de C:
# -----------------------------------------------------------------------------
def test_fs_015_arquivo_em_unidade_diferente_de_c():
    """TEST-FS-015: Descoberta dinâmica de unidades (C:, D:, E:) e verificação de acessibilidade."""
    drives = DriveManager.get_available_drives()
    drive_letters = [d["drive"][0].upper() for d in drives if d.get("accessible")]

    # O sistema atual possui unidades C, D e E
    assert "C" in drive_letters
    assert "D" in drive_letters or "E" in drive_letters

    for d in drives:
        assert "drive" in d
        assert "filesystem" in d
        assert "accessible" in d


# -----------------------------------------------------------------------------
# TEST-FS-016 — Arquivo dentro de subdiretórios profundos
# -----------------------------------------------------------------------------
def test_fs_016_arquivo_subdiretorios_profundos(tmp_path):
    """TEST-FS-016: Localização de arquivo em subdiretórios profundos."""
    deep_dir = tmp_path / "nivel1" / "nivel2" / "nivel3"
    deep_dir.mkdir(parents=True, exist_ok=True)
    target = deep_dir / "tesouro_escondido.docx"
    target.write_text("achou!", encoding="utf-8")

    candidates = SmartPathSearcher.search_candidates("tesouro escondido", roots=[tmp_path], max_depth=5)
    assert len(candidates) >= 1
    assert candidates[0]["name"] == "tesouro_escondido.docx"
    assert Path(candidates[0]["path"]).resolve() == target.resolve()


# -----------------------------------------------------------------------------
# TEST-FS-017 — Abrir arquivo utilizando aplicativo padrão
# -----------------------------------------------------------------------------
def test_fs_017_abrir_arquivo_aplicativo_padrao(tmp_path, monkeypatch):
    """TEST-FS-017: FileSystemService.open_file valida existência, segurança e invoca os.startfile."""
    f = tmp_path / "planilha_orcamento.xlsx"
    f.write_text("dados", encoding="utf-8")

    started_paths = []
    monkeypatch.setattr(os, "startfile", lambda p: started_paths.append(str(p)))

    res = FileSystemService.open_file(str(f))
    assert res["success"] is True
    assert res["found"] is True
    assert res["type"] == "file"
    assert res["extension"] == ".xlsx"
    assert len(started_paths) == 1
    assert Path(started_paths[0]).resolve() == f.resolve()


# -----------------------------------------------------------------------------
# TEST-FS-018 — Abrir pasta pelo caminho exato
# -----------------------------------------------------------------------------
def test_fs_018_abrir_pasta_caminho_exato(tmp_path, monkeypatch):
    """TEST-FS-018: FileSystemService.open_folder abre exatamente a pasta resolvida."""
    pasta = tmp_path / "MinhaPastaExata"
    pasta.mkdir(parents=True, exist_ok=True)

    started_folders = []
    monkeypatch.setattr(os, "startfile", lambda p: started_folders.append(str(p)))

    res = FileSystemService.open_folder(folder=str(pasta))
    assert res["success"] is True
    assert res["found"] is True
    assert res["type"] == "directory"
    assert len(started_folders) == 1
    assert Path(started_folders[0]).resolve() == pasta.resolve()


# -----------------------------------------------------------------------------
# TEST-FS-019 — Resolver alias para localização real
# -----------------------------------------------------------------------------
def test_fs_019_resolver_alias_localizacao_real(tmp_path):
    """TEST-FS-019: Aliases do usuário ou memória do KON resolvem para a pasta real."""
    target_dir = tmp_path / "ProjetosSecretos"
    target_dir.mkdir(parents=True, exist_ok=True)

    # Registra alias
    alias_name = "minha pasta de projetos secretos"
    ok = PathAliasRegistry.set_alias(alias_name, target_dir)
    assert ok is True

    # Resolução via UniversalPathResolver
    res = UniversalPathResolver.resolve_path(alias_name)
    assert res["success"] is True
    assert res["found"] is True
    assert res["resolution_method"] == "alias"
    assert Path(res["path"]).resolve() == target_dir.resolve()


# -----------------------------------------------------------------------------
# TEST-FS-020 — Fallback para Computer Use
# -----------------------------------------------------------------------------
def test_fs_020_fallback_computer_use(tmp_path, monkeypatch):
    """TEST-FS-020: Fallback para Computer Use recebe o caminho real e aciona observação visual."""
    opened_folders = []
    monkeypatch.setattr(FileSystemService, "open_folder", lambda folder: opened_folders.append(str(folder)))
    monkeypatch.setattr(ComputerUseService, "hotkey", lambda keys: None)
    monkeypatch.setattr(ComputerUseService, "type_text", lambda text: None)
    monkeypatch.setattr(ComputerUseService, "press_key", lambda key: None)
    monkeypatch.setattr(ComputerUseService, "get_active_window", lambda: {"title": "Explorador de Arquivos"})

    from backend.computer.screen import ScreenService
    monkeypatch.setattr(ScreenService, "take_screenshot", lambda: {"path": "logs/screen.png"})

    # Busca híbrida por arquivo inexistente no disco dispara fallback do Explorer no diretório real
    res = ComputerUseService.hybrid_find_file("arquivo_que_nao_existe_no_disco_123.pdf")
    assert res["discovery_mode"] == "explorer_gui"
    assert len(opened_folders) >= 1
    # Garante que abriu um caminho real configurado (ex: D:\Arquivos\Downloads) e não uma string genérica
    assert Path(opened_folders[0]).exists()
