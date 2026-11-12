"""Ctrl+Q 偽裝畫面：只有程式碼與模擬的 Claude Code 問答。

回答由本機規則產生：先以 core.code_analysis 靜態分析真實的程式碼片段，
再依提問意圖（解釋 / 審查 / 找 bug / 錯誤處理）組合成具體說明。
不呼叫任何 AI 服務，不編造程式碼；回答中提到的名稱、條件與行號都取自片段原文。
"""
from __future__ import annotations

import random
import re
from dataclasses import dataclass, field
from pathlib import PurePath

from core.code_analysis import Facts, analyze, def_names
from core.code_loader import CodeLibrary, Snippet
from core.fake_diff import make_diff


@dataclass
class Exchange:
    prompt: str
    # ("text", str) | ("read", Snippet) | ("search", pattern, file, n)
    # | ("list", intro, [items]) numbered | ("bullets", intro, [items])
    items: list = field(default_factory=list)


def snippet_names(sn: Snippet) -> tuple[str, list[str]]:
    f = analyze(sn)
    return f.name, [c for c, _ in f.calls]


# ---------------------------------------------------------------- intents
INTENT_WORDS = {
    "review": ("review", "check", "look over", "feedback", "clean", "improve", "refactor", "審查", "看一下"),
    "bug": ("bug", "wrong", "broken", "crash", "fix", "issue", "problem", "fail", "錯", "壞"),
    "errors": ("error", "exception", "handle", "handling", "safe", "edge case"),
}
PROMPTS = {
    "explain": ["explain how {name} works", "what does {name} do?", "walk me through {file} lines {start}-{end}",
                "how does {name} use {call}?", "can you explain {name} in {file}?"],
    "review": ["can you review {name}?", "review {file} lines {start}-{end}", "any feedback on {name}?",
               "is {name} written well?", "check {name} before I commit"],
    "bug": ["is there a bug in {name}?", "{name} sometimes behaves wrong, can you find why?",
            "anything wrong with {name}?", "why might {name} fail?"],
    "errors": ["does {name} handle errors correctly?", "what happens in {name} if {call} fails?",
               "check error handling in {name}"],
}


def detect_intent(prompt: str) -> str:
    low = prompt.lower()
    for intent, words in INTENT_WORDS.items():
        if any(w in low for w in words):
            return intent
    return "explain"


# ---------------------------------------------------------------- phrasing
def _role(f: Facts) -> str:
    n = f.name.lower()
    calls = {c for c, _ in f.calls}
    if f.kind == "method":
        return "method"
    if n in ("main", "app_main") or n.endswith("_main"):
        return "entry point"
    if n.endswith(("_cb", "callback")) or "callback" in n:
        return "callback"
    if "task" in n or "vTaskDelay" in calls:
        return "background task"
    if n.startswith("test"):
        return "test"
    if "handle" in n or "handler" in n:
        return "handler"
    if n.startswith(("init", "setup")) or n.endswith(("_init", "_setup")):
        return "initialization routine"
    if n.startswith(("parse", "decode")):
        return "parser"
    if n.startswith(("build", "make", "create", "new")):
        return "builder"
    return "function"


def _code_list(names: list[str], limit: int = 4) -> str:
    shown = [f"`{x}`" for x in names[:limit]]
    more = "…" if len(names) > limit else ""
    if len(shown) == 1:
        return shown[0] + more
    return ", ".join(shown[:-1]) + f" and {shown[-1]}{more}" if not more else ", ".join(shown) + more


