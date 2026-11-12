"""程式碼片段的靜態分析（純文字規則，不執行程式碼），供偽裝畫面產生具體的回答。

只回報片段中實際出現的東西：名稱、參數、提前返回條件、迴圈、呼叫、寫入的欄位、
回傳值、錯誤處理與常見問題（未檢查的回傳值、魔術數字、無窮迴圈、空的例外處理、TODO）。
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

from core.code_loader import Snippet, _indent

KEYWORDS = {
    "if", "for", "while", "switch", "return", "sizeof", "catch", "elif", "else", "with", "assert",
    "and", "or", "not", "in", "is", "lambda", "super", "typeof", "new", "delete", "defined",
    "foreach", "until", "unless", "case", "do", "try", "except", "match", "when", "print", "printf",
}
COMMON_CONSTS = {"NULL", "TRUE", "FALSE", "EOF", "TODO", "FIXME", "XXX", "NOTE", "HACK", "OK", "ID", "API", "URL",
                 "HTTP", "JSON", "UTF", "MAC", "AP", "STA", "DS", "WDS"}
# 常見會失敗、需要檢查結果的呼叫
FALLIBLE = {
    "malloc", "calloc", "realloc", "fopen", "open", "socket", "connect", "bind", "listen", "accept", "recv",
    "send", "write", "read", "fwrite", "fread", "xQueueSend", "xQueueSendFromISR", "xQueueCreate",
    "xTaskCreate", "xTaskCreatePinnedToCore", "xSemaphoreTake", "pthread_create", "mmap", "strdup",
    "esp_wifi_init", "esp_wifi_start", "esp_wifi_set_mode", "esp_wifi_set_channel", "esp_wifi_80211_tx",
    "nvs_flash_init", "json.loads", "requests.get", "requests.post", "fetch", "JSON.parse", "os.Open",
    "ioutil.ReadFile", "http.Get", "subprocess.run",
}

_LINE_COMMENT = re.compile(r"^\s*(//+|#(?!\s*(?:include|define|if|ifdef|ifndef|endif|else|pragma|undef)\b)|--|;|\*|/\*+)\s?(.*?)\s*(\*/)?$")
_TRAIL_COMMENT = re.compile(r"(?://|#)\s*(.+)$")
_CALL = re.compile(r"\b([A-Za-z_][\w.]*)\s*\(")
_IF_LINE = re.compile(r"^\s*(?:\}\s*)?(?:else\s+)?if\s*\(?\s*(.+?)\s*\)?\s*(?:\{|:|then)?\s*$")
_IF_INLINE_RETURN = re.compile(r"^\s*if\s*\(?\s*(.+?)\s*\)?\s*(?::|\))?\s*return\b")
_LOOP = re.compile(r"^\s*(for|while|foreach)\b\s*\(?\s*(.*?)\s*\)?\s*(?:\{|:|do)?\s*$")
_RETURN = re.compile(r"^\s*return\b\s*(.*?)\s*;?\s*$")
_FIELD_SET = re.compile(r"\b([A-Za-z_]\w*)(?:\.|->)([A-Za-z_]\w*)\s*(?:\[[^\]]*\])?\s*=(?!=)")
_CONST = re.compile(r"\b([A-Z][A-Z0-9_]{2,})\b")
_NUMBER = re.compile(r"(?<![\w.])(0x[0-9a-fA-F]+|\d{2,})(?![\w.])")
_INFINITE = re.compile(r"while\s*\(\s*(?:1|true)\s*\)|while\s+True\s*:|for\s*\(\s*;\s*;\s*\)|\bloop\s*\{")
_STRUCT_FIELD = re.compile(r"^\s*(?:const\s+)?[A-Za-z_][\w\s\*]*?[\s\*]([A-Za-z_]\w*)\s*(?:\[[^\]]*\])?\s*;")
_DEFINE = re.compile(r"^\s*#\s*define\s+([A-Za-z_]\w*)")
_PY_METHOD = re.compile(r"^\s+(?:async\s+)?def\s+(\w+)")

_DEF_PATTERNS = [
    ("macro", re.compile(r"^\s*#\s*define\s+(\w+)")),
    ("struct", re.compile(r"^\s*(?:typedef\s+)?(?:struct|enum|union)\s+(\w+)")),
    ("function", re.compile(r"^\s*(?:@\w+.*\n)?\s*(?:async\s+)?def\s+(\w+)\s*\(([^)]*)")),
    ("class", re.compile(r"^\s*(?:export\s+)?(?:abstract\s+)?(?:public\s+)?class\s+(\w+)")),
    ("function", re.compile(r"^\s*func\s+(?:\([^)]*\)\s*)?(\w+)\s*\(([^)]*)")),
    ("function", re.compile(r"^\s*(?:export\s+)?(?:async\s+)?function\s+(\w+)\s*\(([^)]*)")),
    ("function", re.compile(r"^\s*(?:pub\s+)?fn\s+(\w+)\s*(?:<[^>]*>)?\s*\(([^)]*)")),
    ("function", re.compile(r"^\s*(?:export\s+)?(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s*)?\(([^)]*)")),
    ("function", re.compile(r"^\s*(?:local\s+)?function\s+([\w.:]+)\s*\(([^)]*)")),
    ("function", re.compile(r"^[A-Za-z_][\w\s\*&:<>,]*?\b(\w+)\s*\(([^;{]*)\)?\s*\{?\s*$")),
]


@dataclass
class Facts:
    name: str = ""
    kind: str = "block"            # function | method | class | struct | macro | block
    params: list[str] = field(default_factory=list)
    comment: str = ""
    early_returns: list[str] = field(default_factory=list)
    loops: list[str] = field(default_factory=list)
    calls: list[tuple[str, int]] = field(default_factory=list)
    fields_set: dict[str, list[str]] = field(default_factory=dict)
    returns: list[str] = field(default_factory=list)
    error_handling: list[str] = field(default_factory=list)
    constants: list[str] = field(default_factory=list)
    struct_fields: list[str] = field(default_factory=list)
    defines: list[str] = field(default_factory=list)
    methods: list[str] = field(default_factory=list)
    includes: list[str] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)
    infinite_loop: bool = False
    length: int = 0
    span: tuple[int, int] = (0, 0)


def _clean(expr: str, limit: int = 48) -> str:
    expr = " ".join(expr.split()).strip().rstrip("{:; ").strip()
    while expr.count(")") > expr.count("(") and expr.endswith(")"):
        expr = expr[:-1].rstrip()
    if expr.count("(") > expr.count(")"):
        expr += ")" * (expr.count("(") - expr.count(")"))
    return expr if len(expr) <= limit else expr[: limit - 1] + "…"


def _params(raw: str) -> list[str]:
    out = []
    for part in raw.split(","):
        part = part.split("=")[0].split(":")[0].strip()
        m = re.findall(r"[A-Za-z_]\w*", part)
        if m and m[-1] not in ("void", "self", "cls", "this"):
            out.append(m[-1])
    return out


def _code_only(line: str) -> str:
    """Strip strings and trailing comments for pattern matching."""
    line = re.sub(r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'', '""', line)
    return re.sub(r"\s(//|#).*$", "", line)


def _is_comment(raw: str) -> bool:
    return bool(raw.strip()) and bool(_LINE_COMMENT.match(raw)) and not _DEFINE.match(raw)


def _match_def(raw: str):
    for kind, pat in _DEF_PATTERNS:
        m = pat.match(raw)
        if m and m.group(1) not in KEYWORDS:
            return kind, m
    return None


def definitions(lines: list[str]) -> list[tuple[int, str, re.Match]]:
    """All definitions in a snippet: (line index, kind, match)."""
    out = []
    for i, raw in enumerate(lines):
        if _is_comment(raw):
            continue
        hit = _match_def(raw)
        if hit:
            out.append((i, hit[0], hit[1]))
    return out


def def_names(sn: Snippet) -> list[str]:
    return [m.group(1) for _, _, m in definitions(sn.lines)]


def _block_range(lines: list[str], def_idx: int) -> tuple[int, int]:
    """[lo, hi) of one definition: leading comments/decorators, signature and indented body."""
    d_ind = _indent(lines[def_idx])
    j = def_idx + 1
    while j < len(lines):
        ln = lines[j]
        st = ln.strip()
        if st and _indent(ln) <= d_ind:
            if st.startswith("{") and j == def_idx + 1:      # C style: brace on its own line
                j += 1
                continue
            if st.startswith(("}", ")", "end")):            # closing line belongs to the block
                j += 1
            break
        j += 1
    lo = def_idx
    while lo > 0 and lines[lo - 1].strip() and (_is_comment(lines[lo - 1]) or lines[lo - 1].lstrip().startswith("@")):
        lo -= 1
    hi = j
    while hi > def_idx + 1 and not lines[hi - 1].strip():
        hi -= 1
    return lo, hi


def analyze(sn: Snippet, focus: str | None = None) -> Facts:
    """Analyze one definition in the snippet (the one named `focus`, or the first one)."""
    all_lines = sn.lines
    f = Facts(length=len(all_lines))
    defs = definitions(all_lines)
    chosen = next((d for d in defs if focus and d[2].group(1) == focus), defs[0] if defs else None)
    lo, hi = 0, len(all_lines)
    if chosen is not None:
        idx, kind, m = chosen
        f.name, f.kind = m.group(1), kind
        if kind == "function" and m.lastindex and m.lastindex >= 2:
            f.params = _params(m.group(2) or "")
            if all_lines[idx].startswith((" ", "\t")) and re.search(r"\bself\b", m.group(2) or ""):
                f.kind = "method"
        if f.kind in ("function", "method", "class"):
            lo, hi = _block_range(all_lines, idx)
    f.span = (sn.start + lo, sn.start + hi - 1)
    f.length = hi - lo
    lines = all_lines[lo:hi]

    code_lines: list[tuple[int, str]] = []
    comments: list[str] = []
    for i, raw in enumerate(lines):
        stripped = raw.strip()
        if _is_comment(raw):
            text = _LINE_COMMENT.match(raw).group(2).strip().strip("*/").strip()
            if text:
                comments.append(text)
            continue
        if stripped.startswith(('"""', "\'\'\'")):
            text = stripped.strip("\"' ")
            if text:
                comments.append(text)
            continue
        code_lines.append((i, raw))

    if not f.name and code_lines:
        # typedef struct { ... } name;
        m = re.match(r"^\s*\}\s*(\w+)\s*;", code_lines[-1][1])
        if m:
            f.name, f.kind = m.group(1), "struct"
    for _, raw in code_lines:
        m = (re.match(r"^\s*#\s*include\s*[<\"]([^>\"]+)", raw)
             or re.match(r"^\s*(?:from\s+([\w.]+)\s+import|import\s+([\w.]+))", raw)
             or re.match(r"^\s*(?:const|let|var|import)\s.*?(?:require\(|from\s+)['\"]([^'\"]+)", raw)
             or re.match(r"^\s*use\s+([\w:]+)", raw))
        if m:
            name = next(g for g in m.groups() if g)
            if name not in f.includes:
                f.includes.append(name)
    if comments:
        f.comment = comments[0]
    else:
        for _, raw in code_lines[:1]:
            m = _TRAIL_COMMENT.search(raw)
            if m and not raw.lstrip().startswith("#"):
                f.comment = m.group(1).strip()
                break

    # ---- body -------------------------------------------------------------------
    call_counter: Counter = Counter()
    seen_returns: list[str] = []
    for idx, (i, raw) in enumerate(code_lines):
        code = _code_only(raw)
        m = _IF_INLINE_RETURN.match(code)
        if m:
            f.early_returns.append(_clean(m.group(1)))
        else:
            m = _IF_LINE.match(code)
            if m and idx + 1 < len(code_lines) and code_lines[idx + 1][1].strip().startswith("return"):
                f.early_returns.append(_clean(m.group(1)))
        m = _LOOP.match(code)
        if m and m.group(2):
            f.loops.append(f"{m.group(1)} ({_clean(m.group(2), 40)})")
        m = _RETURN.match(code)
        if m and m.group(1) and m.group(1) not in seen_returns:
            seen_returns.append(_clean(m.group(1), 36))
        for c in _CALL.findall(code):
            base = c.split(".")[-1]
            if base not in KEYWORDS and c != f.name:
                call_counter[c] += 1
        for obj, attr in _FIELD_SET.findall(code):
            f.fields_set.setdefault(obj, [])
            if attr not in f.fields_set[obj]:
                f.fields_set[obj].append(attr)
        lowered = code.lower()
        for marker, label in (("try", "try/except"), ("catch", "try/catch"), ("except", "except"),
                              ("raise", "raise"), ("throw", "throw"), ("err != nil", "Go error check"),
                              ("esp_error_check", "ESP_ERROR_CHECK"), ("== null", "NULL check"),
                              ("!= null", "NULL check"), ("is none", "None check")):
            if re.search(rf"(?<![\w]){re.escape(marker)}(?![\w])", lowered) and label not in f.error_handling:
                f.error_handling.append(label)
        if _INFINITE.search(code):
            f.infinite_loop = True
        if f.kind == "struct":
            m = _STRUCT_FIELD.match(code)
            if m and m.group(1) not in f.struct_fields and not code.lstrip().startswith(("typedef", "}")):
                f.struct_fields.append(m.group(1))
        m = _DEFINE.match(raw)
        if m:
            f.defines.append(m.group(1))
        m = _PY_METHOD.match(raw)
        if m and f.kind == "class":
            f.methods.append(m.group(1))
    f.returns = seen_returns[:4]
    f.calls = call_counter.most_common(8)
    consts = []
    for _, raw in code_lines:
        for c in _CONST.findall(_code_only(raw)):
            if c not in COMMON_CONSTS and c != f.name and c not in consts and c not in f.defines:
                consts.append(c)
    f.constants = consts[:6]
    f.issues = _issues(f, code_lines, comments)
    return f


