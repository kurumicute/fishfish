"""設定檔載入：config/settings.json 與內建預設值合併。"""
from __future__ import annotations

import copy
import json
from pathlib import Path

DEFAULTS: dict = {
    "ratio": {"novel": 62, "work": 10, "code": 24, "status": 4},
    "mode": "mixed",
    "font_size": 3,
    "theme": "claude",
    "language": "en",
    "ascii_glyphs": False,
    "effort": "medium",
    "footer_mode": "auto",
    "show_progress": True,
    "ambient": {"min_interval": 35, "max_interval": 90},
    "code": {"min_lines": 5, "max_lines": 40, "max_file_mb": 5},
    "novel": {"max_file_mb": 200, "auto_section_chars": 4000, "max_chapter_chars": 30000},
    "header": {
        "title": "Claude Code",
        "version": "v2.1.322",
        "model": "Opus 5.5 · Claude Pro",
        "cwd": "",
    },
    "placeholders": [
        "Try \"fix lint errors\"",
        "Try \"refactor <filepath>\"",
        "Try \"how does <filepath> work?\"",
        "Try \"write a test for <filepath>\"",
    ],
}

RATIO_KEYS = ("novel", "work", "code", "status")
MIN_NOVEL_PERCENT = 40


def _merge(base: dict, override: dict) -> dict:
    for key, value in override.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            _merge(base[key], value)
        elif key in base:
            base[key] = value
    return base


def load_config(path: Path) -> tuple[dict, str | None]:
    """回傳 (設定, 錯誤訊息)。設定檔壞掉時使用預設值，不中斷程式。"""
    cfg = copy.deepcopy(DEFAULTS)
    try:
        with open(path, encoding="utf-8-sig") as fh:
            data = json.load(fh)
        if isinstance(data, dict):
            _merge(cfg, data)
        return cfg, None
    except FileNotFoundError:
        return cfg, None
    except (OSError, ValueError) as exc:
        return cfg, f"Failed to read settings.json, using defaults: {exc}"


def normalize_ratio(raw) -> dict:
    """把比例正規化為總和 100 的整數，並確保小說比例不低於下限。"""
    ratio = {}
    for key in RATIO_KEYS:
        try:
            ratio[key] = max(0.0, float((raw or {}).get(key, 0)))
        except (TypeError, ValueError):
            ratio[key] = 0.0
    total = sum(ratio.values())
    if total <= 0 or ratio["novel"] <= 0:
        return dict(DEFAULTS["ratio"])
    scaled = {k: v * 100.0 / total for k, v in ratio.items()}
    if scaled["novel"] < MIN_NOVEL_PERCENT:
        others = sum(scaled[k] for k in RATIO_KEYS if k != "novel")
        factor = (100 - MIN_NOVEL_PERCENT) / others if others else 0
        for k in RATIO_KEYS:
            scaled[k] = MIN_NOVEL_PERCENT if k == "novel" else scaled[k] * factor
    result = {k: int(round(v)) for k, v in scaled.items()}
    result["novel"] += 100 - sum(result.values())
    return result
