"""閱讀進度與使用者設定的高階介面。"""
from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

from database.database import Database


def path_key(path) -> str:
    return os.path.normcase(os.path.abspath(str(path)))


class ProgressManager:
    def __init__(self, db: Database) -> None:
        self.db = db
        self.last_error: str | None = db.error

    def _safe(self, fn, *args, default=None):
        try:
            return fn(*args)
        except sqlite3.Error as exc:
            self.last_error = f"Progress database error: {exc}"
            return default

    # ---- 進度 ----------------------------------------------------------
    def save(self, book, *, chapter: int, paragraph: int, char_pos: int, font_size: int,
             ratio: dict, code_path: str, mode: str) -> bool:
        values = {
            "file_path": str(Path(book.path).resolve()),
            "file_name": Path(book.path).name,
            "title": book.title,
            "chapter": int(chapter),
            "paragraph": int(paragraph),
            "char_pos": int(char_pos),
            "font_size": int(font_size),
            "ratio": json.dumps(ratio, ensure_ascii=False),
            "code_path": code_path,
            "mode": mode,
            "chapter_count": len(book.chapters),
            "total_chars": book.total_chars,
        }
        ok = self._safe(self.db.upsert_book, path_key(book.path), values, default=False)
        return ok is not False

    def load(self, path) -> dict | None:
        rec = self._safe(self.db.get_book, path_key(path))
        if rec and rec.get("ratio"):
            try:
                rec["ratio"] = json.loads(rec["ratio"])
            except ValueError:
                rec["ratio"] = None
        return rec

    def recent(self, limit: int = 10) -> list[dict]:
        rows = self._safe(self.db.recent_books, limit, default=[]) or []
        for r in rows:
            r["exists"] = Path(r["file_path"]).exists()
        return rows

    # ---- 設定 ----------------------------------------------------------
    def get_settings(self) -> dict:
        raw = self._safe(self.db.all_settings, default={}) or {}
        result = {}
        for key, value in raw.items():
            try:
                result[key] = json.loads(value) if value is not None else None
            except ValueError:
                result[key] = value
        return result

    def set_setting(self, key: str, value) -> None:
        self._safe(self.db.set_setting, key, json.dumps(value, ensure_ascii=False))
