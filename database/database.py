"""SQLite 存取層：閱讀進度與使用者設定。所有查詢皆使用參數化。"""
from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS books (
    path_key      TEXT PRIMARY KEY,
    file_path     TEXT NOT NULL,
    file_name     TEXT NOT NULL,
    title         TEXT,
    chapter       INTEGER NOT NULL DEFAULT 0,
    paragraph     INTEGER NOT NULL DEFAULT 0,
    char_pos      INTEGER NOT NULL DEFAULT 0,
    font_size     INTEGER,
    ratio         TEXT,
    code_path     TEXT,
    mode          TEXT,
    chapter_count INTEGER,
    total_chars   INTEGER,
    updated_at    TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""

BOOK_COLUMNS = ("file_path", "file_name", "title", "chapter", "paragraph", "char_pos", "font_size",
                "ratio", "code_path", "mode", "chapter_count", "total_chars")


class Database:
    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        self.error: str | None = None
        try:
            if self.path != ":memory:":
                Path(self.path).parent.mkdir(parents=True, exist_ok=True)
            self.conn = self._connect(self.path)
        except (sqlite3.Error, OSError) as exc:
            # 資料庫無法開啟時不刪除原檔，改用記憶體資料庫並提示使用者
            self.error = f"Cannot open progress database, progress will not be saved: {exc}"
            self.conn = self._connect(":memory:")

    @staticmethod
    def _connect(path: str) -> sqlite3.Connection:
        conn = sqlite3.connect(path, timeout=5)
        conn.row_factory = sqlite3.Row
        conn.executescript(SCHEMA)
        conn.commit()
        return conn

    def close(self) -> None:
        try:
            self.conn.close()
        except sqlite3.Error:
            pass

    # ---- books ---------------------------------------------------------
    def upsert_book(self, path_key: str, values: dict) -> None:
        cols = [c for c in BOOK_COLUMNS if c in values]
        names = ", ".join(["path_key", *cols, "updated_at"])
        marks = ", ".join(["?"] * (len(cols) + 1) + ["datetime('now', 'localtime')"])
        updates = ", ".join(f"{c} = excluded.{c}" for c in [*cols, "updated_at"])
        sql = f"INSERT INTO books ({names}) VALUES ({marks}) ON CONFLICT(path_key) DO UPDATE SET {updates}"
        with self.conn:
            self.conn.execute(sql, [path_key, *[values[c] for c in cols]])

    def get_book(self, path_key: str) -> dict | None:
        row = self.conn.execute("SELECT * FROM books WHERE path_key = ?", (path_key,)).fetchone()
        return dict(row) if row else None

    def recent_books(self, limit: int = 10) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM books ORDER BY updated_at DESC LIMIT ?", (int(limit),)
        ).fetchall()
        return [dict(r) for r in rows]

    # ---- settings ------------------------------------------------------
    def get_setting(self, key: str) -> str | None:
        row = self.conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None

    def all_settings(self) -> dict[str, str]:
        return {r["key"]: r["value"] for r in self.conn.execute("SELECT key, value FROM settings")}

    def set_setting(self, key: str, value: str | None) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )
