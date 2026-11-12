"""程式碼參考檔載入：只讀取文字並切成片段作為視覺內容，絕不執行或編譯。"""
from __future__ import annotations

import random
import re
from dataclasses import dataclass, field
from pathlib import Path

from core.encoding import decode_bytes
from core.models import NovelLoadError

LEXER_BY_EXT = {
    ".py": "python", ".go": "go", ".js": "javascript", ".mjs": "javascript", ".cjs": "javascript",
    ".jsx": "jsx", ".ts": "typescript", ".tsx": "tsx", ".vue": "html", ".html": "html",
    ".htm": "html", ".css": "css", ".scss": "scss", ".sql": "sql", ".json": "json",
    ".md": "markdown", ".txt": "text", ".yml": "yaml", ".yaml": "yaml", ".toml": "toml",
    ".sh": "bash", ".bat": "batch", ".ps1": "powershell", ".java": "java", ".kt": "kotlin",
    ".c": "c", ".h": "c", ".cpp": "cpp", ".hpp": "cpp", ".cs": "csharp", ".rs": "rust",
    ".rb": "ruby", ".php": "php", ".xml": "xml", ".ini": "ini", ".cfg": "ini",
    # C / C++ family and embedded
    ".cc": "cpp", ".cxx": "cpp", ".hh": "cpp", ".hxx": "cpp", ".ino": "cpp", ".m": "objective-c",
    ".mm": "objective-c", ".cu": "cuda", ".asm": "nasm", ".s": "gas", ".v": "verilog", ".sv": "systemverilog",
    ".vhd": "vhdl", ".vhdl": "vhdl",
    # JVM / .NET / mobile
    ".kts": "kotlin", ".scala": "scala", ".groovy": "groovy", ".gradle": "groovy", ".clj": "clojure",
    ".swift": "swift", ".dart": "dart", ".fs": "fsharp", ".vb": "vbnet",
    # scripting / functional
    ".pyw": "python", ".pyi": "python", ".lua": "lua", ".pl": "perl", ".pm": "perl", ".r": "r", ".jl": "julia",
    ".ex": "elixir", ".exs": "elixir", ".erl": "erlang", ".hs": "haskell", ".ml": "ocaml", ".nim": "nim",
    ".zig": "zig", ".zsh": "bash", ".fish": "fish", ".psm1": "powershell", ".cmd": "batch",
    # web
    ".svelte": "html", ".astro": "html", ".less": "less", ".sass": "sass", ".styl": "css",
    ".graphql": "graphql", ".gql": "graphql", ".php5": "php", ".erb": "erb", ".twig": "html",
    # config / data / infra
    ".tf": "terraform", ".hcl": "terraform", ".proto": "protobuf", ".cmake": "cmake", ".mk": "make",
    ".properties": "properties", ".conf": "nginx", ".env": "bash", ".rst": "rst", ".tex": "latex",
    ".jsonc": "json", ".json5": "json", ".csv": "text", ".log": "text",
}
# 沒有副檔名、以檔名辨識的常見檔案
LEXER_BY_NAME = {
    "dockerfile": "docker", "makefile": "make", "gnumakefile": "make", "cmakelists.txt": "cmake",
    "jenkinsfile": "groovy", "vagrantfile": "ruby", "gemfile": "ruby", "rakefile": "ruby",
    ".gitignore": "text", ".dockerignore": "text", ".editorconfig": "ini", "procfile": "text",
}
_SKIP_DIRS = {".git", ".svn", ".hg", "node_modules", ".venv", "venv", "__pycache__", "dist",
              "build", ".idea", ".vscode", "vendor", "target"}
MAX_DIR_FILES = 200


@dataclass
class Snippet:
    source: str       # 顯示用檔名（相對路徑）
    start: int        # 起始行號（1-based）
    lines: list[str]
    lexer: str

    @property
    def end(self) -> int:
        return self.start + len(self.lines) - 1


@dataclass
class CodeLibrary:
    label: str = "none"
    snippets: list[Snippet] = field(default_factory=list)
    file_count: int = 0
    line_count: int = 0
    signature: str = "none"

    @property
    def empty(self) -> bool:
        return not self.snippets

    def pick(self, rng: random.Random) -> Snippet | None:
        """隨機抽取片段；可重複抽取，避免程式碼數量不足。"""
        return rng.choice(self.snippets) if self.snippets else None


def is_code_file(path: Path) -> bool:
    return path.suffix.lower() in LEXER_BY_EXT or path.name.lower() in LEXER_BY_NAME


