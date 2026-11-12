"""假裝的程式碼修改（Claude Code 的 Update 區塊：紅色 - 刪除、綠色 + 新增）。

只用於畫面顯示，不會寫入任何檔案。`-` 行是片段中的真實原始碼，`+` 行是依規則
改寫的版本（加上回傳值檢查、加上 const、Python 加上 try/except、Go 加上 err 檢查），看起來像一次小修改。
"""
from __future__ import annotations

import random
import re
from dataclasses import dataclass, field

from core.code_loader import Snippet

C_LIKE = {"c", "cpp", "cuda", "objective-c", "java", "csharp", "javascript", "typescript", "jsx", "tsx",
          "go", "rust", "kotlin", "swift", "dart", "scala", "groovy", "php"}
_STATEMENT_CALL = re.compile(r"^(\s*)([A-Za-z_][\w.>-]*)\s*\((.*)\)\s*;\s*(//.*)?$")
_PY_CALL = re.compile(r"^(\s*)([A-Za-z_][\w.]*)\s*\((.*)\)\s*(#.*)?$")
_C_DECL = re.compile(r"^(\s*)((?:unsigned\s+|signed\s+)?(?:int|char|float|double|size_t|uint\d+_t|int\d+_t|bool|auto|long|short)\b[^=;]*=[^;]*;.*)$")


@dataclass
class FakeDiff:
    source: str
    rows: list[tuple[str, int, str]] = field(default_factory=list)   # (" " | "-" | "+", line no, text)
    additions: int = 0
    removals: int = 0

    @property
    def summary(self) -> str:
        def plural(n: int, word: str) -> str:
            return f"{n} {word}{'' if n == 1 else 's'}"
        parts = []
        if self.additions:
            parts.append(plural(self.additions, "addition"))
        if self.removals:
            parts.append(plural(self.removals, "removal"))
        return f"Updated {self.source} with " + " and ".join(parts or ["no changes"])


def _rewrite(line: str, lexer: str, rng: random.Random) -> list[str] | None:
    """Return replacement lines for one real line, or None if no rule applies."""
    indent = line[: len(line) - len(line.lstrip())]
    if lexer in C_LIKE and lexer not in ("go", "rust", "python"):
        m = _STATEMENT_CALL.match(line)
        if m and m.group(2) not in ("return", "printf", "free", "memcpy", "memset", "vTaskDelay", "sizeof"):
            call = f"{m.group(2)}({m.group(3)})"
            return [f"{indent}if ({call} != 0) {{", f"{indent}    return;", f"{indent}}}"]
        m = _C_DECL.match(line)
        if m and "const " not in line and "*" not in line.split("=")[0]:
            return [f"{indent}const {m.group(2)}"]
    if lexer == "python":
        m = _PY_CALL.match(line)
        if m and not line.strip().startswith(("return", "print", "self.assert", "raise", "yield")) and "=" not in line:
            return [f"{indent}try:", f"{indent}    {line.strip()}", f"{indent}except Exception as exc:",
                    f"{indent}    logger.warning(\"{m.group(2)} failed: %s\", exc)"]
    if lexer == "go":
        m = re.match(r"^(\s*)(\w+)\s*:=\s*(.+)$", line)
        if m and "err" not in line:
            return [f"{indent}{m.group(2)}, err := {m.group(3)}", f"{indent}if err != nil {{",
                    f"{indent}    return err", f"{indent}}}"]
    return None


def make_diff(sn: Snippet, rng: random.Random, prefer: list[str] | None = None, context: int = 2) -> FakeDiff | None:
    """Pick a line of the snippet and pretend to change it."""
    candidates = [i for i, ln in enumerate(sn.lines)
                  if ln.strip() and not ln.strip().startswith(("//", "#", "/*", "*", "}", "{", '"""'))]
    if not candidates:
        return None
    if prefer:   # lines mentioning something the answer talked about (e.g. an unchecked call)
        preferred = [i for i in candidates if any(name in sn.lines[i] for name in prefer)]
        order = preferred + [i for i in rng.sample(candidates, len(candidates)) if i not in preferred]
    else:
        order = rng.sample(candidates, len(candidates))
    for idx in order:
        new_lines = _rewrite(sn.lines[idx], sn.lexer, rng)
        if not new_lines or new_lines == [sn.lines[idx]]:
            continue
        diff = FakeDiff(sn.source)
        lo = max(0, idx - context)
        hi = min(len(sn.lines), idx + 1 + context)
        for j in range(lo, idx):
            diff.rows.append((" ", sn.start + j, sn.lines[j]))
        diff.rows.append(("-", sn.start + idx, sn.lines[idx]))
        for k, text in enumerate(new_lines):
            diff.rows.append(("+", sn.start + idx + k, text))
        shift = len(new_lines) - 1
        for j in range(idx + 1, hi):
            diff.rows.append((" ", sn.start + j + shift, sn.lines[j]))
        diff.additions, diff.removals = len(new_lines), 1
        return diff
    return None
