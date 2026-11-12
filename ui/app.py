"""Main controller: event loop, key handling, background loading, progress saving."""
from __future__ import annotations

import os
import random
import sys
import threading
import time
import zlib
from dataclasses import dataclass
from pathlib import Path

from rich.console import Console
from rich.style import Style
from rich.text import Text

from core.code_loader import CodeLibrary, load_builtin_library, load_code_sources, split_paths
from core.cover import make_exchange, make_session
from core.config import normalize_ratio
from core.config import load_config
from core.content_mixer import count_kind_lines, mix_chapter
from core.models import Book, NovelLoadError
from core.novel_parser import load_book
from core.progress_manager import ProgressManager
from core.reader import Reader
from core.terminal_engine import CHAPTER_TASK, OPEN_TASK, TerminalEngine
from database.database import Database
from ui.command_handler import HELP, KEYS, CommandHandler, complete
from ui.console_font import ConsoleFont
from ui.terminal_view import TerminalView
from ui.theme import (EFFORT_RATIOS, FONT_LEVELS, FOOTER_MODES, GLYPHS_ASCII, GLYPHS_UNICODE,
                      clamp_font, get_theme)

AUTOSAVE_SECONDS = 1.5
WHEEL_LINES = 3


@dataclass
class Overlay:
    title: str
    lines: list
    offset: int = 0


def display_cwd() -> str:
    cwd = Path.cwd()
    try:
        rel = cwd.relative_to(Path.home())
        return "~" if str(rel) == "." else str(Path("~") / rel)
    except ValueError:
        return str(cwd)


