"""Slash-command parsing and dispatch."""
from __future__ import annotations

from typing import TYPE_CHECKING

from core.config import MIN_NOVEL_PERCENT, RATIO_KEYS
from ui.theme import EFFORT_RATIOS, THEME_ORDER, THEMES

if TYPE_CHECKING:
    from ui.app import App

HELP = [
    ("/open [path|number]", "Open a novel (TXT / EPUB); no argument lists recent files"),
    ("/code [path ...|off|default]", "Code reference files/folders; several paths with ; or quotes (never executed)"),
    ("/code add <path>", "Add another code file or folder to the current source"),
    ("/next", "Next chapter"),
    ("/prev", "Previous chapter"),
    ("/continue", "Scroll down one screen (continues into the next chapter)"),
    ("/progress", "Show reading progress"),
    ("/toc", "List chapters"),
    ("/goto <number>", "Jump to chapter"),
    ("/font [1-5|+|-]", "Font size (column width and line spacing)"),
    ("/ratio [novel work code status]", "Content ratio, e.g. /ratio 78 12 7 3, /ratio code 10, /ratio reset"),
    ("/effort [low|medium|high]", "Preset ratio: how much terminal work is mixed in"),
    ("/mode [mixed|reading]", "Mixed terminal mode / pure reading mode"),
    ("/theme [claude|mono|retro]", "Switch color theme"),
    ("/log", "Show work log"),
    ("/clear", "Clear screen and work log"),
    ("/help", "Show commands"),
    ("/quit", "Save progress and exit"),
]
KEYS = [
    ("Up / Down", "Scroll one line (command history while typing)"),
    ("Mouse wheel", "Scroll three lines"),
    ("PageUp / PageDown", "Scroll one screen"),
    ("Left / Right", "Jump to previous / next chapter (when input is empty)"),
    ("Home / End", "Start / end of chapter"),
    ("Tab", "Complete command"),
    ("Shift+Tab", "Cycle footer mode"),
    ("?", "Show shortcuts (when input is empty)"),
    ("Esc", "Clear input, close panel, interrupt"),
    ("Ctrl+Q", "Toggle code-only view (press again to return)"),
    ("Ctrl+C", "Save progress and exit"),
]
COMMAND_NAMES = ["/open", "/code", "/next", "/prev", "/continue", "/progress", "/toc", "/goto",
                 "/font", "/ratio", "/effort", "/mode", "/theme", "/log", "/clear", "/help", "/quit", "/exit"]
RATIO_ALIASES = {"novel": "novel", "work": "work", "code": "code", "status": "status"}


