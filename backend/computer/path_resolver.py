"""
Universal Windows File and Path Resolution Layer for KON Assistant.
Provides robust, multi-drive, Windows Known Folders (Win32 & Registry), Unicode-normalized,
and disambiguating path resolution across the entire operating system.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import difflib
import json
import os
import platform
import re
import sys
import time
import unicodedata
import uuid
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple, Set, Union

import psutil

from backend.core.logger import kon_logger
from backend.security.file_policy import is_sensitive_file


# =============================================================================
# 1. WINDOWS KNOWN FOLDERS API & REGISTRY DISCOVERY
# =============================================================================

# Standard Windows Shell KNOWNFOLDERIDs
FOLDERID_GUIDS = {
    "downloads": uuid.UUID("{374DE290-123F-4565-9164-39C4925E467B}"),
    "downloads_legacy": uuid.UUID("{7D83EE9B-2244-4E70-B1F5-5393042AF1E4}"),
    "documents": uuid.UUID("{FDD39AD0-238F-46AF-ADB4-6C85480369C7}"),
    "desktop": uuid.UUID("{B4BFCC3A-DB2C-424C-B029-7FE99A87C641}"),
    "pictures": uuid.UUID("{33E28130-4E1E-4676-835A-98395C3BC3BB}"),
    "videos": uuid.UUID("{1898EB46-2A43-4556-A228-1EA42E465226}"),
    "music": uuid.UUID("{4BD8D570-50AB-49E1-BB32-C160E6473AC9}"),
    "profile": uuid.UUID("{5E6C858F-0E22-4760-9AFE-EA3317B67173}"),
    "saved_games": uuid.UUID("{4C5C32FF-BB9D-43B0-B5B4-2D72E54EAAA4}"),
}


class _Win32GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", wintypes.DWORD),
        ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD),
        ("Data4", wintypes.BYTE * 8),
    ]

    def __init__(self, u: uuid.UUID):
        super().__init__()
        self.Data1 = u.time_low
        self.Data2 = u.time_mid
        self.Data3 = u.time_hi_version
        for i, b in enumerate(u.bytes[8:]):
            self.Data4[i] = b


class WindowsKnownFolders:
    """
    Discovers the REAL user folder paths configured in Windows.
    Never relies on hardcoded 'Path.home() / Downloads' or default assumptions.
    Consults Win32 SHGetKnownFolderPath, Windows Registry User Shell Folders, and OneDrive mirrors.
    """

    _cached_folders: Optional[Dict[str, Path]] = None
    _last_refresh: float = 0.0
    _CACHE_TTL: float = 30.0  # 30 seconds TTL for fast repeated access

    # Portuguese and English natural aliases mapped to canonical known folder keys
    FOLDER_KEY_SYNONYMS: Dict[str, str] = {
        # Downloads
        "downloads": "downloads",
        "download": "downloads",
        "pasta de downloads": "downloads",
        "pasta downloads": "downloads",
        "minha pasta downloads": "downloads",
        "minha pasta de downloads": "downloads",
        "meus downloads": "downloads",
        "baixados": "downloads",
        "pasta de baixados": "downloads",
        # Documents
        "documentos": "documents",
        "documento": "documents",
        "documents": "documents",
        "document": "documents",
        "docs": "documents",
        "pasta de documentos": "documents",
        "pasta documentos": "documents",
        "meus documentos": "documents",
        "minha pasta documentos": "documents",
        "minha pasta de documentos": "documents",
        # Desktop
        "area de trabalho": "desktop",
        "área de trabalho": "desktop",
        "desktop": "desktop",
        "minha area de trabalho": "desktop",
        "minha área de trabalho": "desktop",
        "pasta area de trabalho": "desktop",
        "pasta área de trabalho": "desktop",
        "ambiente de trabalho": "desktop",
        # Pictures / Photos
        "imagens": "pictures",
        "imagem": "pictures",
        "pictures": "pictures",
        "fotos": "pictures",
        "foto": "pictures",
        "pasta de imagens": "pictures",
        "pasta imagens": "pictures",
        "pasta de fotos": "pictures",
        "pasta fotos": "pictures",
        "minhas fotos": "pictures",
        "minhas imagens": "pictures",
        # Videos
        "videos": "videos",
        "vídeos": "videos",
        "video": "videos",
        "vídeo": "videos",
        "pasta de videos": "videos",
        "pasta de vídeos": "videos",
        "pasta videos": "videos",
        "pasta vídeos": "videos",
        "meus videos": "videos",
        "meus vídeos": "videos",
        # Music
        "musicas": "music",
        "músicas": "music",
        "musica": "music",
        "música": "music",
        "music": "music",
        "pasta de musicas": "music",
        "pasta de músicas": "music",
        "pasta musicas": "music",
        "minhas musicas": "music",
        "minhas músicas": "music",
        # User Home / Profile
        "home": "profile",
        "user": "profile",
        "usuario": "profile",
        "usuário": "profile",
        "perfil": "profile",
        "pasta do usuario": "profile",
        "pasta do usuário": "profile",
        "pasta inicial": "profile",
    }

    @classmethod
    def _query_sh_known_folder(cls, folder_uuid: uuid.UUID) -> Optional[Path]:
        """Calls Win32 SHGetKnownFolderPath to resolve a Windows KNOWNFOLDERID."""
        if platform.system().lower() != "windows":
            return None
        try:
            sh_get_known_folder_path = ctypes.windll.shell32.SHGetKnownFolderPath
            sh_get_known_folder_path.argtypes = [
                ctypes.POINTER(_Win32GUID),
                wintypes.DWORD,
                wintypes.HANDLE,
                ctypes.POINTER(wintypes.LPWSTR),
            ]
            sh_get_known_folder_path.restype = ctypes.c_long

            guid_obj = _Win32GUID(folder_uuid)
            p_path = wintypes.LPWSTR()
            hr = sh_get_known_folder_path(ctypes.byref(guid_obj), 0, None, ctypes.byref(p_path))
            if hr == 0 and p_path.value:
                val = p_path.value
                ctypes.windll.ole32.CoTaskMemFree(p_path)
                resolved = Path(val)
                if resolved.exists():
                    return resolved
        except Exception as exc:
            kon_logger.debug(f"[KNOWN_FOLDERS] SHGetKnownFolderPath error for {folder_uuid}: {exc}")
        return None

    @classmethod
    def _query_registry_user_shell_folders(cls) -> Dict[str, Path]:
        """Queries HKCU User Shell Folders registry key for configured locations."""
        folders: Dict[str, Path] = {}
        if platform.system().lower() != "windows":
            return folders

        try:
            import winreg

            key_paths = [
                r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders",
                r"Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders",
            ]

            # Registry value names mapped to canonical keys
            reg_map = {
                "{374DE290-123F-4565-9164-39C4925E467B}": "downloads",
                "{7D83EE9B-2244-4E70-B1F5-5393042AF1E4}": "downloads",
                "Personal": "documents",
                "{F42EE2D3-909F-4907-8871-4C22FC0BF756}": "documents",
                "{24D89E24-2F19-4534-9DDE-6A6671FBB8FE}": "documents",
                "Desktop": "desktop",
                "My Pictures": "pictures",
                "{339719B5-8C47-4894-94C2-D8F77ADD44A6}": "pictures",
                "{0DDD015D-B06C-45D5-8C4C-F59713854639}": "pictures",
                "My Video": "videos",
                "My Music": "music",
            }

            for sub_key in key_paths:
                try:
                    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, sub_key) as key:
                        i = 0
                        while True:
                            try:
                                name, val, _ = winreg.EnumValue(key, i)
                                i += 1
                                if not val or not isinstance(val, str):
                                    continue
                                expanded = os.path.expandvars(val)
                                p = Path(expanded)
                                if name in reg_map:
                                    canon = reg_map[name]
                                    if canon not in folders and p.exists():
                                        folders[canon] = p
                            except OSError:
                                break
                except Exception:
                    pass
        except Exception as exc:
            kon_logger.debug(f"[KNOWN_FOLDERS] Erro lendo User Shell Folders no Registro: {exc}")

        return folders

    @classmethod
    def get_known_folders(cls, force_refresh: bool = False) -> Dict[str, Path]:
        """
        Discovers and returns all actual Windows Known Folders.
        Prioritizes:
        1. SHGetKnownFolderPath (Native Shell API)
        2. Windows Registry User Shell Folders
        3. User profile with OneDrive mirror detection
        """
        now = time.time()
        if not force_refresh and cls._cached_folders and (now - cls._last_refresh < cls._CACHE_TTL):
            return cls._cached_folders

        result: Dict[str, Path] = {}

        # 1. Base user home
        user_profile = os.getenv("USERPROFILE")
        home = Path(user_profile) if user_profile else Path.home()
        result["profile"] = home

        # 2. Query Windows Registry for configured paths
        reg_folders = cls._query_registry_user_shell_folders()
        result.update(reg_folders)

        # 3. Query Win32 Shell API (higher precision for redirected folders like Downloads)
        for canon, guid_val in FOLDERID_GUIDS.items():
            if canon.endswith("_legacy"):
                canon_target = canon.replace("_legacy", "")
            else:
                canon_target = canon

            p_win32 = cls._query_sh_known_folder(guid_val)
            if p_win32 and p_win32.exists():
                result[canon_target] = p_win32

        # 4. Fallback inspection for OneDrive mirrors and defaults if any wasn't resolved
        fallbacks = {
            "downloads": [home / "Downloads", Path("D:/Downloads"), Path("D:/Arquivos/Downloads")],
            "documents": [home / "OneDrive" / "Documentos", home / "OneDrive" / "Documents", home / "Documents"],
            "desktop": [home / "OneDrive" / "Área de Trabalho", home / "OneDrive" / "Desktop", home / "Desktop"],
            "pictures": [home / "OneDrive" / "Imagens", home / "OneDrive" / "Pictures", home / "Pictures"],
            "videos": [home / "Videos"],
            "music": [home / "Music"],
        }

        for key, candidates in fallbacks.items():
            if key not in result or not result[key].exists():
                for c in candidates:
                    if c.exists():
                        result[key] = c
                        break
                if key not in result:
                    result[key] = candidates[0]

        cls._cached_folders = result
        cls._last_refresh = now
        return result

    @classmethod
    def resolve_known_folder(cls, query: str) -> Optional[Path]:
        """
        Matches a natural string against known folders and returns the real path.
        Returns None if not a recognized known folder name.
        """
        if not query:
            return None

        norm = PathNormalizer.strip_accents(query.strip().lower())

        # Strip prefixes like "pasta ", "minha pasta ", "diretorio "
        for pfx in ("pasta de ", "pasta ", "minha pasta de ", "minha pasta ", "o diretorio de ", "diretorio de ", "diretorio ", "meus ", "minhas "):
            pfx_norm = PathNormalizer.strip_accents(pfx)
            if norm.startswith(pfx_norm):
                norm = norm[len(pfx_norm):].strip()

        # Check in synonyms dictionary
        syn_key = None
        for syn, canon in cls.FOLDER_KEY_SYNONYMS.items():
            if PathNormalizer.strip_accents(syn) == norm:
                syn_key = canon
                break

        if not syn_key:
            return None

        folders = cls.get_known_folders()
        resolved = folders.get(syn_key)
        if resolved and resolved.exists():
            return resolved
        return resolved


# =============================================================================
# 2. DYNAMIC DRIVE DISCOVERY & MANAGER
# =============================================================================

class DriveManager:
    """
    Dynamically discovers all available storage drives (C:, D:, E:, etc.),
    validates accessibility, queries volume labels, file system types, and space.
    Never assumes only C:, D:, or E: exist.
    """

    _cached_drives: Optional[List[Dict[str, Any]]] = None
    _last_refresh: float = 0.0
    _CACHE_TTL: float = 10.0

    @classmethod
    def get_volume_info(cls, drive_path: str) -> Tuple[str, str]:
        """Queries volume label and filesystem name using Win32 API."""
        if platform.system().lower() != "windows":
            return "", ""
        try:
            kernel32 = ctypes.windll.kernel32
            vol_name = ctypes.create_unicode_buffer(1024)
            fs_name = ctypes.create_unicode_buffer(1024)
            # Ensure path ends with backslash (e.g. "C:\\")
            canonical_root = drive_path.rstrip("/\\") + "\\"
            res = kernel32.GetVolumeInformationW(
                canonical_root,
                vol_name,
                1024,
                None,
                None,
                None,
                fs_name,
                1024,
            )
            if res:
                return vol_name.value, fs_name.value
        except Exception:
            pass
        return "", ""

    @classmethod
    def get_available_drives(cls, force_refresh: bool = False) -> List[Dict[str, Any]]:
        """
        Discovers all logical drives currently available on the machine.
        Returns detailed structured information for each drive.
        """
        now = time.time()
        if not force_refresh and cls._cached_drives is not None and (now - cls._last_refresh < cls._CACHE_TTL):
            return cls._cached_drives

        drives: List[Dict[str, Any]] = []

        try:
            partitions = psutil.disk_partitions(all=False)
            for part in partitions:
                mount = part.mountpoint
                device = part.device or mount
                # Normalize drive string to standard format: "C:\\"
                drive_str = mount.rstrip("/\\") + "\\"

                # Test accessibility and query usage
                accessible = False
                total_space = 0
                free_space = 0
                try:
                    p = Path(drive_str)
                    if p.exists():
                        usage = psutil.disk_usage(mount)
                        total_space = usage.total
                        free_space = usage.free
                        accessible = True
                except Exception:
                    accessible = False

                label, fs_type = cls.get_volume_info(drive_str)
                if not fs_type:
                    fs_type = part.fstype or "unknown"

                drives.append({
                    "drive": drive_str,
                    "device": device,
                    "label": label or "",
                    "filesystem": fs_type,
                    "total_space": total_space,
                    "free_space": free_space,
                    "accessible": accessible,
                    "opts": part.opts,
                })
        except Exception as exc:
            kon_logger.warning(f"[DRIVE_MANAGER] Erro ao listar unidades com psutil: {exc}")

        # Fallback if psutil returns nothing or on error
        if not drives and platform.system().lower() == "windows":
            for letter in "CDEFGHIJKLMNOPQRSTUVWXYZ":
                candidate = f"{letter}:\\"
                p = Path(candidate)
                try:
                    if p.exists():
                        label, fs_type = cls.get_volume_info(candidate)
                        drives.append({
                            "drive": candidate,
                            "device": candidate,
                            "label": label or "",
                            "filesystem": fs_type or "NTFS",
                            "total_space": 0,
                            "free_space": 0,
                            "accessible": True,
                            "opts": "",
                        })
                except Exception:
                    pass

        cls._cached_drives = drives
        cls._last_refresh = now
        return drives

    @classmethod
    def get_accessible_drive_roots(cls) -> List[Path]:
        """Returns Path objects for all currently accessible drives."""
        drives = cls.get_available_drives()
        roots: List[Path] = []
        for d in drives:
            if d.get("accessible"):
                try:
                    p = Path(d["drive"])
                    if p.exists():
                        roots.append(p)
                except Exception:
                    pass
        return roots


# =============================================================================
# 3. PATH NORMALIZATION & UNICODE HANDLING
# =============================================================================

class PathNormalizer:
    """
    Universal normalizer for path inputs:
    - Strips surrounding quotes ('', "", “”, ‘’, «»)
    - Trims leading/trailing whitespace
    - Normalizes slashes (/ and \\)
    - Expands environment variables (%USERPROFILE%, %APPDATA%, ~)
    - Normalizes drive letters ('c:' or 'c:\\' -> 'C:\\')
    - Handles Windows long paths (\\\\?\\)
    - Unicode NFC normalization & accent stripping for resilient matching
    """

    QUOTE_CHARS = '"\'“”‘’«»`'

    @classmethod
    def strip_quotes(cls, text: str) -> str:
        """Strips all standard and typographic quotation marks."""
        if not text:
            return ""
        s = text.strip()
        while s and s[0] in cls.QUOTE_CHARS:
            s = s[1:].strip()
        while s and s[-1] in cls.QUOTE_CHARS:
            s = s[:-1].strip()
        return s

    @classmethod
    def strip_accents(cls, text: str) -> str:
        """Removes diacritics/accents from text for flexible search (e.g. 'matemática' -> 'matematica')."""
        if not text:
            return ""
        nfkd = unicodedata.normalize("NFKD", text)
        return "".join(c for c in nfkd if not unicodedata.combining(c)).lower()

    @classmethod
    def normalize_unicode(cls, text: str) -> str:
        """Normalizes unicode to Canonical Composition (NFC)."""
        return unicodedata.normalize("NFC", text) if text else ""

    @classmethod
    def normalize_path_str(cls, raw: str) -> str:
        """
        Normalizes a raw path string into a canonical filesystem string.
        """
        if not raw:
            return ""

        # 1. Clean quotes and whitespace
        s = cls.strip_quotes(raw.strip())
        s = cls.normalize_unicode(s)

        # 2. Expand environment variables and ~
        s = os.path.expandvars(os.path.expanduser(s))

        # 3. Normalize slashes
        s = s.replace("/", "\\")

        # 4. Canonicalize bare drive letters (e.g. 'c:' -> 'C:\\', 'd' with colon)
        if re.match(r"^[A-Za-z]:$", s):
            s = f"{s.upper()}\\"
        elif re.match(r"^[A-Za-z]:\\?$", s):
            s = f"{s[:2].upper()}\\"
        elif len(s) >= 2 and s[1] == ":":
            s = f"{s[0].upper()}:{s[2:]}"

        return s

    @classmethod
    def to_long_path_if_needed(cls, path_obj: Path) -> str:
        """
        Adds the \\\\?\\ prefix for Windows paths exceeding MAX_PATH (260 characters).
        """
        path_str = str(path_obj.resolve()) if path_obj.is_absolute() else str(path_obj)
        if platform.system().lower() == "windows" and len(path_str) >= 250:
            if not path_str.startswith("\\\\?\\") and not path_str.startswith("\\\\"):
                return f"\\\\?\\{path_str}"
        return path_str


# =============================================================================
# 4. PATH ALIAS REGISTRY & KON MEMORY
# =============================================================================

class PathAliasRegistry:
    """
    Persistent registry for user-defined folder aliases and locations discovered by KON.
    Enables commands like 'minha pasta de trabalhos' -> 'D:\\Arquivos\\Trabalhos'.
    """

    _ALIAS_FILE = Path("data/folder_aliases.json")
    _aliases: Optional[Dict[str, str]] = None

    @classmethod
    def _ensure_loaded(cls) -> None:
        if cls._aliases is not None:
            return
        cls._aliases = {}
        try:
            if cls._ALIAS_FILE.exists():
                with open(cls._ALIAS_FILE, "r", encoding="utf-8") as f:
                    cls._aliases = json.load(f)
        except Exception as exc:
            kon_logger.debug(f"[ALIAS_REGISTRY] Falha ao carregar aliases: {exc}")

    @classmethod
    def _save(cls) -> None:
        try:
            cls._ALIAS_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(cls._ALIAS_FILE, "w", encoding="utf-8") as f:
                json.dump(cls._aliases or {}, f, indent=2, ensure_ascii=False)
        except Exception as exc:
            kon_logger.debug(f"[ALIAS_REGISTRY] Falha ao salvar aliases: {exc}")

    @classmethod
    def get_alias(cls, alias_name: str) -> Optional[Path]:
        """Retrieves a mapped path by alias name."""
        cls._ensure_loaded()
        clean = PathNormalizer.strip_accents(alias_name.strip().lower())
        for k, v in (cls._aliases or {}).items():
            if PathNormalizer.strip_accents(k) == clean:
                p = Path(v)
                if p.exists():
                    return p
        return None

    @classmethod
    def set_alias(cls, alias_name: str, target_path: Union[str, Path]) -> bool:
        """Sets a persistent alias to a target path."""
        cls._ensure_loaded()
        clean_name = alias_name.strip()
        p = Path(target_path)
        if not p.exists():
            return False
        if cls._aliases is None:
            cls._aliases = {}
        cls._aliases[clean_name] = str(p.resolve())
        cls._save()
        kon_logger.info(f"[ALIAS_REGISTRY] Alias registrado: '{clean_name}' -> '{p}'")
        return True

    @classmethod
    def list_aliases(cls) -> Dict[str, str]:
        cls._ensure_loaded()
        return dict(cls._aliases or {})


# =============================================================================
# 5. SMART CACHE & SEARCHER WITH VOICE RESILIENCE & DISAMBIGUATION
# =============================================================================

class PathCache:
    """
    Lightweight cache for resolved paths.
    CRITICAL RULE: The cache is NEVER more authoritative than the real filesystem.
    Always validates Path.exists() before returning a cached result.
    """

    _cache: Dict[str, Tuple[Path, float]] = {}
    _TTL: float = 60.0  # 1 minute

    @classmethod
    def get(cls, query: str) -> Optional[Path]:
        key = PathNormalizer.strip_accents(query.strip().lower())
        entry = cls._cache.get(key)
        if entry:
            p, timestamp = entry
            if time.time() - timestamp < cls._TTL:
                if p.exists():
                    return p
                else:
                    # Invalidate stale entry
                    cls._cache.pop(key, None)
        return None

    @classmethod
    def put(cls, query: str, path: Path) -> None:
        if path and path.exists():
            key = PathNormalizer.strip_accents(query.strip().lower())
            cls._cache[key] = (path, time.time())


KNOWN_FILE_EXTENSIONS: Set[str] = {
    # Documents
    "pdf", "docx", "doc", "xlsx", "xls", "pptx", "ppt", "txt", "csv", "rtf", "odt", "ods", "odp",
    # Images
    "png", "jpg", "jpeg", "gif", "bmp", "svg", "webp", "ico", "tiff", "tif",
    # Media
    "mp4", "mp3", "wav", "m4a", "flac", "avi", "mkv", "mov", "wmv", "wma", "ogg",
    # Archives
    "zip", "rar", "7z", "tar", "gz", "bz2", "xz",
    # Executables & scripts
    "exe", "msi", "bat", "cmd", "ps1", "vbs",
    # Code & data
    "py", "js", "ts", "html", "css", "json", "xml", "yaml", "yml", "md", "sql", "sh",
}


def parse_query_stem_and_ext(query_str: str, explicit_ext: Optional[str] = None) -> Tuple[str, Optional[str]]:
    """
    Carefully parses user query into filename stem and optional extension.
    Avoids erroneously treating version numbers or dot notations (e.g. '2.3', 'v1.0') as file extensions!
    """
    clean = PathNormalizer.strip_quotes(query_str.strip())
    if explicit_ext:
        clean_ext = explicit_ext.lstrip(".").lower()
        if clean.lower().endswith(f".{clean_ext}"):
            clean = clean[: -len(clean_ext) - 1].strip()
        return clean, clean_ext

    # Check if query ends with a dot followed by alphanumeric
    match = re.search(r"\.([a-zA-Z0-9]+)$", clean)
    if match:
        candidate_ext = match.group(1).lower()
        # Only treat as extension if it is in KNOWN_FILE_EXTENSIONS and not purely numeric
        if candidate_ext in KNOWN_FILE_EXTENSIONS and not candidate_ext.isdigit():
            stem_part = clean[: match.start()].strip()
            return stem_part, candidate_ext

    return clean, None


def normalize_name_for_comparison(text: str) -> str:
    """
    Normalizes text for robust name comparison:
    - Unicode NFKD (strips diacritics/accents)
    - Lowercase
    - Replaces punctuation, hyphens, underscores with single space
    - Preserves decimal numbers (e.g. '2.3')
    """
    if not text:
        return ""
    nfkd = unicodedata.normalize("NFKD", text)
    no_accents = "".join(c for c in nfkd if not unicodedata.combining(c)).lower()
    cleaned = re.sub(r"[^a-z0-9.]+", " ", no_accents)
    cleaned = re.sub(r"\.(?![0-9])", " ", cleaned)
    cleaned = re.sub(r"(?<![0-9])\.", " ", cleaned)
    return " ".join(cleaned.split())


def normalize_alpha_only(text: str) -> str:
    """Normalizes text removing all non-alphanumeric characters for word set comparison."""
    if not text:
        return ""
    nfkd = unicodedata.normalize("NFKD", text)
    no_accents = "".join(c for c in nfkd if not unicodedata.combining(c)).lower()
    cleaned = re.sub(r"[^a-z0-9]+", " ", no_accents)
    return " ".join(cleaned.split())


def score_filename_match(
    query_stem: str,
    query_ext: Optional[str],
    file_name: str,
    file_stem: str,
    file_ext: str,
) -> Tuple[float, str]:
    """
    6-stage tiered matching:
    1. Exact full name (1.00)
    2. Exact stem without extension (0.99)
    3. Normalized stem (0.98)
    4. Normalized alpha-only (0.96)
    5. Words subset / containment (0.88 - 0.90)
    6. Fuzzy SequenceMatcher (0.70 - 0.85)
    """
    if query_ext and file_ext != query_ext:
        return 0.0, "ext_mismatch"

    clean_q = query_stem.strip().lower()
    clean_fn = file_name.strip().lower()
    clean_fs = file_stem.strip().lower()

    # 1. Exact full name
    if clean_q == clean_fn:
        return 1.0, "exact_name"

    # 2. Exact stem
    if clean_q == clean_fs:
        return 0.99, "exact_stem"

    # 3. Normalized stem
    nq = normalize_name_for_comparison(query_stem)
    nfs = normalize_name_for_comparison(file_stem)
    if nq == nfs:
        return 0.98, "normalized_stem"

    # 4. Normalized alpha-only
    na_q = normalize_alpha_only(query_stem)
    na_fs = normalize_alpha_only(file_stem)
    if na_q and na_q == na_fs:
        return 0.96, "normalized_alpha"

    # 5. Words subset / containment
    words_q = set(na_q.split())
    words_fs = set(na_fs.split())
    if words_q and words_q.issubset(words_fs):
        return 0.90, "words_subset"
    if na_q and na_q in na_fs:
        return 0.88, "substring"

    # 6. Fuzzy SequenceMatcher
    ratio = difflib.SequenceMatcher(None, na_q, na_fs).ratio()
    if ratio >= 0.70:
        return 0.70 + 0.15 * ratio, "fuzzy"

    return 0.0, "no_match"


class SmartPathSearcher:
    """
    Intelligent multi-drive search engine with:
    - Unicode & accent insensitivity
    - Exact stem, normalized stem, and word-set tiered matching
    - Speech-to-text typo tolerance & fuzzy matching
    - Disambiguation detection (returns candidate options when ambiguous)
    """

    PRUNED_DIR_NAMES = {
        "node_modules", ".git", ".venv", "venv", "$recycle.bin",
        "system volume information", "appdata", "windows", "program files",
        "program files (x86)", "$windows.~bt", "recovery", "config.msi",
    }

    @classmethod
    def search_candidates(
        cls,
        query: str,
        roots: Optional[List[Path]] = None,
        extension: Optional[str] = None,
        max_results: int = 10,
        max_depth: int = 4,
    ) -> List[Dict[str, Any]]:
        """
        Searches across specified roots (or all accessible drives and user folders)
        for files or directories matching the query.
        """
        clean_query = PathNormalizer.strip_quotes(query.strip())
        if not clean_query:
            return []

        # Determine roots
        search_roots: List[Path] = []
        if roots is not None:
            # If roots was explicitly specified (even if 1 folder), limit STRICTLY to those roots!
            for r in roots:
                if r and r.exists() and r not in search_roots:
                    search_roots.append(r)
            if not search_roots:
                # Specified roots do not exist, return empty without expanding to entire computer
                return []
        else:
            # Global fallback search across user known folders and accessible drives
            kf = WindowsKnownFolders.get_known_folders()
            for key in ("downloads", "documents", "desktop", "profile"):
                p = kf.get(key)
                if p and p.exists() and p not in search_roots:
                    search_roots.append(p)

            for d in DriveManager.get_accessible_drive_roots():
                if d not in search_roots:
                    search_roots.append(d)

        # Parse query stem and target extension without corrupting decimals/versions
        target_stem, target_ext = parse_query_stem_and_ext(clean_query, explicit_ext=extension)

        candidates: List[Tuple[float, Dict[str, Any]]] = []
        visited_paths: Set[str] = set()

        for root in search_roots:
            if len(candidates) >= max_results * 2:
                break

            try:
                # Top-level scan of root folder first
                for entry in root.iterdir():
                    try:
                        resolved_entry_str = str(entry.resolve())
                        if resolved_entry_str in visited_paths or is_sensitive_file(entry):
                            continue
                        visited_paths.add(resolved_entry_str)

                        entry_stem = entry.stem
                        entry_ext = entry.suffix.lstrip(".").lower()

                        score, stage = score_filename_match(
                            target_stem,
                            target_ext if entry.is_file() else None,
                            entry.name,
                            entry_stem,
                            entry_ext,
                        )

                        if score >= 0.70:
                            info = UniversalPathResolver.format_path_info(entry, resolution_method="filesystem_search")
                            info["match_score"] = score
                            info["match_stage"] = stage
                            candidates.append((score, info))
                    except Exception:
                        continue

                # Deep subfolder walk with depth limit
                for current_dir, dirs, files in os.walk(str(root)):
                    # Prune unwanted directories in-place
                    dirs[:] = [
                        d for d in dirs
                        if not d.startswith(".")
                        and d.lower() not in cls.PRUNED_DIR_NAMES
                        and not is_sensitive_file(d)
                    ]

                    # Depth check
                    try:
                        rel = Path(current_dir).relative_to(root)
                        if len(rel.parts) > max_depth:
                            dirs[:] = []
                            continue
                    except Exception:
                        pass

                    for fname in files:
                        if is_sensitive_file(fname):
                            continue

                        fpath = Path(current_dir) / fname
                        fpath_str = str(fpath)
                        if fpath_str in visited_paths:
                            continue
                        visited_paths.add(fpath_str)

                        f_stem = Path(fname).stem
                        f_ext = Path(fname).suffix.lstrip(".").lower()

                        score, stage = score_filename_match(
                            target_stem,
                            target_ext,
                            fname,
                            f_stem,
                            f_ext,
                        )

                        if score >= 0.70:
                            info = UniversalPathResolver.format_path_info(fpath, resolution_method="filesystem_search")
                            info["match_score"] = score
                            info["match_stage"] = stage
                            candidates.append((score, info))

                            if len(candidates) >= max_results * 3:
                                break
                    if len(candidates) >= max_results * 3:
                        break

            except Exception as exc:
                kon_logger.debug(f"[SMART_SEARCH] Erro pesquisando em {root}: {exc}")

        # Sort candidates by score descending
        candidates.sort(key=lambda x: x[0], reverse=True)
        return [c[1] for c in candidates[:max_results]]


# =============================================================================
# 6. UNIVERSAL PATH RESOLVER (CENTRALIZED ORCHESTRATOR)
# =============================================================================

class UniversalPathResolver:
    """
    Centralized, robust, universal Windows Path Resolver for KON.
    Enforces the 5-priority resolution hierarchy:
    1. EXPLICIT PATH: absolute path or drive letter (Path.exists() -> return immediately, no search).
    2. RELATIVE PATH: resolved against user known folders and accessible roots.
    3. WINDOWS KNOWN FOLDERS: discovered from native Win32 API and Registry.
    4. ALIASES / MEMORY: persistent user aliases.
    5. INTELLIGENT SEARCH: multi-drive or scoped search with fuzzy matching, caching, and disambiguation.
    """

    _last_found_file: Optional[Path] = None

    @classmethod
    def get_last_found_file(cls) -> Optional[Path]:
        """Returns the most recently found file by the resolver, if still existing."""
        if cls._last_found_file and cls._last_found_file.exists():
            return cls._last_found_file
        return None

    @classmethod
    def format_path_info(
        cls,
        path_obj: Path,
        resolution_method: str = "explicit_path",
        message: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Creates the standardized structured dictionary for an existing path."""
        try:
            resolved_p = path_obj.resolve()
        except Exception:
            resolved_p = path_obj

        is_file = resolved_p.is_file()
        is_dir = resolved_p.is_dir()
        size = 0
        mod_time = ""

        try:
            st = resolved_p.stat()
            size = st.st_size if is_file else 0
            mod_time = time.ctime(st.st_mtime)
        except Exception:
            pass

        p_type = "file" if is_file else ("directory" if is_dir else "other")
        name = resolved_p.name or str(resolved_p)
        ext = resolved_p.suffix.lower() if is_file else ""

        return {
            "success": True,
            "found": True,
            "path": str(resolved_p),
            "type": p_type,
            "name": name,
            "extension": ext,
            "parent": str(resolved_p.parent) if resolved_p.parent != resolved_p else str(resolved_p),
            "size": size,
            "modified": mod_time,
            "resolution_method": resolution_method,
            "disambiguation_required": False,
            "candidates": [],
            "message": message or f"{p_type.capitalize()} '{name}' localizado com sucesso.",
        }

    @classmethod
    def resolve_path(
        cls,
        user_input: Union[str, Path, None],
        expected_type: Optional[str] = None,  # "file", "directory", or None
        allow_search: bool = True,
        search_roots: Optional[List[Union[str, Path]]] = None,
        extension: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Universal path resolution method following the 5 priorities.
        Logs transparent diagnostics:
        [FILESYSTEM] User input: ...
        [FILESYSTEM] Resolution method: ...
        [FILESYSTEM] Resolved path: ...
        [FILESYSTEM] Exists: ...
        """
        if not user_input:
            # Check if referring to last found file (e.g. user simply says "abra")
            last_file = cls.get_last_found_file()
            if last_file:
                return cls.format_path_info(last_file, resolution_method="last_found_file")
            return {
                "success": False,
                "found": False,
                "requested_input": user_input,
                "reason": "empty_input",
                "message": "Nenhum caminho ou nome de arquivo foi fornecido.",
            }

        raw_str = str(user_input).strip()
        raw_lower = raw_str.lower()

        # Check for natural referential phrases ("abra", "abra ele", "abra o arquivo")
        if raw_lower in ("abra", "abra ele", "abra ela", "abra o arquivo", "abrir", "abrir arquivo", "executar", "execute"):
            last_file = cls.get_last_found_file()
            if last_file:
                kon_logger.info(f"[FILESYSTEM] User input: \"{raw_str}\" -> Referência ao último arquivo localizado: {last_file}")
                return cls.format_path_info(last_file, resolution_method="last_found_file")

        kon_logger.info(f"[FILESYSTEM] User input: \"{raw_str}\"")

        # -------------------------------------------------------------
        # PRIORITY 1 — EXPLICIT PATH
        # -------------------------------------------------------------
        norm_str = PathNormalizer.normalize_path_str(raw_str)
        is_explicit_drive = bool(re.match(r"^[A-Za-z]:", norm_str))
        is_unc = norm_str.startswith("\\\\")
        has_slashes = "\\" in norm_str or "/" in norm_str

        if is_explicit_drive or is_unc or (has_slashes and (Path(norm_str).is_absolute() or Path(norm_str).exists())):
            try:
                candidate_path = Path(norm_str)
                if candidate_path.exists():
                    kon_logger.info(f"[FILESYSTEM] Resolution method: explicit_path")
                    kon_logger.info(f"[FILESYSTEM] Resolved path: {candidate_path}")
                    kon_logger.info(f"[FILESYSTEM] Exists: True")
                    res = cls.format_path_info(candidate_path, resolution_method="explicit_path")
                    PathCache.put(raw_str, candidate_path)
                    if candidate_path.is_file():
                        cls._last_found_file = candidate_path
                    return res
                elif candidate_path.is_absolute():
                    # If an explicit absolute path was given but does NOT exist: RETURN IMMEDIATELY.
                    kon_logger.info(f"[FILESYSTEM] Resolution method: explicit_path")
                    kon_logger.info(f"[FILESYSTEM] Resolved path: {candidate_path}")
                    kon_logger.info(f"[FILESYSTEM] Exists: False")
                    return {
                        "success": True,
                        "found": False,
                        "requested_input": raw_str,
                        "normalized_path": str(candidate_path),
                        "reason": "path_not_found",
                        "resolution_method": "explicit_path",
                        "searched_roots": [str(candidate_path.parent)],
                        "message": f"O caminho exato '{candidate_path}' não existe no computador.",
                    }
            except Exception as exc:
                kon_logger.debug(f"[FILESYSTEM] Erro ao testar caminho explícito '{norm_str}': {exc}")

        # -------------------------------------------------------------
        # PRIORITY 2 — RELATIVE PATH (resolved against known locations & roots)
        # -------------------------------------------------------------
        if has_slashes and not Path(norm_str).is_absolute():
            kf = WindowsKnownFolders.get_known_folders()
            check_bases = [
                kf.get("downloads"),
                kf.get("documents"),
                kf.get("desktop"),
                kf.get("profile"),
                Path.cwd(),
            ]
            for drive_root in DriveManager.get_accessible_drive_roots():
                if drive_root not in check_bases:
                    check_bases.append(drive_root)

            for base in check_bases:
                if not base:
                    continue
                try:
                    rel_candidate = (base / norm_str).resolve()
                    if rel_candidate.exists():
                        kon_logger.info(f"[FILESYSTEM] Resolution method: relative_path")
                        kon_logger.info(f"[FILESYSTEM] Resolved path: {rel_candidate}")
                        kon_logger.info(f"[FILESYSTEM] Exists: True")
                        res = cls.format_path_info(rel_candidate, resolution_method="relative_path")
                        PathCache.put(raw_str, rel_candidate)
                        if rel_candidate.is_file():
                            cls._last_found_file = rel_candidate
                        return res
                except Exception:
                    continue

        # -------------------------------------------------------------
        # PRIORITY 3 — WINDOWS KNOWN FOLDERS
        # -------------------------------------------------------------
        known_folder_res = WindowsKnownFolders.resolve_known_folder(raw_str)
        if known_folder_res and known_folder_res.exists():
            kon_logger.info(f"[FILESYSTEM] Resolution method: windows_known_folder")
            kon_logger.info(f"[FILESYSTEM] Resolved path: {known_folder_res}")
            kon_logger.info(f"[FILESYSTEM] Exists: True")
            res = cls.format_path_info(known_folder_res, resolution_method="windows_known_folder")
            PathCache.put(raw_str, known_folder_res)
            return res

        # -------------------------------------------------------------
        # PRIORITY 4 — ALIASES / MEMORY OF KON
        # -------------------------------------------------------------
        alias_res = PathAliasRegistry.get_alias(raw_str)
        if alias_res and alias_res.exists():
            kon_logger.info(f"[FILESYSTEM] Resolution method: alias")
            kon_logger.info(f"[FILESYSTEM] Resolved path: {alias_res}")
            kon_logger.info(f"[FILESYSTEM] Exists: True")
            res = cls.format_path_info(alias_res, resolution_method="alias")
            return res

        # Check Cache before performing search (only if no explicit roots filter)
        if not search_roots:
            cached_hit = PathCache.get(raw_str)
            if cached_hit and cached_hit.exists():
                kon_logger.info(f"[FILESYSTEM] Resolution method: indexed_search")
                kon_logger.info(f"[FILESYSTEM] Resolved path: {cached_hit}")
                kon_logger.info(f"[FILESYSTEM] Exists: True")
                if cached_hit.is_file():
                    cls._last_found_file = cached_hit
                return cls.format_path_info(cached_hit, resolution_method="indexed_search")

        # -------------------------------------------------------------
        # PRIORITY 5 — INTELLIGENT SEARCH (multi-drive, scoped, fuzzy, disambiguation)
        # -------------------------------------------------------------
        if not allow_search:
            return {
                "success": True,
                "found": False,
                "requested_input": raw_str,
                "reason": "search_disabled",
                "message": f"Não foi possível determinar a localização de '{raw_str}'.",
            }

        custom_roots: List[Path] = []
        invalid_root_requested: Optional[str] = None

        if search_roots:
            for item in search_roots:
                r_str = str(item).strip()
                # 1. Resolve known folder alias (e.g. "Downloads" -> D:\Arquivos\Downloads)
                p_resolved = WindowsKnownFolders.resolve_known_folder(r_str)
                if not p_resolved:
                    # 2. Resolve alias from registry
                    p_resolved = PathAliasRegistry.get_alias(r_str)
                if not p_resolved:
                    # 3. Resolve explicit/normalized path
                    norm_r = PathNormalizer.normalize_path_str(r_str)
                    if norm_r:
                        try:
                            p_cand = Path(norm_r)
                            if p_cand.exists():
                                p_resolved = p_cand
                        except Exception:
                            pass

                if p_resolved and p_resolved.exists() and p_resolved.is_dir():
                    if p_resolved not in custom_roots:
                        custom_roots.append(p_resolved)
                else:
                    invalid_root_requested = r_str

            # CRITICAL RULE: If a root was explicitly specified but does not exist,
            # fail immediately with clear error. NEVER expand to entire computer!
            if invalid_root_requested and not custom_roots:
                kon_logger.warning(f"[FILESYSTEM] Pasta raiz solicitada não existe: '{invalid_root_requested}'")
                return {
                    "success": False,
                    "found": False,
                    "requested_input": raw_str,
                    "root_requested": invalid_root_requested,
                    "reason": "root_not_found",
                    "results": [],
                    "count": 0,
                    "message": f"A pasta raiz solicitada '{invalid_root_requested}' não foi encontrada no computador.",
                }

        # Logging search scope
        if custom_roots:
            searched_roots_strs = [str(r) for r in custom_roots]
            scope_str = ", ".join(searched_roots_strs)
            kon_logger.info(f"[FILESYSTEM] Query: {raw_str}")
            kon_logger.info(f"[FILESYSTEM] Root requested: {search_roots[0] if search_roots else 'None'}")
            kon_logger.info(f"[FILESYSTEM] Root resolved: {scope_str}")
            kon_logger.info(f"[FILESYSTEM] Search scope: {scope_str}")
        else:
            drives = DriveManager.get_available_drives()
            accessible_drives_strs = [d["drive"] for d in drives if d.get("accessible")]
            searched_roots_strs = accessible_drives_strs
            kon_logger.info(f"[FILESYSTEM] Query: {raw_str}")
            kon_logger.info(f"[FILESYSTEM] Root requested: None")
            kon_logger.info(f"[FILESYSTEM] Search scope: user folders and accessible drives: {accessible_drives_strs}")

        candidates = SmartPathSearcher.search_candidates(
            query=raw_str,
            roots=custom_roots if custom_roots else None,
            extension=extension,
            max_results=5,
        )

        # Filter by expected type if specified
        if expected_type:
            candidates = [c for c in candidates if c.get("type") == expected_type]

        if not candidates:
            has_exact = False
            has_norm = False
            kon_logger.info(f"[FILESYSTEM] Exact filename match: {has_exact}")
            kon_logger.info(f"[FILESYSTEM] Normalized match: {has_norm}")
            if custom_roots:
                msg = f"Não encontrei '{raw_str}' dentro da pasta solicitada '{search_roots[0]}' ({custom_roots[0]})."
            else:
                msg = (
                    f"Não encontrei '{raw_str}'. "
                    f"Procurei nas pastas do usuário e nas unidades acessíveis: {', '.join(searched_roots_strs)}."
                )
            kon_logger.info(f"[FILESYSTEM] Busca não retornou resultados: {msg}")
            return {
                "success": True,
                "found": False,
                "requested_input": raw_str,
                "reason": "path_not_found",
                "resolution_method": "filesystem_search",
                "searched_roots": searched_roots_strs,
                "results": [],
                "count": 0,
                "message": msg,
            }

        # Check for Disambiguation (multiple matches with very close high scores)
        if len(candidates) >= 2:
            top_score = candidates[0].get("match_score", 0.0)
            second_score = candidates[1].get("match_score", 0.0)

            # Check if top two have exact same name in different directories
            name1 = PathNormalizer.strip_accents(candidates[0]["name"])
            name2 = PathNormalizer.strip_accents(candidates[1]["name"])
            same_name = (name1 == name2)

            # Only disambiguate if top match is NOT a distinct winner
            if same_name or (top_score >= 0.85 and (top_score - second_score) < 0.05):
                loc1 = candidates[0]["parent"]
                loc2 = candidates[1]["parent"]
                cand_name = candidates[0]["name"]
                disambig_msg = (
                    f"Encontrei dois ou mais arquivos chamados '{cand_name}'. "
                    f"Um está em '{loc1}' e outro em '{loc2}'. Qual você quer?"
                )
                kon_logger.info(f"[FILESYSTEM] Desambiguação necessária: {disambig_msg}")
                return {
                    "success": True,
                    "found": True,
                    "disambiguation_required": True,
                    "candidates": candidates,
                    "count": len(candidates),
                    "resolution_method": "filesystem_search",
                    "message": disambig_msg,
                }

        # Clear distinct top match!
        top_match = candidates[0]
        resolved_path = Path(top_match["path"])
        PathCache.put(raw_str, resolved_path)
        if resolved_path.is_file():
            cls._last_found_file = resolved_path

        has_exact = top_match.get("match_stage") in ("exact_name", "exact_stem")
        has_norm = top_match.get("match_stage") in ("normalized_stem", "normalized_alpha")
        kon_logger.info(f"[FILESYSTEM] Exact filename match: {has_exact}")
        kon_logger.info(f"[FILESYSTEM] Normalized match: {has_norm}")
        kon_logger.info(f"[FILESYSTEM] Found: {resolved_path}")
        kon_logger.info(f"[FILESYSTEM] Resolution method: filesystem_search")
        kon_logger.info(f"[FILESYSTEM] Resolved path: {resolved_path}")
        kon_logger.info(f"[FILESYSTEM] Exists: True")

        top_match["results"] = candidates
        top_match["count"] = len(candidates)
        top_match["searched_roots"] = searched_roots_strs
        return top_match
