"""Colors, glyphs and font levels (styled after the Claude Code CLI)."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Theme:
    name: str
    label: str
    bg: str
    text: str       # main text (novel)
    bright: str     # headings / title
    dim: str        # secondary gray
    faint: str      # placeholder / line numbers
    rule: str       # input box rules
    accent: str     # mascot / spinner (claude orange)
    ok: str         # tool-call dot
    error: str
    warn: str
    auto: str       # "auto mode on"
    plan: str       # "plan mode on"
    edits: str      # "accept edits on"
    inline: str     # `inline code` in answers
    diff_add: str   # background of + lines
    diff_del: str   # background of - lines
    diff_add_fg: str  # line number / + marker
    diff_del_fg: str  # line number / - marker
    lineno: str     # line numbers of unchanged code
    code: str       # plain code text
    code_theme: str


THEMES = {
    # Colors sampled from the Claude Code CLI (dark theme on Windows Terminal)
    "claude": Theme("claude", "Claude dark", bg="#0c0c0c", text="#cccccc", bright="#f2f2f2",
                    dim="#999999", faint="#666666", rule="#888888", accent="#d77757",
                    ok="#4eba65", error="#ff6b80", warn="#ffc107", auto="#ffc107",
                    plan="#48968c", edits="#af87ff", inline="#b1b9f9", diff_add="#022800", diff_del="#3d0100",
                    diff_add_fg="#50c850", diff_del_fg="#dc5a5a", lineno="#7c7c79", code="#f8f8f2",
                    code_theme="claude"),
    "mono": Theme("mono", "Monochrome", bg="#000000", text="#d0d0d0", bright="#ffffff",
                  dim="#8a8a8a", faint="#6c6c6c", rule="#6c6c6c", accent="#bcbcbc",
                  ok="#bcbcbc", error="#ffffff", warn="#e4e4e4", auto="#e4e4e4",
                  plan="#bcbcbc", edits="#bcbcbc", inline="#e4e4e4", diff_add="#2e4a2e", diff_del="#4a2e2e",
                  diff_add_fg="#d0d0d0", diff_del_fg="#8a8a8a", lineno="#6c6c6c", code="#d0d0d0",
                  code_theme="bw"),
    "retro": Theme("retro", "Retro green", bg="#050a05", text="#b8e6b8", bright="#d7ffd7",
                   dim="#6f9f6f", faint="#4f7f4f", rule="#3f6f3f", accent="#87ff87",
                   ok="#5fff87", error="#ff8787", warn="#d7d787", auto="#d7d787",
                   plan="#87d7af", edits="#87d7d7", inline="#87d7d7", diff_add="#1f4f1f", diff_del="#5f1f1f",
                   diff_add_fg="#87ff87", diff_del_fg="#ff8787", lineno="#4f7f4f", code="#b8e6b8",
                   code_theme="native"),
}
THEME_ORDER = list(THEMES)


def get_theme(name: str) -> Theme:
    return THEMES.get(name, THEMES["claude"])


# Claude Code mascot (3 rows, 9 cells wide)
MASCOT_UNICODE = [" ▐▛███▜▌", "▝▜█████▛▘", "  ▘▘ ▝▝"]
MASCOT_ASCII = [" [o___o]", "<|#####|>", "  '' ''"]

GLYPHS_UNICODE = {
    "dot": "●", "branch": "⎿", "prompt": "❯", "rule": "─", "sep": "·",
    "spin": ["·", "✢", "✳", "✶", "✻", "✽", "✽", "✻", "✶", "✳", "✢", "·"],
    "effort": {"low": "○", "medium": "◐", "high": "●"},
    "auto": "⏵⏵", "plan": "⏸", "edits": "⏵⏵", "mascot": MASCOT_UNICODE,
}
GLYPHS_ASCII = {
    "dot": "*", "branch": "`-", "prompt": ">", "rule": "-", "sep": "-",
    "spin": [".", "o", "O", "o"],
    "effort": {"low": "o", "medium": "O", "high": "@"},
    "auto": ">>", "plan": "||", "edits": ">>", "mascot": MASCOT_ASCII,
}

# Terminals such as Windows Terminal do not let a program change the font, so the
# "font size" is simulated with column width and paragraph spacing; on the classic
# conhost window the real font height (px) is also changed.
FONT_LEVELS = {
    1: {"width": 140, "spacing": 0, "px": 12},
    2: {"width": 116, "spacing": 0, "px": 14},
    3: {"width": 96, "spacing": 0, "px": 16},
    4: {"width": 78, "spacing": 0, "px": 20},
    5: {"width": 62, "spacing": 0, "px": 24},
}

# /effort presets: how much "terminal work" is mixed into the novel
EFFORT_RATIOS = {
    "low": {"novel": 80, "work": 6, "code": 12, "status": 2},
    "medium": {"novel": 62, "work": 10, "code": 24, "status": 4},
    "high": {"novel": 48, "work": 12, "code": 35, "status": 5},
}

# Shift+Tab cycles the footer mode label (cosmetic, like Claude Code)
FOOTER_MODES = ["auto", "plan", "edits", "default"]


def clamp_font(value) -> int:
    try:
        return max(1, min(5, int(value)))
    except (TypeError, ValueError):
        return 3
