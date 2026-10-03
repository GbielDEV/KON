"""
Local persistent memory storage using SQLite.
Stores user preferences, folder aliases, command history, and simple memory items.
"""
import sqlite3
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
from backend.core.config import get_settings
from backend.core.logger import kon_logger


class MemoryManager:
    """
    Manages SQLite storage in data/kon.db.
    """
    def __init__(self, db_path: Optional[Path] = None) -> None:
        self.db_path = db_path or get_settings().db_path
        self._init_database()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_database(self) -> None:
        """
        Creates tables if they do not exist.
        """
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                # Settings table
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS settings (
                        key TEXT PRIMARY KEY,
                        value TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    )
                """)

                # Folder aliases table
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS folder_aliases (
                        alias TEXT PRIMARY KEY,
                        path TEXT NOT NULL,
                        created_at TEXT NOT NULL
                    )
                """)

                # Command history table
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS command_history (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        command TEXT NOT NULL,
                        state_at_execution TEXT NOT NULL,
                        status TEXT NOT NULL,
                        response TEXT,
                        created_at TEXT NOT NULL
                    )
                """)

                # User memories table (key-value facts)
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS memories (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        key TEXT UNIQUE NOT NULL,
                        value TEXT NOT NULL,
                        created_at TEXT NOT NULL
                    )
                """)

                # Permission memory table (remembered user approval decisions, adapted from OpenJarvis)
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS permission_memory (
                        action_key TEXT NOT NULL,
                        scope TEXT NOT NULL DEFAULT '',
                        decision TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        PRIMARY KEY (action_key, scope)
                    )
                """)
                # Safe schema migration for pre-existing databases without scope column
                cursor.execute("PRAGMA table_info(permission_memory)")
                existing_cols = [c[1] for c in cursor.fetchall()]
                if "scope" not in existing_cols:
                    try:
                        cursor.execute("ALTER TABLE permission_memory ADD COLUMN scope TEXT NOT NULL DEFAULT ''")
                    except Exception:
                        pass
                conn.commit()
            kon_logger.debug(f"Banco de dados SQLite inicializado em {self.db_path}")
        except Exception as err:
            kon_logger.error(f"Erro ao inicializar banco de dados SQLite: {err}")

    def log_command(self, command: str, state: str, status: str, response: Optional[str] = None) -> None:
        """
        Records a command in the command history.
        """
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO command_history (command, state_at_execution, status, response, created_at)
                    VALUES (?, ?, ?, ?, ?)
                """, (
                    command,
                    state,
                    status,
                    response,
                    datetime.now(timezone.utc).isoformat()
                ))
                conn.commit()
        except Exception as err:
            kon_logger.error(f"Erro ao salvar comando no histórico: {err}")

    def get_recent_history(self, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Returns recent command executions.
        """
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT id, command, state_at_execution, status, response, created_at
                    FROM command_history
                    ORDER BY id DESC
                    LIMIT ?
                """, (limit,))
                rows = cursor.fetchall()
                return [dict(r) for r in rows]
        except Exception as err:
            kon_logger.error(f"Erro ao buscar histórico: {err}")
            return []

    CRITICAL_TOOLS = frozenset({
        "delete_file",
        "shutdown_system",
        "restart_system",
        "critical_action",
    })

    def remember_permission(self, action_key: str, decision: str, scope: Optional[str] = None) -> None:
        """
        Persists a user permission decision ('always_approve', 'always_deny', 'ask').
        Adapted from OpenJarvis approval_store pattern with strict scoping:
        - CRITICAL actions can NEVER be memorized.
        - 'always_approve' for CONFIRM actions accepts a scope (root directory or path pattern).
        """
        if action_key in self.CRITICAL_TOOLS:
            kon_logger.warning(f"[SECURITY] Ações de nível CRITICAL ('{action_key}') NUNCA podem ser memorizadas.")
            return

        norm_scope = ""
        if scope:
            try:
                norm_scope = str(Path(scope).resolve()).lower().strip()
            except Exception:
                norm_scope = str(scope).lower().strip()

        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO permission_memory (action_key, scope, decision, updated_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(action_key, scope) DO UPDATE SET
                        decision = excluded.decision,
                        updated_at = excluded.updated_at
                """, (action_key, norm_scope, decision, datetime.now(timezone.utc).isoformat()))
                conn.commit()
            kon_logger.info(f"[SECURITY] Permissão lembrada para '{action_key}' (escopo: '{norm_scope}'): {decision}")
        except Exception as err:
            kon_logger.error(f"Erro ao salvar memória de permissão: {err}")

    def get_remembered_permission(self, action_key: str, target_path: Optional[str] = None) -> Optional[str]:
        """
        Retrieves a remembered permission decision if it exists.
        Enforces scoped permission checking:
        - CRITICAL actions always return None (never remembered).
        - If target_path is specified:
            Matches records where target_path is under record scope.
            Legacy records without scope (scope == '' or None) are treated as NOT approved (safe migration).
        - If target_path is None:
            Returns decision for unscoped record (if exists) or matches. Note: for CONFIRM file actions,
            unscoped 'always_approve' is not considered authorized without scope.
        """
        if action_key in self.CRITICAL_TOOLS:
            return None

        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT scope, decision FROM permission_memory WHERE action_key = ?
                """, (action_key,))
                rows = cursor.fetchall()
                if not rows:
                    return None

                if target_path is not None:
                    try:
                        norm_target = Path(target_path).resolve()
                    except Exception:
                        norm_target = Path(target_path)

                    for r in rows:
                        rec_scope = (r["scope"] or "").strip()
                        decision = r["decision"]
                        # Safe migration: records without scope are ignored / not approved for always_approve
                        if not rec_scope:
                            continue
                        try:
                            scope_path = Path(rec_scope).resolve()
                            if norm_target == scope_path or norm_target.is_relative_to(scope_path):
                                return decision
                        except Exception:
                            if norm_target.as_posix().lower().startswith(Path(rec_scope).as_posix().lower()):
                                return decision
                    # If target_path was provided but did not fall inside any registered scope:
                    return None

                # When target_path is not provided (e.g. non-filesystem tools or legacy tests)
                return rows[0]["decision"]
        except Exception as err:
            kon_logger.error(f"Erro ao recuperar memória de permissão: {err}")
            return None

    def clear_permission(self, action_key: str, scope: Optional[str] = None) -> None:
        """Clears a remembered permission decision."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                if scope is not None:
                    norm_scope = str(Path(scope).resolve()).lower().strip()
                    cursor.execute("DELETE FROM permission_memory WHERE action_key = ? AND scope = ?", (action_key, norm_scope))
                else:
                    cursor.execute("DELETE FROM permission_memory WHERE action_key = ?", (action_key,))
                conn.commit()
        except Exception as err:
            kon_logger.error(f"Erro ao limpar memória de permissão: {err}")