def _issues(f: Facts, code_lines: list[tuple[int, str]], comments: list[str]) -> list[str]:
    issues: list[str] = []
    joined = "\n".join(raw for _, raw in code_lines)
    # unchecked results of calls that can fail
    for _, raw in code_lines:
        code = _code_only(raw).strip()
        for name in FALLIBLE:
            short = name.split(".")[-1]
            if re.match(rf"^(?:\(void\)\s*)?{re.escape(name)}\s*\(", code) or re.match(rf"^{re.escape(short)}\s*\(", code):
                if not code.startswith("(void)"):
                    issues.append(f"The return value of `{name}` is ignored. If it can fail, the error is silently dropped.")
                break
            m = re.match(rf"^(?:[\w\s\*]+?)?\b(\w+)\s*=\s*(?:\([^)]*\)\s*)?{re.escape(name)}\s*\(", code)
            if m:
                var = m.group(1)
                if not re.search(rf"if\s*\(?[^\n]*\b{re.escape(var)}\b", joined):
                    issues.append(f"`{var}` comes from `{name}` but is never checked before use.")
                break
    if f.infinite_loop and "break" not in joined and "return" not in joined.split("while", 1)[-1]:
        issues.append("The loop never exits, so this has to run in its own task/thread and will block anything after it.")
    if re.search(r"except\s*:|except\s+Exception\s*:\s*\n\s*pass|catch\s*\([^)]*\)\s*\{\s*\}", joined):
        issues.append("An exception is caught and swallowed, which will hide real failures.")
    magic = []
    for _, raw in code_lines:
        if _DEFINE.match(raw) or "=" in raw.split("//")[0] and raw.strip().endswith(","):
            continue
        for n in _NUMBER.findall(_code_only(raw)):
            if n not in ("10", "100", "1000", "0x00", "0xff", "0xFF") and n not in magic:
                magic.append(n)
    if len(magic) >= 2:
        sample = ", ".join(f"`{m}`" for m in magic[:3])
        issues.append(f"There are a few magic numbers ({sample}). Named constants would make the intent clearer.")
    for c in comments:
        if re.search(r"\b(TODO|FIXME|XXX|HACK)\b", c):
            issues.append(f"There's an open note in the code: `{_clean(c, 60)}`.")
            break
    if f.length > 45 and f.kind in ("function", "method"):
        issues.append(f"At {f.length} lines, `{f.name}` is doing quite a lot; it could be split into smaller helpers.")
    unique: list[str] = []
    for msg in issues:
        if msg not in unique:
            unique.append(msg)
    return unique[:4]