def _lexer_for(path: Path) -> str:
    if path.name.lower() in LEXER_BY_NAME:
        return LEXER_BY_NAME[path.name.lower()]
    ext = path.suffix.lower()
    if ext in LEXER_BY_EXT:
        return LEXER_BY_EXT[ext]
    try:
        from pygments.lexers import get_lexer_for_filename
        return get_lexer_for_filename(path.name).aliases[0]
    except Exception:
        return "text"


def read_text_file(path: Path, max_bytes: int) -> str:
    try:
        size = path.stat().st_size
        if size > max_bytes:
            raise NovelLoadError(f"Code file too large ({size / 1024 / 1024:.1f} MB): {path.name}")
        data = path.read_bytes()
    except OSError as exc:
        raise NovelLoadError(f"Cannot read code file: {exc}") from exc
    if b"\x00" in data[:8192]:
        raise NovelLoadError(f"Binary file, not plain-text code: {path.name}")
    text, _ = decode_bytes(data)
    return text


_STRINGS = re.compile(r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|`[^`]*`')
_LINE_COMMENT = re.compile(r"(//|#(?!include|define|if|endif|else|pragma|import)).*$")


def _bracket_delta(line: str) -> int:
    """大括號深度變化（粗略忽略字串與行尾註解）。只看 {}，避免被截斷或跨行的 () 影響。"""
    code = _LINE_COMMENT.sub("", _STRINGS.sub('""', line))
    return code.count("{") - code.count("}")


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _units(lines: list[str]) -> list[tuple[int, int]]:
    """切出頂層邏輯單位 (起, 迄)：完整的函式 / 類別 / 區塊，連同其上方註解。

    只在「括號深度為 0、且下一個非空白行沒有縮排」的空白行處切開，
    因此 C/Go/JS 的大括號區塊與 Python 的縮排區塊都會保持完整。
    """
    units: list[tuple[int, int]] = []
    depth = 0
    start = None
    i, n = 0, len(lines)
    while i < n:
        line = lines[i]
        if not line.strip():
            if start is not None and depth <= 0:
                j = i
                while j < n and not lines[j].strip():
                    j += 1
                if j >= n or _indent(lines[j]) == 0:
                    units.append((start, i))
                    start = None
                    depth = 0
            i += 1
            continue
        if start is None:
            start = i
        depth = max(0, depth + _bracket_delta(line))
        if _indent(line) == 0 and line.lstrip().startswith("}"):
            # 頂層的右大括號：區塊在這裡結束（即使下一個函式緊接著、中間沒有空行）
            depth = 0
            units.append((start, i + 1))
            start = None
        i += 1
    if start is not None:
        units.append((start, n))
    return units


def _split_long(lines: list[str], s: int, e: int, max_lines: int) -> list[tuple[int, int]]:
    """過長的單位在內部空白行（段落）處分段；沒有空白行才硬切。
    不超過上限 1.5 倍的單位保持完整，避免把一個函式從中間切開。"""
    if e - s <= int(max_lines * 1.5):
        return [(s, e)]
    parts: list[tuple[int, int]] = []
    cur = s
    while e - cur > max_lines:
        cut = None
        # 從上限往回找最近的內部空白行，片段就在那裡結束
        for k in range(cur + max_lines, cur + max(3, max_lines // 3), -1):
            if k < e and not lines[k].strip():
                cut = k
                break
        cut = cut or cur + max_lines
        parts.append((cur, cut))
        cur = cut
        while cur < e and not lines[cur].strip():
            cur += 1
    if cur < e:
        parts.append((cur, e))
    return parts


def split_snippets(text: str, source: str, lexer: str, min_lines: int, max_lines: int) -> list[Snippet]:
    """依程式結構切成較完整的片段（整個函式 / 區塊），保留原始內容（僅將 Tab 展開為空白）。"""
    lines = [ln.rstrip("\r").expandtabs(4).rstrip() for ln in text.replace("\r\n", "\n").split("\n")]
    min_lines = max(1, min_lines)
    max_lines = max(min_lines, max_lines)

    pieces: list[tuple[int, int]] = []
    for s, e in _units(lines):
        pieces.extend(_split_long(lines, s, e, max_lines))

    # 太短的單位與後面相鄰的單位合併（中間的空白行一併保留），但不超過上限
    merged: list[tuple[int, int]] = []
    for s, e in pieces:
        if merged:
            ps, pe = merged[-1]
            if pe - ps < min_lines and e - ps <= max_lines:
                merged[-1] = (ps, e)
                continue
        merged.append((s, e))

    snippets: list[Snippet] = []
    for s, e in merged:
        chunk = lines[s:e]
        while chunk and not chunk[-1].strip():
            chunk.pop()
        if sum(1 for c in chunk if c.strip()) >= min(2, len(chunk)) and chunk:
            snippets.append(Snippet(source, s + 1, chunk, lexer))
    return snippets


def _iter_dir(root: Path):
    count = 0
    stack = [root]
    while stack and count < MAX_DIR_FILES:
        current = stack.pop()
        try:
            entries = sorted(current.iterdir())
        except OSError:
            continue
        for entry in entries:
            if entry.is_dir():
                if entry.name not in _SKIP_DIRS and not entry.name.startswith("."):
                    stack.append(entry)
            elif is_code_file(entry):
                yield entry
                count += 1
                if count >= MAX_DIR_FILES:
                    return


def load_code_library(path, *, min_lines: int = 4, max_lines: int = 10,
                      max_file_mb: float = 5, label: str | None = None,
                      base: Path | None = None) -> CodeLibrary:
    """載入單一程式碼檔或資料夾（資料夾只收已知文字副檔名）。"""
    p = Path(str(path)).expanduser()
    if not p.exists():
        raise NovelLoadError(f"Code file not found: {p}")
    max_bytes = int(max_file_mb * 1024 * 1024)
    files = list(_iter_dir(p)) if p.is_dir() else [p]
    if not files:
        raise NovelLoadError(f"No usable code files in folder: {p}")

    lib = CodeLibrary(label=label or p.name)
    errors = []
    root = base or (p if p.is_dir() else p.parent)
    for f in files:
        try:
            text = read_text_file(f, max_bytes)
        except NovelLoadError as exc:
            errors.append(str(exc))
            continue
        try:
            display = f.relative_to(root).as_posix()
        except ValueError:
            display = f.name
        lib.snippets.extend(split_snippets(text, display, _lexer_for(f), min_lines, max_lines))
        lib.file_count += 1
        lib.line_count += text.count("\n") + 1
    if not lib.snippets:
        raise NovelLoadError(errors[0] if errors else f"Code file is empty: {p.name}")
    lib.signature = f"{p.resolve()}|{lib.line_count}|{len(lib.snippets)}"
    return lib


def load_builtin_library(base_dir: Path, **kwargs) -> CodeLibrary:
    """未指定程式碼檔時，以本專案自己的真實原始碼作為來源（不自行編造程式碼）。"""
    lib = CodeLibrary(label="built-in (project source)")
    for folder in ("core", "ui", "database"):
        d = base_dir / folder
        if not d.is_dir():
            continue
        try:
            sub = load_code_library(d, base=base_dir, **kwargs)
        except NovelLoadError:
            continue
        lib.snippets.extend(sub.snippets)
        lib.file_count += sub.file_count
        lib.line_count += sub.line_count
    lib.signature = f"builtin|{lib.line_count}|{len(lib.snippets)}"
    return lib


def split_paths(setting: str) -> list[str]:
    """Split a code-source setting into paths: separated by ';', or several quoted paths."""
    import shlex
    setting = setting.strip()
    if ";" in setting:
        parts = setting.split(";")
    elif '"' in setting:
        try:
            parts = shlex.split(setting, posix=False)
        except ValueError:
            parts = [setting]
    else:
        parts = [setting]
    return [p.strip().strip('"').strip("'") for p in parts if p.strip().strip('"').strip("'")]


def load_code_sources(paths: list[str], **kwargs) -> CodeLibrary:
    """Load several files / folders into one library. Missing or unreadable entries are reported."""
    lib = CodeLibrary()
    loaded, errors, labels = [], [], []
    for raw in paths:
        p = Path(raw).expanduser()
        try:
            sub = load_code_library(p, **kwargs)
        except NovelLoadError as exc:
            errors.append(str(exc))
            continue
        lib.snippets.extend(sub.snippets)
        lib.file_count += sub.file_count
        lib.line_count += sub.line_count
        loaded.append(str(p.resolve()))
        labels.append(sub.label)
    if not lib.snippets:
        raise NovelLoadError(errors[0] if errors else "No code files given")
    lib.label = labels[0] if len(labels) == 1 else f"{labels[0]} +{len(labels) - 1} more"
    lib.signature = "|".join(loaded) + f"|{lib.line_count}|{len(lib.snippets)}"
    lib.errors = errors
    lib.paths = loaded
    return lib
