# pistoncore/backend/error_logger.py
#
# SQLite-based error logger for PistonCore.
# One table: error_logs. WAL mode. 30-day purge on startup.
# Used for compiler errors, runtime issues, and unhandled exceptions.

import json
import sqlite3
import sys
import traceback
from pathlib import Path
from typing import Any, Dict, List, Optional


DB_PATH = Path("/pistoncore-userdata/pistoncore.db")


class ErrorLogger:
    """
    Lightweight SQLite error logger.
    Instantiated once at module level — import `error_logger` to use.
    """

    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self):
        """Create table and indexes, enable WAL, run 30-day purge."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS error_logs (
                    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp           TEXT NOT NULL DEFAULT (datetime('now')),
                    piston_id           TEXT,
                    piston_name         TEXT,
                    level               TEXT NOT NULL,
                    code                TEXT,
                    message             TEXT NOT NULL,
                    context             TEXT,
                    stack_trace         TEXT,
                    session_id          TEXT,
                    user_agent          TEXT,
                    ha_version          TEXT,
                    pistoncore_version  TEXT,
                    metadata            TEXT
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_error_logs_timestamp ON error_logs(timestamp)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_error_logs_piston    ON error_logs(piston_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_error_logs_level     ON error_logs(level)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_error_logs_code      ON error_logs(code)")
        self.purge_old()

    def log(self,
            level: str,
            code: str,
            message: str,
            piston_id: Optional[str] = None,
            piston_name: Optional[str] = None,
            context: Optional[str] = None,
            stack_trace: Optional[str] = None,
            metadata: Optional[Dict[str, Any]] = None):
        """
        Insert one log entry.
        session_id / user_agent / ha_version / pistoncore_version left NULL for now.
        If level is 'error' and no stack_trace is passed, captures the active
        exception traceback if one exists.
        """
        if stack_trace is None and level == "error" and sys.exc_info()[0] is not None:
            stack_trace = traceback.format_exc()

        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    INSERT INTO error_logs
                    (level, code, message, piston_id, piston_name, context,
                     stack_trace, metadata)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    level.lower(),
                    code,
                    message,
                    piston_id,
                    piston_name,
                    context,
                    stack_trace,
                    json.dumps(metadata) if metadata else None,
                ))
        except Exception as e:
            # Last resort — DB write failed, don't crash the caller
            print(f"[ERROR_LOG_FAIL] {level} {code}: {message} | {e}")

    def get_recent(self, limit: int = 100, level: Optional[str] = None) -> List[dict]:
        """Return recent log entries as a list of dicts, newest first."""
        query = "SELECT * FROM error_logs"
        params: list = []
        if level:
            query += " WHERE level = ?"
            params.append(level.lower())
        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            return [dict(row) for row in conn.execute(query, params).fetchall()]

    def purge_old(self, days: int = 30):
        """Delete entries older than `days` days."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "DELETE FROM error_logs WHERE timestamp < datetime('now', ?)",
                (f"-{days} days",),
            )


# Module-level singleton — import this instance everywhere
error_logger = ErrorLogger()
