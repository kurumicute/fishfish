"""內容混排：依比例把工作訊息、程式碼片段、狀態紀錄分散插入段落之間。

小說段落本身永遠完整保留、順序不變；插入物只出現在段落邊界。
比例以「顯示行數」計算。
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

from rich.cells import cell_len

from core.code_loader import CodeLibrary, Snippet
from core.fake_diff import FakeDiff, make_diff
from core.models import Chapter
from core.terminal_engine import TerminalEngine


DIFF_SHARE = 0.35   # share of code blocks rendered as a fake Update diff


@dataclass
class Block:
    kind: str                       # title | para | work | code | status
    text: str = ""
    para: int = 0                   # para：段落索引；插入物：其後第一個段落索引
    steps: list[str] = field(default_factory=list)
    done: str = ""
    snippet: Snippet | None = None
    diff: FakeDiff | None = None


def extra_lines(block: Block, spacing: int) -> int:
    gap = 2   # one empty line before and after each block
    if block.kind == "work":
        return 2 + len(block.steps) + gap
    if block.kind == "code":
        return 1 + len(block.snippet.lines) + gap if block.snippet else 0
    if block.kind == "diff":
        return 2 + len(block.diff.rows) + gap if block.diff else 0
    return 1 + gap


def estimate_novel_lines(chapter: Chapter, width: int, spacing: int) -> int:
    width = max(10, width)
    return sum(max(1, math.ceil(cell_len(p) / width)) + spacing for p in chapter.paragraphs)


def mix_chapter(chapter: Chapter, *, width: int, ratio: dict, mode: str, code_lib: CodeLibrary,
                engine: TerminalEngine, rng: random.Random, spacing: int = 1) -> list[Block]:
    blocks = [Block("title", chapter.title, para=0)]
    paras = [Block("para", text, para=i) for i, text in enumerate(chapter.paragraphs)]
    if mode != "mixed" or not paras:
        return blocks + paras

    novel_lines = estimate_novel_lines(chapter, width, spacing)
    novel_share = max(1, ratio.get("novel", 78))

    def make(kind: str) -> Block | None:
        if kind == "work":
            title, steps, done = engine.random_task(rng)
            return Block("work", title, steps=steps, done=done)
        if kind == "code":
            snippet = code_lib.pick(rng)
            if snippet is None:
                return None
            # some code blocks are shown as a (pretend) edit with red - / green + lines
            if rng.random() < DIFF_SHARE:
                diff = make_diff(snippet, rng)
                if diff is not None:
                    return Block("diff", text=snippet.lexer, diff=diff)
            return Block("code", snippet=snippet)
        return Block("status", engine.random_status(rng, chapter.char_count, len(paras)))

    extras: list[Block] = []
    for kind in ("work", "code", "status"):
        budget = novel_lines * ratio.get(kind, 0) / novel_share
        used = 0.0
        guard = 0
        while used < budget and guard < 500:
            guard += 1
            block = make(kind)
            if block is None:
                break
            size = extra_lines(block, spacing)
            if size <= 0:
                break
            # 最後一個區塊以機率決定，讓長期平均貼近設定比例
            if used + size > budget and rng.random() > (budget - used) / size:
                break
            extras.append(block)
            used += size
        # short chapters: still show at least one real code snippet when code is enabled
        if kind == "code" and ratio.get("code", 0) > 0 and not any(b.kind in ("code", "diff") for b in extras):
            block = make("code")
            if block is not None:
                extras.append(block)

    if not extras:
        return blocks + paras
    rng.shuffle(extras)

    # 章節開頭的工作訊息最自然，若有工作區塊則放在第一個位置
    first_work = next((i for i, b in enumerate(extras) if b.kind == "work"), None)
    if first_work is not None:
        extras.insert(0, extras.pop(first_work))

    count = len(paras)
    k = len(extras)
    positions = []
    for j in range(k):
        if j == 0 and extras[0].kind == "work":
            positions.append(0)
            continue
        pos = int((j + rng.uniform(0.2, 0.8)) * count / k)
        positions.append(min(max(1, pos), count))

    slots: dict[int, list[Block]] = {}
    for pos, block in zip(positions, extras):
        block.para = pos
        slots.setdefault(pos, []).append(block)

    out = blocks
    for i, para in enumerate(paras):
        out.extend(slots.get(i, []))
        out.append(para)
    out.extend(slots.get(count, []))
    return out


def count_kind_lines(blocks: list[Block], width: int, spacing: int) -> dict[str, int]:
    """估算各類型行數（測試與 /ratio 顯示用）。"""
    result = {"novel": 0, "work": 0, "code": 0, "status": 0}
    for b in blocks:
        if b.kind == "para":
            result["novel"] += max(1, math.ceil(cell_len(b.text) / max(10, width))) + spacing
        elif b.kind in ("work", "code", "status", "diff"):
            result["code" if b.kind == "diff" else b.kind] += extra_lines(b, spacing)
    return result
