"""Screen composition, styled after the Claude Code CLI:

    mascot + title / model / cwd          (header)
    transcript area (novel + mixed blocks)
    status row: spinner / notice  ......  ◐ medium · /effort
    ──────────────────────────────────────
    ❯ input
    ──────────────────────────────────────
      ⏵⏵ auto mode on (shift+tab to cycle) · ← for agents      progress

Every row is padded to the full width with the theme background and the frame
height is fixed, so rich Live redraws in place without flicker or jumping.
"""
from __future__ import annotations

from dataclasses import dataclass

from rich.cells import cell_len
from rich.console import Console, Group
from rich.style import Style
from pygments.token import Comment, Generic, Keyword, Name, Number, Operator, String, Token
from rich.syntax import ANSISyntaxTheme, Syntax
from rich.text import Span, Text

from core.content_mixer import Block
from core.models import Chapter
from core.reader import RenderedChapter
from core.terminal_engine import StatusSnapshot
from ui.theme import FONT_LEVELS, Theme

INDENT = 2

# Syntax colors used by Claude Code (Monokai Extended), sampled from a real Claude Code diff.
CLAUDE_SYNTAX = ANSISyntaxTheme({
    Token: Style(color="#f8f8f2"),
    Keyword: Style(color="#f92672"),                       # if / return / else / import
    Keyword.Declaration: Style(color="#66d9ef"),
    Keyword.Type: Style(color="#66d9ef"),     # int / void / uint8_t
    Keyword.Constant: Style(color="#be84ff"),              # None / True / NULL
    Keyword.Namespace: Style(color="#f92672"),
    Operator: Style(color="#f92672"),
    Operator.Word: Style(color="#f92672"),                 # and / or / not / is / in
    Name.Function: Style(color="#a6e22e"),                 # function names
    Name.Class: Style(color="#a6e22e"),
    Name.Decorator: Style(color="#a6e22e"),
    Name.Exception: Style(color="#a6e22e"),
    Name.Builtin: Style(color="#66d9ef"),
    Name.Builtin.Pseudo: Style(color="#fd971f"),   # self / this
    Name.Constant: Style(color="#be84ff"),
    Name.Tag: Style(color="#f92672"),
    Name.Attribute: Style(color="#a6e22e"),
    String: Style(color="#e6db74"),
    String.Escape: Style(color="#be84ff"),
    Number: Style(color="#be84ff"),
    Comment: Style(color="#75715e"),
    Comment.Preproc: Style(color="#f92672"),               # #include / #define
    Comment.PreprocFile: Style(color="#e6db74"),
    Generic.Inserted: Style(color="#a6e22e"),
    Generic.Deleted: Style(color="#f92672"),
})

# 避頭（不可出現在行首）與避尾（不可出現在行尾）標點
NO_START = set("，。、；：？！）」』】〉》〕｝…—～・·,.;:?!)]}%")
NO_END = set("（「『【〈《〔｛([{")


def cjk_wrap(text: str, width: int) -> list[str]:
    """Greedy wrap by cell width with CJK line-breaking rules; content is unchanged."""
    lines: list[str] = []
    cur, w = "", 0
    for ch in text:
        cw = cell_len(ch)
        if w + cw > width and cur:
            k = 0
            if ch in NO_START or cur[-1] in NO_END:
                # 往前多帶幾個字到下一行，直到新行開頭不是避頭標點、上一行結尾不是避尾標點
                k = 1
                while k < min(4, len(cur) - 1) and (cur[-k] in NO_START or cur[-k - 1] in NO_END):
                    k += 1
                if k >= len(cur) or cur[-k] in NO_START or cur[-k - 1] in NO_END:
                    k = 0
            if k:
                carry = cur[-k:]
                lines.append(cur[:-k])
                cur, w = carry, cell_len(carry)
            else:
                lines.append(cur)
                cur, w = "", 0
        cur += ch
        w += cw
    lines.append(cur)
    return lines