def _summary(f: Facts, sn: Snippet, file: str) -> str:
    a, b = f.span if f.span != (0, 0) else (sn.start, sn.end)
    loc = f"`{file}:{a}-{b}`"
    if f.kind == "method" and f.name:
        s = f"`{f.name}` ({loc}) is a method"
        s += f" that takes {_code_list(f.params)}." if f.params else " that takes no arguments besides `self`."
    elif f.kind == "function" and f.name:
        s = f"`{f.name}` ({loc}) is the {_role(f)}"
        s += f" and takes {_code_list(f.params)}." if f.params else " and takes no arguments."
    elif f.kind == "struct" and f.name:
        s = f"`{f.name}` ({loc}) is a struct"
        s += f" with {len(f.struct_fields)} fields: {_code_list(f.struct_fields, 6)}." if f.struct_fields else "."
    elif f.kind == "macro" or f.defines:
        s = f"This part of `{file}` ({loc}) defines {_code_list(f.defines or [f.name], 5)}."
    elif f.kind == "class" and f.name:
        s = f"`{f.name}` ({loc}) is a class"
        s += f" with {_code_list(f.methods, 5)}." if f.methods else "."
    elif f.includes:
        s = f"Lines {sn.start}-{sn.end} of `{file}` pull in {_code_list(f.includes, 5)}."
    else:
        s = f"Lines {sn.start}-{sn.end} of `{file}` are top-level setup code."
    if f.comment:
        s += f' The comment there sums up the intent: "{f.comment}".'
    return s


def _flow(f: Facts) -> list[str]:
    steps: list[str] = []
    for cond in f.early_returns[:3]:
        steps.append(f"Returns early when `{cond}`")
    for obj, attrs in list(f.fields_set.items())[:2]:
        if obj in ("self", "this"):
            steps.append("Updates " + _code_list([f"{obj}.{a}" for a in attrs], 4))
        else:
            steps.append(f"Fills in `{obj}` ({_code_list(attrs, 4)})")
    for loop in f.loops[:2]:
        steps.append(f"Runs a `{loop}` loop")
    calls = [c for c, _ in f.calls if c not in f.fields_set]
    if calls:
        parts = [f"`{c}`" + (f" ({n}×)" if n > 1 else "") for c, n in f.calls[:4]]
        steps.append("Calls " + ", ".join(parts))
    if f.returns:
        steps.append(("Returns " if len(f.returns) == 1 else "Returns one of ") + ", ".join(f"`{r}`" for r in f.returns))
    if f.error_handling:
        steps.append("Handles failures with " + ", ".join(f.error_handling))
    if f.kind == "struct" and f.struct_fields and not steps:
        steps.append(f"Holds {_code_list(f.struct_fields, 6)}")
    if not steps:
        steps.append("Runs a few straight-line statements with no branching")
    return steps[:6]


def _answer(f: Facts, sn: Snippet, file: str, intent: str, rng: random.Random) -> list:
    items: list = [("text", _summary(f, sn, file))]
    flow = _flow(f)
    name = f"`{f.name}`" if f.name else "this block"
    first_call = f.calls[0][0] if f.calls else None
    if intent == "review":
        if f.issues:
            items.append(("bullets", "**A few things worth looking at:**", f.issues))
            items.append(("text", f"Otherwise the structure of {name} is reasonable: it {flow[0][0].lower() + flow[0][1:]}."))
        else:
            items.append(("list", "Here's what it does:", flow))
            items.append(("text", f"I don't see anything in {name} that needs to change."))
    elif intent == "bug":
        if f.issues:
            items.append(("text", "I don't see a definite bug, but this is the most likely source of trouble:"))
            items.append(("bullets", "", f.issues[:2]))
            if first_call:
                items.append(("text", f"If the behavior is intermittent, I'd add logging around `{first_call}` first."))
        else:
            items.append(("list", "I couldn't find a bug here. The flow is:", flow))
            hint = f"`{first_call}`" if first_call else "the callers"
            items.append(("text", f"If you're still seeing wrong behavior, the next place I'd check is {hint}."))
    elif intent == "errors":
        if f.error_handling:
            items.append(("text", f"{name} handles failures with {', '.join(f.error_handling)}."))
        else:
            items.append(("text", f"There's no explicit error handling in {name}."))
        relevant = [i for i in f.issues if "ignored" in i or "checked" in i or "swallowed" in i]
        if relevant:
            items.append(("bullets", "**Gaps:**", relevant))
        elif f.early_returns:
            items.append(("text", f"It does guard its inputs: it returns early when `{f.early_returns[0]}`."))
    else:
        items.append(("list", "Here's the flow:", flow))
        if f.issues and rng.random() < 0.6:
            items.append(("text", "One thing to keep in mind: " + f.issues[0]))
    return items


