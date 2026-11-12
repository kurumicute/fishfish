"""Novel Terminal - terminal novel reader (entry point)."""
from __future__ import annotations

import argparse
import io
import os
import sys
from pathlib import Path

if getattr(sys, "frozen", False):
    # PyInstaller build: config/ and data/ live next to NovelTerminal.exe
    BASE_DIR = Path(sys.executable).resolve().parent
else:
    BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))


def setup_utf8() -> None:
    """讓 Windows CMD 正確顯示中文：切換主控台字碼頁並設定標準輸出編碼。"""
    if sys.platform == "win32":
        try:
            import ctypes
            k32 = ctypes.windll.kernel32
            k32.SetConsoleOutputCP(65001)
            k32.SetConsoleCP(65001)
            # 開啟 VT 處理模式，讓傳統 CMD 也能使用替代螢幕與游標定位（原地重繪、不閃爍）
            handle = k32.GetStdHandle(-11)
            mode = ctypes.c_uint32()
            if k32.GetConsoleMode(handle, ctypes.byref(mode)):
                k32.SetConsoleMode(handle, mode.value | 0x0004)  # ENABLE_VIRTUAL_TERMINAL_PROCESSING
        except Exception:
            pass
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def parse_args(argv=None):
    ap = argparse.ArgumentParser(prog="novel-terminal", description="Terminal novel reader")
    ap.add_argument("file", nargs="?", help="novel to open (TXT / EPUB); resumes the last one if omitted")
    ap.add_argument("--code", help="code reference file or folder")
    ap.add_argument("--db", help="progress database path (default data/progress.db)")
    ap.add_argument("--snapshot", action="store_true",
                    help="print a single plain-text frame and exit (testing; progress not saved)")
    ap.add_argument("--width", type=int, default=100, help="snapshot width")
    ap.add_argument("--height", type=int, default=32, help="snapshot height")
    ap.add_argument("--chapter", type=int, help="snapshot: go to chapter N")
    ap.add_argument("--pages", type=int, default=0, help="snapshot: page down N times")
    ap.add_argument("--cmd", action="append", default=[], help="snapshot: run commands in order, e.g. --cmd \"/font 4\"")
    return ap.parse_args(argv)


def run_snapshot(args) -> int:
    from rich.console import Console
    from ui.app import App

    buf = io.StringIO()
    console = Console(file=buf, width=args.width, height=args.height, color_system=None,
                      force_terminal=False, legacy_windows=False, highlight=False)
    app = App(BASE_DIR, console, db_path=args.db or ":memory:", interactive=False)
    app.startup(args.file, args.code, sync=True)
    app.engine.ambient_enabled = False
    app.engine.active = None if app.engine.active and not app.engine.active.external else app.engine.active
    app.build_frame(args.width, args.height)   # 先排版，取得頁高
    if args.chapter:
        app.goto_chapter(args.chapter - 1)
        app.build_frame(args.width, args.height)
    for _ in range(max(0, args.pages)):
        app.page(+1)
        app.build_frame(args.width, args.height)
    for command in args.cmd:
        app.commands.execute(command)
        app.build_frame(args.width, args.height)
    app.engine.active = None
    console.print(app.build_frame(args.width, args.height))
    app.shutdown()
    sys.stdout.write(buf.getvalue())
    return 0


def main(argv=None) -> int:
    setup_utf8()
    args = parse_args(argv)
    try:
        import rich  # noqa: F401
    except ImportError:
        print("Missing package rich. Run install.bat (or pip install -r requirements.txt).")
        return 1

    if args.snapshot:
        return run_snapshot(args)

    if not sys.stdin.isatty() or not sys.stdout.isatty():
        print("Please run this in CMD / PowerShell / Windows Terminal (an interactive terminal is required).")
        return 2

    from rich.console import Console
    from ui.app import App

    console = Console(highlight=False)
    app = App(BASE_DIR, console, db_path=args.db)
    app.startup(args.file, args.code)
    app.run()
    print("Progress saved.")
    return 0


if __name__ == "__main__":
    os.environ.setdefault("PYTHONUTF8", "1")
    sys.exit(main())