class App:
    def __init__(self, base_dir: Path, console: Console, *, db_path=None, interactive: bool = True) -> None:
        self.base_dir = Path(base_dir)
        # bundled read-only resources (project source used as the built-in code source)
        self.resource_dir = Path(getattr(sys, "_MEIPASS", self.base_dir))
        self.console = console
        self.interactive = interactive
        self.cfg, cfg_error = load_config(self.base_dir / "config" / "settings.json")
        self.db = Database(db_path or (self.base_dir / "data" / "progress.db"))
        self.pm = ProgressManager(self.db)

        saved = self.pm.get_settings()
        self.ratio = normalize_ratio(saved.get("ratio") or self.cfg["ratio"])
        self.mode = saved.get("mode") if saved.get("mode") in ("mixed", "reading") else self.cfg["mode"]
        self.font = clamp_font(saved.get("font_size", self.cfg["font_size"]))
        self.theme_name = saved.get("theme") or self.cfg["theme"]
        self.code_setting = saved.get("code_path", "") or ""
        effort = saved.get("effort") or self.cfg.get("effort", "medium")
        self.effort = effort if effort in EFFORT_RATIOS else "medium"
        footer = saved.get("footer_mode") or self.cfg.get("footer_mode", "auto")
        self.footer_mode = footer if footer in FOOTER_MODES else "auto"

        self.glyphs = GLYPHS_ASCII if self.cfg.get("ascii_glyphs") else GLYPHS_UNICODE
        self.view = TerminalView(console, get_theme(self.theme_name), self.glyphs, self.cfg["header"])
        self.cwd_text = self.cfg["header"].get("cwd") or display_cwd()
        placeholders = self.cfg.get("placeholders") or ['Try "fix lint errors"']
        self.placeholder = placeholders[0]
        amb = self.cfg["ambient"]
        self.engine = TerminalEngine(self.cfg["language"], amb["min_interval"], amb["max_interval"])
        self.engine.ambient_enabled = self.mode == "mixed"
        self.reader = Reader()
        self.code_lib = CodeLibrary()
        self.commands = CommandHandler(self)
        self.font_ctl = ConsoleFont() if interactive else None

        self.input_buf = ""
        self.history: list[str] = []
        self.hist_idx: int | None = None
        self.overlay: Overlay | None = None
        self.job: dict | None = None
        self.running = True
        self._dirty = False
        self._last_save = 0.0
        self._size = None
        self._layout = None
        self._cursor = (0, 0)
        # Ctrl+Q cover view (code + simulated answers only)
        self.cover = False
        self.cover_exchanges: list | None = None
        self.cover_offset: int | None = None     # None = stick to the bottom
        self._cover_cache = (None, [])
        self._cover_rng = random.Random()

        for err in (cfg_error, self.db.error):
            if err:
                self.notify(err, "warn")
        self.set_code_source(self.code_setting, quiet=True)

    # ==== common ==========================================================
    @property
    def theme(self):
        return self.view.theme

    def notify(self, text: str, kind: str = "ok", detail: str = "") -> None:
        self.engine.notify(text, kind, detail)

    @staticmethod
    def path_exists(value: str) -> bool:
        return Path(os.path.expandvars(value)).expanduser().exists()

    def _save_global(self) -> None:
        for key, value in (("ratio", self.ratio), ("mode", self.mode), ("font_size", self.font),
                           ("theme", self.theme_name), ("code_path", self.code_setting),
                           ("effort", self.effort), ("footer_mode", self.footer_mode)):
            self.pm.set_setting(key, value)

    def save_progress(self, force: bool = False) -> None:
        book = self.reader.book
        if book is None or (not self._dirty and not force):
            return
        ok = self.pm.save(
            book, chapter=self.reader.current_chapter(), paragraph=self.reader.para_index(),
            char_pos=self.reader.char_pos(), font_size=self.font, ratio=self.ratio,
            code_path=self.code_setting, mode=self.mode,
        )
        self._dirty = False
        self._last_save = time.monotonic()
        if not ok and self.pm.last_error:
            self.notify(self.pm.last_error, "error")

    # ==== startup =========================================================
    def startup(self, file: str | None = None, code: str | None = None, *, sync: bool = False) -> None:
        if code:
            self.set_code_source(code)
        if file:
            self.open_book(file, sync=sync)
            return
        last = self.pm.get_settings().get("last_book")
        if last:
            if Path(last).exists():
                self.open_book(last, sync=sync)
            else:
                self.notify(f"Last file not found: {Path(last).name}", "warn",
                            "progress kept; restore the file to continue")
        else:
            self.notify("Type /open <filepath> to open a novel", "info", "? for shortcuts")

    # ==== open novel ======================================================
    def open_book(self, raw_path: str, *, sync: bool = False) -> None:
        if self.job is not None:
            self.notify("A document is still loading", "warn")
            return
        path = Path(os.path.expandvars(raw_path)).expanduser()
        if not path.exists():
            self.notify(f"File not found: {path.name}", "error", str(path))
            return
        self.save_progress(force=True)
        self.overlay = None
        self.engine.start_named(OPEN_TASK, external=True)
        novel_cfg = self.cfg["novel"]
        job = {"path": path, "book": None, "error": None, "done": False}

        def work() -> None:
            try:
                job["book"] = load_book(
                    path, max_file_mb=novel_cfg["max_file_mb"],
                    auto_section_chars=novel_cfg["auto_section_chars"],
                    max_chapter_chars=novel_cfg["max_chapter_chars"],
                )
            except NovelLoadError as exc:
                job["error"] = str(exc)
            except Exception as exc:  # never crash the UI on unexpected errors
                job["error"] = f"Failed to read file: {type(exc).__name__}: {exc}"
            job["done"] = True

        self.job = job
        if sync:
            work()
            self.poll_job()
        else:
            threading.Thread(target=work, daemon=True).start()

    def poll_job(self) -> bool:
        job = self.job
        if job is None or not job["done"]:
            return False
        self.job = None
        if job["error"]:
            self.engine.finish_external(False, job["error"])
            return True
        self._apply_book(job["book"])
        return True

    def _apply_book(self, book: Book) -> None:
        rec = self.pm.load(book.path)
        chapter, char_pos, note = 0, 0, ""
        if rec:
            if rec.get("font_size"):
                self.font = clamp_font(rec["font_size"])
            if rec.get("mode") in ("mixed", "reading"):
                self.mode = rec["mode"]
                self.engine.ambient_enabled = self.mode == "mixed"
            if rec.get("code_path") is not None and rec["code_path"] != self.code_setting:
                self.set_code_source(rec["code_path"], quiet=True)
            chapter = int(rec.get("chapter") or 0)
            char_pos = int(rec.get("char_pos") or 0)
            if chapter >= len(book.chapters):
                note = "file changed, moved to last chapter"
                chapter, char_pos = len(book.chapters) - 1, 0
            else:
                note = f"resumed at chapter {chapter + 1}"
        self.reader.set_book(book, chapter, char_pos)
        self.pm.set_setting("last_book", str(Path(book.path).resolve()))
        self._apply_font_px()
        self._dirty = True
        self.save_progress()
        detail = f"{book.fmt} · {book.encoding} · {len(book.chapters)} chapters · {book.total_chars:,} chars"
        self.engine.finish_external(True, f"Read {Path(book.path).name}",
                                    f"{detail} · {note}" if note else detail)

    # ==== code source ======================================================
    def set_code_source(self, setting: str, quiet: bool = False) -> None:
        code_cfg = self.cfg["code"]
        kwargs = dict(min_lines=code_cfg["min_lines"], max_lines=code_cfg["max_lines"],
                      max_file_mb=code_cfg["max_file_mb"])
        try:
            if setting == "off":
                lib = CodeLibrary(label="off")
            elif setting:
                lib = load_code_sources(split_paths(os.path.expandvars(setting)), **kwargs)
                setting = ";".join(lib.paths)
            else:
                lib = load_builtin_library(self.resource_dir, **kwargs)
        except NovelLoadError as exc:
            self.notify(str(exc), "error", "using built-in code source" if quiet else "code source unchanged")
            if quiet:
                self.code_lib = load_builtin_library(self.resource_dir, **kwargs)
                self.code_setting = ""
            return
        self.code_lib = lib
        self.code_setting = setting
        self.reader.invalidate()
        if not quiet:
            self._save_global()
            self._dirty = True
            if setting == "off":
                self.notify("Code snippets disabled", "ok")
            elif getattr(lib, "errors", None):
                self.notify(f"Code source: {lib.label}", "warn", f"skipped: {lib.errors[0]}")
            else:
                self.notify(f"Code source: {lib.label}", "ok",
                            f"{lib.file_count} files · {lib.line_count:,} lines · {len(lib.snippets)} snippets")

    def add_code_source(self, raw: str) -> None:
        """Add files / folders to the current code source (/code add)."""
        current = self.code_setting if self.code_setting not in ("", "off") else ""
        self.set_code_source(";".join(p for p in [current, *split_paths(raw)] if p))

    def show_code_info(self) -> None:
        lib = self.code_lib
        self.notify(f"Code source: {lib.label}", "info",
                    f"{lib.file_count} files · {len(lib.snippets)} snippets · /code <path>, /code off, /code default")

    # ==== reading ==========================================================
    def _need_book(self) -> bool:
        if self.reader.book is None:
            self.notify("No document open", "warn", "use /open <filepath>")
            return False
        return True

    def _chapter_changed(self) -> None:
        self._dirty = True
        self.save_progress()
        if self.mode == "mixed" and self.engine.active is None:
            self.engine.start_named(CHAPTER_TASK)

    def change_chapter(self, delta: int) -> None:
        if not self._need_book():
            return
        ok = self.reader.next_chapter() if delta > 0 else self.reader.prev_chapter()
        if ok:
            self.overlay = None
            self._chapter_changed()
        else:
            self.notify("Already at the last chapter" if delta > 0 else "Already at the first chapter", "info")

    def goto_chapter(self, index: int) -> None:
        if not self._need_book():
            return
        if self.reader.goto_chapter(index):
            self.overlay = None
            self._chapter_changed()
        else:
            self.notify(f"Chapter must be between 1 and {self.reader.chapter_count}", "warn")

    def page(self, direction: int) -> None:
        self.scroll(direction * max(1, self.reader.page_h - 1))

    def scroll(self, delta: int) -> None:
        """Continuous scrolling: chapters flow into each other."""
        if self.overlay:
            self._overlay_scroll(delta)
            return
        if self.cover:
            self._cover_scroll(delta)
            return
        if self.reader.book is None:
            return
        before = self.reader.current_chapter()
        if self.reader.scroll(delta):
            self._dirty = True
            if self.reader.current_chapter() != before:
                self._chapter_changed()
        elif delta > 0 and self.reader.at_end():
            self.notify("End of document", "info")

    def chapter_edge(self, end: bool) -> None:
        if self.cover and not self.overlay:
            self.cover_offset = None if end else 0
            return
        if self.overlay:
            self.overlay.offset = 0 if not end else max(0, len(self.overlay.lines) - self.reader.page_h)
        elif self.reader.book:
            self.reader.chapter_end() if end else self.reader.chapter_start()
            self._dirty = True

    # ==== settings ==========================================================
    def _apply_font_px(self) -> None:
        if self.font_ctl and self.font_ctl.supported:
            self.font_ctl.set_height(FONT_LEVELS[self.font]["px"])

    def set_font(self, value: int) -> None:
        self.font = clamp_font(value)
        self._apply_font_px()
        self.reader.invalidate()
        self._save_global()
        self._dirty = True
        level = FONT_LEVELS[self.font]
        how = "console font resized" if self.font_ctl and self.font_ctl.supported else "simulated"
        self.notify(f"Font size set to {self.font}", "ok",
                    f"width {level['width']} · spacing {level['spacing']} · {how}")

    def ratio_text(self) -> str:
        r = self.ratio
        return f"Ratio: novel {r['novel']}% · work {r['work']}% · code {r['code']}% · status {r['status']}%"

    def set_ratio(self, ratio: dict) -> None:
        self.ratio = normalize_ratio(ratio)
        self.reader.invalidate()
        self._save_global()
        self._dirty = True
        self.notify(self.ratio_text(), "ok", "applies in mixed mode" if self.mode != "mixed" else "")

    def set_effort(self, effort: str) -> None:
        self.effort = effort
        self.ratio = normalize_ratio(EFFORT_RATIOS[effort])
        self.reader.invalidate()
        self._save_global()
        self._dirty = True
        self.notify(f"Effort set to {effort}", "ok", self.ratio_text())

    def set_mode(self, mode: str) -> None:
        self.mode = mode
        self.engine.ambient_enabled = mode == "mixed"
        self.reader.invalidate()
        self._save_global()
        self._dirty = True
        self.notify("Mixed terminal mode" if mode == "mixed" else "Pure reading mode", "ok")

    def set_theme(self, name: str) -> None:
        self.theme_name = name
        self.view.theme = get_theme(name)
        self.reader.invalidate()
        self._save_global()
        self.notify(f"Theme set to {name}", "ok")

    def cycle_footer(self) -> None:
        idx = FOOTER_MODES.index(self.footer_mode) if self.footer_mode in FOOTER_MODES else 0
        self.footer_mode = FOOTER_MODES[(idx + 1) % len(FOOTER_MODES)]
        self.pm.set_setting("footer_mode", self.footer_mode)

    def clear_screen(self) -> None:
        self.overlay = None
        self.engine.clear()
        self.input_buf = ""
        if self.interactive:
            self.console.clear()

    def quit(self) -> None:
        self.running = False

    # ==== panels =============================================================
    def _overlay_scroll(self, delta: int) -> None:
        ov = self.overlay
        ov.offset = max(0, min(ov.offset + delta, max(0, len(ov.lines) - self.reader.page_h)))

    def _panel(self, command: str, title: str, body: list) -> None:
        t = self.theme
        lines = [Text(f"> {command}", style=t.dim), Text("")]
        head = Text()
        head.append(f"{self.glyphs['dot']} ", style=t.bright)
        head.append(title, style=Style(color=t.bright, bold=True))
        lines += [head, Text("")]
        lines += body
        self.overlay = Overlay(command, lines)

    def _kv(self, key: str, value: str, key_w: int = 34) -> Text:
        row = Text("  ")
        row.append(key.ljust(key_w), style=self.theme.text)
        row.append(value, style=self.theme.dim)
        return row

    def show_help(self, command: str = "/help") -> None:
        t = self.theme
        body = [self._kv(c, d) for c, d in HELP]
        body += [Text(""), Text("  Shortcuts", style=Style(color=t.bright, bold=True)), Text("")]
        body += [self._kv(k, d, 22) for k, d in KEYS]
        body += [Text(""), Text("  All work messages are generated locally. No network, no AI service, "
                                "imported code is never executed.", style=t.faint)]
        self._panel(command, "Commands", body)

    def show_log(self) -> None:
        t, g = self.theme, self.glyphs
        styles = {"run": t.accent, "step": t.dim, "ok": t.text, "warn": t.warn, "error": t.error, "info": t.text}
        body = []
        for stamp, kind, text in self.engine.log:
            row = Text(f"  {stamp}  ", style=t.faint)
            row.append(f"{g['branch']}  " if kind == "step" else f"{g['dot']} ", style=styles.get(kind, t.dim))
            row.append(text, style=styles.get(kind, t.dim))
            body.append(row)
        if not body:
            body.append(Text("  (no entries)", style=t.dim))
        self._panel("/log", "Work log", body)
        self.overlay.offset = max(0, len(self.overlay.lines) - self.reader.page_h)

    def show_progress(self) -> None:
        if not self._need_book():
            return
        r, book = self.reader, self.reader.book
        ch = book.chapters[r.current_chapter()]
        body = [
            self._kv("File", Path(book.path).name, 18),
            self._kv("Path", str(book.path), 18),
            self._kv("Format / encoding", f"{book.fmt} / {book.encoding}", 18),
            self._kv("Chapter", f"{r.current_chapter() + 1} / {r.chapter_count}  {ch.title}", 18),
            self._kv("Paragraph", f"{r.para_index() + 1} / {len(ch.paragraphs)}", 18),
            self._kv("Chapter progress", f"{r.chapter_percent():.1f}%", 18),
            self._kv("Total progress", f"{r.book_percent():.2f}%", 18),
            self._kv("Characters", f"{r.book_char_pos():,} / {book.total_chars:,}", 18),
            self._kv("Encoding (output)", "UTF-8 · LOCAL · session active", 18),
            self._kv("Font size", str(self.font), 18),
            self._kv("Mode", "mixed" if self.mode == "mixed" else "reading", 18),
            self._kv("Effort", self.effort, 18),
            self._kv("Ratio", self.ratio_text().replace("Ratio: ", ""), 18),
        ]
        if self.mode == "mixed" and r.doc is not None and self._layout:
            width = self.view.column_width(self._layout, self.font) - 2
            counts = count_kind_lines(self._blocks(width), width, FONT_LEVELS[self.font]["spacing"])
            total = sum(counts.values()) or 1
            body.append(self._kv("Actual (chapter)", " · ".join(f"{k} {v * 100 / total:.0f}%" for k, v in counts.items()), 18))
        body.append(self._kv("Code source", self.code_lib.label, 18))
        self._panel("/progress", "Reading progress", body)

    def show_toc(self) -> None:
        if not self._need_book():
            return
        t, r = self.theme, self.reader
        body = []
        for i, ch in enumerate(r.book.chapters):
            current = i == r.current_chapter()
            row = Text(f"  {'❯' if current else ' '} {i + 1:>4}  ", style=t.text if current else t.faint)
            row.append(ch.title, style=Style(color=t.bright, bold=True) if current else t.text)
            row.append(f"  {ch.char_count:,} chars", style=t.faint)
            body.append(row)
        self._panel("/toc", "Chapters (/goto <number>)", body)
        self.overlay.offset = max(0, min(r.current_chapter(), len(self.overlay.lines) - r.page_h))

    def show_recent(self) -> None:
        t = self.theme
        body = []
        for i, rec in enumerate(self.pm.recent(20), 1):
            row = Text(f"  {i:>3}  ", style=t.faint)
            row.append(rec["file_name"], style=t.text if rec["exists"] else t.dim)
            total = rec.get("chapter_count") or 0
            row.append(f"  chapter {rec['chapter'] + 1}/{total} · {rec['updated_at']}", style=t.faint)
            if not rec["exists"]:
                row.append("  (file missing, progress kept)", style=t.warn)
            body.append(row)
        if not body:
            body.append(Text("  (no recent files) use /open <filepath>; you can drag a file into the window",
                             style=t.dim))
        self._panel("/open", "Recent files (/open <number>)", body)

    # ==== Ctrl+Q cover view ==================================================
    def _cover_lib(self) -> CodeLibrary:
        if not self.code_lib.empty:
            return self.code_lib
        if not hasattr(self, "_builtin_lib"):
            code_cfg = self.cfg["code"]
            self._builtin_lib = load_builtin_library(self.resource_dir, min_lines=code_cfg["min_lines"],
                                                     max_lines=code_cfg["max_lines"], max_file_mb=code_cfg["max_file_mb"])
        return self._builtin_lib

    def toggle_cover(self) -> None:
        """Switch between the novel and a code-only Claude Code style transcript."""
        self.cover = not self.cover
        self.overlay = None
        self.input_buf = ""
        self.hist_idx = None
        self.engine.status = type(self.engine.status)("idle", "")
        if self.cover:
            self.save_progress(force=True)
            lib = self._cover_lib()
            if self.cover_exchanges is None or getattr(self, "_cover_sig", None) != lib.signature:
                self.cover_exchanges = make_session(lib, zlib.crc32(lib.signature.encode("utf-8")))
                self._cover_sig = lib.signature
            self.cover_offset = None

    def _cover_ask(self, prompt: str) -> None:
        """Typed text in cover mode becomes another simulated exchange."""
        self.cover_exchanges.append(make_exchange(self._cover_lib(), self._cover_rng, prompt))
        self.cover_offset = None
        title, steps, done = self.engine.random_task(self._cover_rng)
        self.engine.start_task(title, steps, done)

    def _cover_lines(self, lay) -> list:
        width = lay.width - 1
        key = (width, self.theme_name, len(self.cover_exchanges), getattr(self, "_cover_sig", None))
        if self._cover_cache[0] != key:
            lines = self.view.header_rows(lay, self.cwd_text) + self.view.render_cover(self.cover_exchanges, width)
            self._cover_cache = (key, lines)
        return self._cover_cache[1]

    def _cover_view(self, lay) -> list:
        lines = self._cover_lines(lay)
        max_off = max(0, len(lines) - lay.body)
        off = max_off if self.cover_offset is None else min(self.cover_offset, max_off)
        return lines[off:]

    def _cover_scroll(self, delta: int) -> None:
        if self._layout is None or self.cover_exchanges is None:
            return
        lines = self._cover_lines(self._layout)
        max_off = max(0, len(lines) - self._layout.body)
        off = max_off if self.cover_offset is None else self.cover_offset
        off = max(0, min(max_off, off + delta))
        self.cover_offset = None if off >= max_off else off

    # ==== keyboard ===========================================================
    def handle_key(self, key: str) -> None:
        if key == "CTRL_C":
            self.quit()
        elif key == "CTRL_Q":
            self.toggle_cover()
        elif key == "ENTER":
            line = self.input_buf.strip()
            self.input_buf = ""
            self.hist_idx = None
            if line:
                if not self.history or self.history[-1] != line:
                    self.history.append(line)
                self.overlay = None
                if self.cover and not line.startswith("/"):
                    self._cover_ask(line)
                else:
                    self.commands.execute(line)
            elif self.overlay:
                self.overlay = None
        elif key == "BACKSPACE":
            self.input_buf = self.input_buf[:-1]
        elif key == "ESC":
            if self.input_buf:
                self.input_buf = ""
            elif self.overlay:
                self.overlay = None
            else:
                self.engine.interrupt()
            self.hist_idx = None
        elif key == "TAB":
            self.input_buf = complete(self.input_buf)
        elif key == "SHIFT_TAB":
            self.cycle_footer()
        elif key in ("WHEEL_UP", "WHEEL_DOWN"):
            self.scroll(-WHEEL_LINES if key == "WHEEL_UP" else WHEEL_LINES)
        elif key == "PGDN":
            self.page(+1)
        elif key == "PGUP":
            self.page(-1)
        elif key in ("UP", "DOWN"):
            if self.input_buf or self.hist_idx is not None:
                self._history(-1 if key == "UP" else 1)
            else:
                self.scroll(-1 if key == "UP" else 1)
        elif key in ("LEFT", "RIGHT"):
            if not self.input_buf and not self.cover:
                self.change_chapter(-1 if key == "LEFT" else 1)
        elif key in ("HOME", "END"):
            if not self.input_buf:
                self.chapter_edge(key == "END")
        elif len(key) == 1:
            if key == "?" and not self.input_buf:
                self.show_help("?")
            elif key.isprintable() or key == "　":
                self.input_buf += key

    def _history(self, step: int) -> None:
        if not self.history:
            return
        if self.hist_idx is None:
            self.hist_idx = len(self.history)
        self.hist_idx = max(0, min(len(self.history), self.hist_idx + step))
        if self.hist_idx == len(self.history):
            self.input_buf, self.hist_idx = "", None
        else:
            self.input_buf = self.history[self.hist_idx]

    # ==== frame ==============================================================
    def _blocks(self, width: int, ci: int | None = None):
        book = self.reader.book
        ci = self.reader.current_chapter() if ci is None else ci
        seed = zlib.crc32(f"{book.path}|{ci}|{self.code_lib.signature}|{sorted(self.ratio.items())}|{self.font}".encode("utf-8"))
        return mix_chapter(
            book.chapters[ci], width=width, ratio=self.ratio, mode=self.mode, code_lib=self.code_lib,
            engine=self.engine, rng=random.Random(seed), spacing=FONT_LEVELS[self.font]["spacing"],
        )

    def build_frame(self, width: int, height: int):
        lay = self.view.layout(width, height)
        self._layout = lay
        self.reader.page_h = lay.body
        col = self.view.column_width(lay, self.font)

        if self.reader.book is not None:
            key = (col, self.font, self.mode, tuple(sorted(self.ratio.items())),
                   self.code_lib.signature, self.theme_name, lay.body)
            spacing = FONT_LEVELS[self.font]["spacing"]
            book = self.reader.book

            def build(ci: int):
                doc = self.view.render_blocks(self._blocks(col - 2, ci), book.chapters[ci], col, spacing)
                # the header belongs to the start of the transcript (first chapter) and scrolls away
                return self.view.with_header(doc, self.view.header_rows(lay, self.cwd_text)) if ci == 0 else doc

            self.reader.configure(key, build)

        if self.overlay:
            body_lines = self.overlay.lines[self.overlay.offset:]
        elif self.cover:
            body_lines = self._cover_view(lay)
        elif self.reader.book is not None:
            body_lines = self.reader.visible_lines(lay.body)
        else:
            body_lines = self.view.header_rows(lay, self.cwd_text)

        inputs, cursor_col = self.view.input_rows(lay, self.input_buf, self.placeholder,
                                                  show_fake_cursor=not self.interactive)
        self._cursor = (lay.prompt_row, cursor_col)
        rows = self.view.body_rows(body_lines, lay.body)
        rows.append(self.view.status_row(lay, self.engine.snapshot(), self.effort))
        rows += inputs
        rows.append(self.view.footer_row(lay, self.footer_mode, self._progress_info()))
        return self.view.compose(lay, rows)

    def _progress_info(self) -> str:
        r, book = self.reader, self.reader.book
        if book is None or self.cover or not self.cfg.get("show_progress", True):
            return ""
        return f"{Path(book.path).name} · {r.current_chapter() + 1}/{r.chapter_count} · {r.book_percent():.1f}%"

    # ==== main loop ==========================================================
    def run(self) -> None:
        from rich.live import Live
        from ui.keyboard import Keyboard

        keyboard = Keyboard()
        try:
            with Live(console=self.console, screen=True, auto_refresh=False,
                      redirect_stdout=False, redirect_stderr=False) as live:
                self._refresh(live)
                while self.running:
                    try:
                        keys = keyboard.read_keys(0.05)
                        for key in keys:
                            self.handle_key(key)
                            if not self.running:
                                break
                        changed = bool(keys)
                        changed |= self.poll_job()
                        changed |= self.engine.tick()
                        if tuple(self.console.size) != self._size:
                            changed = True
                        if self._dirty and time.monotonic() - self._last_save > AUTOSAVE_SECONDS:
                            self.save_progress()
                        if changed and self.running:
                            self._refresh(live)
                    except KeyboardInterrupt:
                        self.running = False
        except KeyboardInterrupt:
            pass
        finally:
            keyboard.close()
            self.shutdown()

    def _refresh(self, live) -> None:
        width, height = self.console.size
        self._size = (width, height)
        vt = self.console.is_terminal and not self.console.legacy_windows
        if vt:
            self.console.file.write("\x1b[?25l")          # hide cursor while drawing
        live.update(self.build_frame(width, height), refresh=True)
        if vt:
            row, col = self._cursor                        # real cursor in the ❯ input line
            self.console.file.write(f"\x1b[{row + 1};{col + 1}H\x1b[?25h")
            self.console.file.flush()

    def shutdown(self) -> None:
        try:
            self.save_progress(force=True)
        finally:
            if self.font_ctl:
                self.font_ctl.restore()
            self.db.close()