# ---------------------------------------------------------------- exchanges
_WORD = re.compile(r"[A-Za-z_]\w{2,}")


def _pick_for_prompt(lib: CodeLibrary, rng: random.Random, prompt: str | None) -> Snippet | None:
    """When the typed question names something that really exists in the code, read that part."""
    if prompt and lib.snippets:
        words = set(_WORD.findall(prompt))
        defined = [sn for sn in lib.snippets if words & set(def_names(sn))]
        if defined:
            return rng.choice(defined)
        mentioned = [sn for sn in lib.snippets if any(w in "\n".join(sn.lines) for w in words)]
        if mentioned:
            return rng.choice(mentioned)
    return lib.pick(rng)


def _count_matches(lib: CodeLibrary, source: str, pattern: str) -> int:
    """Real number of lines in the loaded code that contain the pattern."""
    seen = set()
    for sn in lib.snippets:
        if sn.source != source:
            continue
        for i, line in enumerate(sn.lines):
            if pattern in line:
                seen.add(sn.start + i)
    return len(seen)


FIX_INTROS = ["Let me fix that.", "I'll make that change.", "Here's a small fix:", "Let me tighten that up."]
FIX_DONE = [
    "Done. The change is limited to `{file}`; nothing else needs to move.",
    "That's the only change. The rest of `{file}` can stay as is.",
    "Updated. The behavior is the same on the normal path; it just handles that case explicitly now.",
]

INTROS = [
    "I'll read `{file}` to see how {name} works.",
    "Let me look at {name} in `{file}`.",
    "Let me check the relevant part of `{file}`.",
    "I'll start by reading {name}.",
]


def make_exchange(lib: CodeLibrary, rng: random.Random, prompt: str | None = None) -> Exchange:
    sn = _pick_for_prompt(lib, rng, prompt)
    if sn is None:
        return Exchange(prompt or "summarize this project",
                        [("text", "There are no code files loaded yet. Use `/code <path>` to add one.")])
    focus = None
    if prompt:
        words = set(_WORD.findall(prompt))
        focus = next((n for n in def_names(sn) if n in words), None)
    f = analyze(sn, focus)
    file = PurePath(sn.source).name
    first_call = f.calls[0][0] if f.calls else (f.constants[0] if f.constants else "")
    ctx = {"name": f.name or f"lines {sn.start}-{sn.end}", "file": file, "start": sn.start,
           "end": sn.end, "call": first_call or file}
    if prompt is None:
        intent = rng.choice(["explain", "explain", "review", "bug", "errors"])
        if intent == "errors" and not first_call:
            intent = "explain"
        prompt = rng.choice(PROMPTS[intent]).format(**ctx)
    else:
        intent = detect_intent(prompt)
    ex = Exchange(prompt)
    named = f"`{f.name}`" if f.name else "that code"
    ex.items.append(("text", rng.choice(INTROS).format(file=file, name=named)))
    pattern = first_call or f.name
    if pattern and rng.random() < 0.4:
        hits = _count_matches(lib, sn.source, pattern)
        if hits:
            ex.items.append(("search", pattern, sn.source, hits))
    ex.items.append(("read", sn))
    ex.items.extend(_answer(f, sn, file, intent, rng))
    # review / bug / error questions usually end with a (pretend) edit, like Claude Code does
    if intent != "explain" and f.issues and rng.random() < 0.85:
        mentioned = re.findall(r"`([^`]+)`", " ".join(f.issues))
        diff = make_diff(sn, rng, prefer=mentioned)
        if diff is not None:
            ex.items.append(("text", rng.choice(FIX_INTROS)))
            ex.items.append(("update", diff, sn.lexer))
            ex.items.append(("text", rng.choice(FIX_DONE).format(file=file)))
    return ex


def make_session(lib: CodeLibrary, seed: int, count: int = 30) -> list[Exchange]:
    rng = random.Random(seed)
    return [make_exchange(lib, rng) for _ in range(count)]