def strip_quotes(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        value = value[1:-1]
    return value.strip()


def complete(prefix: str) -> str:
    if not prefix.startswith("/") or " " in prefix:
        return prefix
    matches = [c for c in COMMAND_NAMES if c.startswith(prefix.lower())]
    if len(matches) == 1:
        return matches[0] + " "
    return prefix


class CommandHandler:
    def __init__(self, app: "App") -> None:
        self.app = app
        self.table = {
            "open": self.cmd_open, "code": self.cmd_code, "next": self.cmd_next,
            "prev": self.cmd_prev, "continue": self.cmd_continue, "progress": self.cmd_progress,
            "toc": self.cmd_toc, "goto": self.cmd_goto, "font": self.cmd_font,
            "ratio": self.cmd_ratio, "effort": self.cmd_effort, "mode": self.cmd_mode,
            "theme": self.cmd_theme, "log": self.cmd_log, "clear": self.cmd_clear,
            "help": self.cmd_help, "quit": self.cmd_quit, "exit": self.cmd_quit,
        }

    def execute(self, line: str) -> None:
        line = line.strip()
        if not line:
            return
        if not line.startswith("/"):
            self.app.notify("Commands start with /", "info", "type /help for available commands")
            return
        name, _, arg = line[1:].partition(" ")
        handler = self.table.get(name.lower())
        if handler is None:
            self.app.notify(f"Unknown command: /{name}", "warn", "type /help for available commands")
            return
        handler(arg.strip())

    # ---- commands ------------------------------------------------------
    def cmd_open(self, arg: str) -> None:
        arg = strip_quotes(arg)
        if not arg:
            self.app.show_recent()
            return
        if arg.isdigit() and not self.app.path_exists(arg):
            recent = self.app.pm.recent(20)
            idx = int(arg) - 1
            if 0 <= idx < len(recent):
                arg = recent[idx]["file_path"]
            else:
                self.app.notify(f"No recent file #{arg}", "warn")
                return
        self.app.open_book(arg)

    def cmd_code(self, arg: str) -> None:
        if arg.lower().startswith("add "):
            self.app.add_code_source(arg[4:].strip())
            return
        if arg.count('"') <= 2:
            arg = strip_quotes(arg)
        if not arg:
            self.app.show_code_info()
        elif arg.lower() == "off":
            self.app.set_code_source("off")
        elif arg.lower() == "default":
            self.app.set_code_source("")
        else:
            self.app.set_code_source(arg)

    def cmd_next(self, arg: str) -> None:
        self.app.change_chapter(+1)

    def cmd_prev(self, arg: str) -> None:
        self.app.change_chapter(-1)

    def cmd_continue(self, arg: str) -> None:
        self.app.page(+1)

    def cmd_progress(self, arg: str) -> None:
        self.app.show_progress()

    def cmd_toc(self, arg: str) -> None:
        self.app.show_toc()

    def cmd_goto(self, arg: str) -> None:
        if not arg.isdigit():
            self.app.notify("Usage: /goto <chapter number>", "warn")
            return
        self.app.goto_chapter(int(arg) - 1)

    def cmd_font(self, arg: str) -> None:
        current = self.app.font
        if not arg:
            self.app.notify(f"Font size: {current} (range 1-5)", "info", "usage: /font 4, /font +, /font -")
            return
        if arg in ("+", "-"):
            value = current + (1 if arg == "+" else -1)
        elif arg.isdigit():
            value = int(arg)
        else:
            self.app.notify("Usage: /font [1-5|+|-]", "warn")
            return
        if not 1 <= value <= 5:
            self.app.notify("Font size must be between 1 and 5", "warn")
            return
        self.app.set_font(value)

    def cmd_ratio(self, arg: str) -> None:
        parts = arg.split()
        current = dict(self.app.ratio)
        if not parts:
            self.app.notify(self.app.ratio_text(), "info", "usage: /ratio 78 12 7 3, /ratio code 10, /ratio reset")
            return
        if parts[0].lower() == "reset":
            self.app.set_ratio(dict(self.app.cfg["ratio"]))
            return
        try:
            if len(parts) == 4:
                new = {k: float(v) for k, v in zip(RATIO_KEYS, parts)}
            elif len(parts) == 2 and parts[0].lower() in RATIO_ALIASES:
                key = RATIO_ALIASES[parts[0].lower()]
                value = float(parts[1])
                if key == "novel":
                    self.app.notify("Adjust work / code / status; novel takes the remainder", "warn")
                    return
                if not 0 <= value <= 100:
                    raise ValueError
                new = dict(current)
                new[key] = value
                new["novel"] = 100 - sum(new[k] for k in RATIO_KEYS if k != "novel")
            else:
                raise ValueError
        except ValueError:
            self.app.notify("Invalid ratio", "warn", "usage: /ratio 78 12 7 3 or /ratio code 10")
            return
        if any(v < 0 for v in new.values()) or sum(new.values()) <= 0:
            self.app.notify("Ratio values cannot be negative", "warn")
            return
        if new["novel"] * 100 / sum(new.values()) < MIN_NOVEL_PERCENT:
            self.app.notify(f"Novel share cannot be below {MIN_NOVEL_PERCENT}%", "warn")
            return
        self.app.set_ratio(new)

    def cmd_effort(self, arg: str) -> None:
        arg = arg.lower()
        order = list(EFFORT_RATIOS)
        if not arg:
            idx = order.index(self.app.effort) if self.app.effort in order else 0
            arg = order[(idx + 1) % len(order)]
        if arg not in EFFORT_RATIOS:
            self.app.notify("Usage: /effort [low|medium|high]", "warn")
            return
        self.app.set_effort(arg)

    def cmd_mode(self, arg: str) -> None:
        arg = arg.lower()
        if not arg:
            arg = "reading" if self.app.mode == "mixed" else "mixed"
        aliases = {"mixed": "mixed", "reading": "reading", "read": "reading"}
        if arg not in aliases:
            self.app.notify("Usage: /mode [mixed|reading]", "warn")
            return
        self.app.set_mode(aliases[arg])

    def cmd_theme(self, arg: str) -> None:
        arg = arg.lower()
        if not arg:
            idx = THEME_ORDER.index(self.app.theme_name) if self.app.theme_name in THEME_ORDER else -1
            arg = THEME_ORDER[(idx + 1) % len(THEME_ORDER)]
        if arg not in THEMES:
            self.app.notify(f"Unknown theme: {arg}", "warn", "available: " + ", ".join(THEME_ORDER))
            return
        self.app.set_theme(arg)

    def cmd_log(self, arg: str) -> None:
        self.app.show_log()

    def cmd_clear(self, arg: str) -> None:
        self.app.clear_screen()

    def cmd_help(self, arg: str) -> None:
        self.app.show_help()

    def cmd_quit(self, arg: str) -> None:
        self.app.quit()