def mostly_cjk(text: str) -> bool:
    letters = sum(1 for c in text if c.isascii() and c.isalpha())
    return letters < len(text) * 0.3


@dataclass
class Layout:
    width: int
    height: int
    header: int
    body: int
    status: int = 1
    input: int = 3
    footer: int = 1

    @property
    def prompt_row(self) -> int:
        """0-based screen row of the ❯ input line."""
        return self.height - self.footer - 2


class TerminalView:
    def __init__(self, console: Console, theme: Theme, glyphs: dict, header_cfg: dict) -> None:
        self.console = console
        self.theme = theme
        self.g = glyphs
        self.header_cfg = header_cfg

    # ---- sizes ---------------------------------------------------------
    def layout(self, width: int, height: int) -> Layout:
        # The header is part of the scrollable transcript (like Claude Code), not a fixed region.
        width = max(30, width)
        body = max(1, height - 1 - 3 - 1)
        return Layout(width, height, 0, body)

    @staticmethod
    def with_header(doc: RenderedChapter, header: list[Text]) -> RenderedChapter:
        """Prepend the header rows to a chapter so they scroll away with the text."""
        n = len(header)
        return RenderedChapter(header + doc.lines, [0] * n + doc.line_char, [False] * n + doc.line_is_para)

    def column_width(self, layout: Layout, font: int) -> int:
        level = FONT_LEVELS.get(font, FONT_LEVELS[3])
        return max(24, min(layout.width - 1, level["width"]))

    # ---- transcript rendering -------------------------------------------
    def render_blocks(self, blocks: list[Block], chapter: Chapter, width: int, spacing: int) -> RenderedChapter:
        t, g = self.theme, self.g
        lines: list[Text] = []
        chars: list[int] = []
        is_para: list[bool] = []
        inner = max(10, width - INDENT)
        pad = " " * INDENT

        def add(text: Text, char: int, para: bool = False) -> None:
            lines.append(text)
            chars.append(char)
            is_para.append(para)

        def blank(n: int, char: int) -> None:
            for _ in range(n):
                add(Text(""), char)

        def ensure_blank(char: int) -> None:
            # exactly one empty line between blocks (never several in a row)
            if lines and lines[-1].plain.strip():
                add(Text(""), char)

        def bullet(label: Text, char: int) -> None:
            row = Text()
            row.append(f"{g['dot']} ", style=t.ok)
            row.append_text(label)
            add(self._cut(row, width), char)

        def branch(first: bool, body: Text, char: int) -> None:
            row = Text(pad)
            row.append(f"{g['branch']}  " if first else " " * (len(g["branch"]) + 2), style=t.dim)
            row.append_text(body)
            add(self._cut(row, width), char)

        for block in blocks:
            next_char = chapter.offset_of(block.para)
            if block.kind == "title":
                title = Text(block.text, style=Style(color=t.bright, bold=True))
                for i, ln in enumerate(title.wrap(self.console, inner, overflow="fold")):
                    row = Text()
                    row.append(f"{g['dot']} " if i == 0 else pad, style=t.bright)
                    row.append_text(ln)
                    add(row, 0)
            elif block.kind == "para":
                consumed = 0
                base = chapter.offsets[block.para]
                if mostly_cjk(block.text):
                    wrapped = [Text(s, style=t.text) for s in cjk_wrap(block.text, inner)]
                else:
                    wrapped = list(Text(block.text, style=t.text).wrap(self.console, inner, overflow="fold"))
                for ln in wrapped:
                    row = Text(pad)
                    row.append_text(ln)
                    add(row, base + consumed, True)
                    consumed += len(ln.plain)
                blank(spacing, chapter.offset_of(block.para + 1))
            elif block.kind == "work":
                ensure_blank(next_char)
                bullet(Text(block.text, style=Style(color=t.bright, bold=True)), next_char)
                steps = [*block.steps, block.done]
                for i, step in enumerate(steps):
                    branch(i == 0, Text(step, style=t.dim), next_char)
                blank(1, next_char)
            elif block.kind == "code" and block.snippet:
                sn = block.snippet
                ensure_blank(next_char)
                head = Text()
                head.append("Read", style=Style(color=t.bright, bold=True))
                head.append(f"({sn.source})", style=t.text)
                bullet(head, next_char)
                count = len(sn.lines)
                summary = Text(f"Read {count} line{'s' if count != 1 else ''} (L{sn.start}-{sn.end})", style=t.dim)
                branch(True, summary, next_char)
                for i, code_line in enumerate(self._highlight(sn.lines, sn.lexer)):
                    body = Text()
                    body.append(f"{sn.start + i:>5} ", style=t.lineno)
                    body.append_text(code_line)
                    branch(False, body, next_char)
                blank(1, next_char)
            elif block.kind == "diff" and block.diff:
                ensure_blank(next_char)
                head = Text()
                head.append("Update", style=Style(color=t.bright, bold=True))
                head.append(f"({block.diff.source})", style=t.text)
                bullet(head, next_char)
                branch(True, Text(block.diff.summary, style=t.dim), next_char)
                for body in self.diff_rows(block.diff, block.text or "text", width):
                    branch(False, body, next_char)
                blank(1, next_char)
            elif block.kind == "status":
                ensure_blank(next_char)
                branch(True, Text(block.text, style=t.dim), next_char)
                blank(1, next_char)

        if not lines:
            add(Text(pad + "(empty chapter)", style=t.dim), 0)
        return RenderedChapter(lines, chars, is_para)

    # ---- Ctrl+Q cover transcript (code + simulated answers only) ---------
    def _inline_md(self, text: str, style: str) -> Text:
        """Plain text with `inline code` and **bold** rendered like Claude Code."""
        out = Text()
        for i, part in enumerate(text.split("`")):
            if i % 2:
                out.append(part, style=self.theme.inline)
                continue
            for j, chunk in enumerate(part.split("**")):
                out.append(chunk, style=Style(color=self.theme.bright, bold=True) if j % 2 else style)
        return out

    def render_cover(self, exchanges: list, width: int) -> list[Text]:
        t, g = self.theme, self.g
        pad = " " * INDENT
        inner = max(10, width - INDENT)
        out: list[Text] = []

        def para(first_prefix: Text, body: Text) -> None:
            for i, ln in enumerate(body.wrap(self.console, inner, overflow="fold")):
                row = first_prefix.copy() if i == 0 else Text(pad)
                row.append_text(ln)
                out.append(row)

        def tool(label: Text, lines: list[Text]) -> None:
            head = Text()
            head.append(f"{g['dot']} ", style=t.ok)
            head.append_text(label)
            out.append(self._cut(head, width))
            for i, body in enumerate(lines):
                row = Text(pad)
                row.append(f"{g['branch']}  " if i == 0 else " " * (len(g["branch"]) + 2), style=t.dim)
                row.append_text(body)
                out.append(self._cut(row, width))

        for ex in exchanges:
            if out:
                out.append(Text(""))
            para(Text("> ", style=t.dim), Text(ex.prompt, style=t.dim))
            for item in ex.items:
                out.append(Text(""))
                kind = item[0]
                if kind == "text":
                    para(Text(f"{g['dot']} ", style=t.bright), self._inline_md(item[1], t.text))
                elif kind in ("list", "bullets"):
                    if item[1]:
                        para(Text(f"{g['dot']} ", style=t.bright), self._inline_md(item[1], t.text))
                    for n, entry in enumerate(item[2], 1):
                        marker = f"{n}. " if kind == "list" else "- "
                        prefix = Text(pad if item[1] else f"{g['dot']} " if n == 1 else pad, style=t.bright)
                        prefix.append(marker, style=t.text)
                        para(prefix, self._inline_md(entry, t.text))
                elif kind == "search":
                    label = Text()
                    label.append("Search", style=Style(color=t.bright, bold=True))
                    label.append(f'(pattern: "{item[1]}", path: "{item[2]}")', style=t.text)
                    tool(label, [Text(f"Found {item[3]} matches", style=t.dim)])
                elif kind == "update":
                    diff, lexer = item[1], item[2]
                    label = Text()
                    label.append("Update", style=Style(color=t.bright, bold=True))
                    label.append(f"({diff.source})", style=t.text)
                    tool(label, [Text(diff.summary, style=t.dim), *self.diff_rows(diff, lexer, width)])
                elif kind == "read":
                    sn = item[1]
                    label = Text()
                    label.append("Read", style=Style(color=t.bright, bold=True))
                    label.append(f"({sn.source})", style=t.text)
                    body = [Text(f"Read {len(sn.lines)} lines (L{sn.start}-{sn.end})", style=t.dim)]
                    for i, code_line in enumerate(self._highlight(sn.lines, sn.lexer)):
                        row = Text()
                        row.append(f"{sn.start + i:>5} ", style=t.lineno)
                        row.append_text(code_line)
                        body.append(row)
                    tool(label, body)
        return out

    def diff_rows(self, diff, lexer: str, width: int) -> list[Text]:
        """Rows of a fake Update block, styled like a real Claude Code diff:
        removed lines are plain text on dark red, added lines are highlighted on dark green,
        unchanged lines are highlighted without a background."""
        t = self.theme
        texts = self._highlight([text for _, _, text in diff.rows], lexer)
        num_w = max(len(str(num)) for _, num, _ in diff.rows)
        avail = max(1, width - INDENT - len(self.g["branch"]) - 2)
        out = []
        for (kind, num, raw), code in zip(diff.rows, texts):
            color = {"+": t.diff_add_fg, "-": t.diff_del_fg}.get(kind, t.lineno)
            row = Text()
            row.append(f"{num:>{num_w}} {kind} ", style=color)
            row.append_text(Text(raw, style=t.code) if kind == "-" else code)
            if kind != " ":
                row.truncate(avail, overflow="ellipsis", pad=True)
                row.stylize(Style(bgcolor=t.diff_add if kind == "+" else t.diff_del))
            out.append(row)
        return out

    def _highlight(self, code_lines: list[str], lexer: str) -> list[Text]:
        code = "\n".join(code_lines)
        try:
            theme = CLAUDE_SYNTAX if self.theme.code_theme == "claude" else self.theme.code_theme
            syntax = Syntax(code, lexer, theme=theme, background_color=self.theme.bg)
            text = syntax.highlight(code)
            text.rstrip()
            result = list(text.split("\n", allow_blank=True))
            # keep only foreground / weight from the syntax theme (no theme background patches)
            for line in result:
                line.style = Style(color=self.theme.code)    # plain identifiers (#f8f8f2 in Claude Code)
                line.spans = [Span(sp.start, sp.end, self._fg_only(sp.style)) for sp in line.spans]
        except Exception:
            result = [Text(ln, style=self.theme.dim) for ln in code_lines]
        while len(result) < len(code_lines):
            result.append(Text(""))
        return result[: len(code_lines)]

    @staticmethod
    def _fg_only(style) -> Style:
        st = Style.parse(style) if isinstance(style, str) else style
        return Style(color=st.color, bold=st.bold, underline=st.underline, dim=st.dim)

    @staticmethod
    def _cut(text: Text, width: int) -> Text:
        text.truncate(width, overflow="ellipsis")
        return text

    # ---- screen regions ---------------------------------------------------
    def header_rows(self, lay: Layout, cwd: str) -> list[Text]:
        t, cfg = self.theme, self.header_cfg
        mascot = self.g["mascot"]
        texts = [Text(), Text(cfg.get("model", ""), style=t.dim), Text(cwd, style=t.dim)]
        texts[0].append(cfg.get("title", "Claude Code"), style=Style(color=t.bright, bold=True))
        version = cfg.get("version", "")
        if version:
            texts[0].append(f" {version}", style=t.dim)
        rows = []
        for art, text in zip(mascot, texts):
            row = Text(art.ljust(9), style=t.accent)
            row.append("  ")
            row.append_text(text)
            rows.append(row)
        rows.append(Text(""))
        return rows

    def status_row(self, lay: Layout, snap: StatusSnapshot, effort: str) -> Text:
        t, g = self.theme, self.g
        left = Text()
        if snap.state == "running":
            spin = g["spin"][snap.spin % len(g["spin"])]
            left.append(f"{spin} ", style=t.accent)
            left.append(f"{snap.title}…", style=t.accent)
            left.append(f" ({snap.elapsed}s · esc to interrupt)", style=t.dim)
        elif snap.state != "idle" and snap.title:
            color = {"error": t.error, "warn": t.warn}.get(snap.state, t.dim)
            left.append(f"{' ' * INDENT}{g['branch']}  ", style=t.dim)
            left.append(snap.title, style=color)
            if snap.detail:
                left.append(f" {g['sep']} {snap.detail}", style=t.faint)
        right = Text(f"{g['effort'].get(effort, g['effort']['medium'])} {effort} {g['sep']} /effort  ", style=t.dim)
        return self._split(left, right, lay.width)

    def input_rows(self, lay: Layout, buffer: str, placeholder: str, show_fake_cursor: bool) -> tuple[list[Text], int]:
        """Return (rows, cursor column) for the input box."""
        t, g = self.theme, self.g
        rule = Text(g["rule"] * lay.width, style=t.rule)
        prompt = Text()
        prompt.append(f"{g['prompt']} ", style=t.text)
        prefix = cell_len(prompt.plain)
        room = lay.width - prefix - 1
        if buffer:
            shown = buffer
            while cell_len(shown) > room and shown:
                shown = shown[1:]
            prompt.append(shown, style=t.text)
            cursor = prefix + cell_len(shown)
            if show_fake_cursor:
                prompt.append(" ", style=Style(reverse=True))
        else:
            cursor = prefix
            if show_fake_cursor and placeholder:
                prompt.append(placeholder[0], style=Style(color=t.faint, reverse=True))
                prompt.append(placeholder[1:], style=t.faint)
            else:
                prompt.append(placeholder, style=t.faint)
        return [rule, prompt, rule.copy()], cursor

    def footer_row(self, lay: Layout, mode: str, info: str) -> Text:
        t, g = self.theme, self.g
        left = Text(" " * INDENT)
        if mode == "default":
            left.append("? for shortcuts", style=t.dim)
        else:
            label = {"auto": "auto mode on", "plan": "plan mode on", "edits": "accept edits on"}[mode]
            color = {"auto": t.auto, "plan": t.plan, "edits": t.edits}[mode]
            left.append(f"{g[mode]} {label}", style=color)
            left.append(" (shift+tab to cycle)", style=t.dim)
        left.append(f" {g['sep']} ← for agents", style=t.dim)
        right = Text(f"{info}  " if info else "", style=t.faint)
        return self._split(left, right, lay.width)

    def body_rows(self, lines: list[Text], height: int) -> list[Text]:
        rows = list(lines[:height])
        while len(rows) < height:
            rows.append(Text(""))
        return rows

    @staticmethod
    def _split(left: Text, right: Text, width: int) -> Text:
        """Left-aligned text with right-aligned text on the same row."""
        rlen = cell_len(right.plain)
        if rlen >= width - 10:
            right = Text("")
            rlen = 0
        left.truncate(max(0, width - rlen), overflow="ellipsis", pad=True)
        left.append_text(right)
        return left

    def compose(self, lay: Layout, rows: list[Text]) -> Group:
        base = Style(color=self.theme.text, bgcolor=self.theme.bg)
        out = []
        for row in rows[: lay.height]:
            line = Text(style=base, no_wrap=True, overflow="ellipsis")
            line.append_text(row)
            line.truncate(lay.width, overflow="ellipsis", pad=True)
            out.append(line)
        while len(out) < lay.height:
            out.append(Text(" " * lay.width, style=base, no_wrap=True))
        return Group(*out)
