"""End-to-end test in a real Windows ConPTY console (runs run.bat, sends keystrokes,
rebuilds the screen with pyte and checks every operation).

Usage:  .venv\\Scripts\\python.exe -m pip install -r requirements-dev.txt
        .venv\\Scripts\\python.exe tests\\e2e_conpty.py
Uses a temporary progress database; your real data/progress.db is not touched.
"""
import shutil
import sys
import tempfile
import threading
import time
from pathlib import Path

import pyte
from winpty import PtyProcess

ROOT = Path(__file__).resolve().parent.parent
ROWS, COLS = 30, 110
OUT = Path(tempfile.gettempdir()) / "novel_terminal_e2e_screens.txt"
TMP = Path(tempfile.mkdtemp())
DB = TMP / "e2e.db"
CN_FILE = TMP / "測試小說.txt"
shutil.copy(ROOT / "samples" / "sample.txt", CN_FILE)

KEYS = {"UP": "\x1b[A", "DOWN": "\x1b[B", "RIGHT": "\x1b[C", "LEFT": "\x1b[D", "PGUP": "\x1b[5~",
        "PGDN": "\x1b[6~", "HOME": "\x1b[H", "END": "\x1b[F", "SHIFT_TAB": "\x1b[Z", "ESC": "\x1b",
        "ENTER": "\r", "TAB": "\t", "BS": "\x7f", "CTRL_C": "\x03"}
results = []
log = OUT.open("w", encoding="utf-8")


class Term:
    def __init__(self, args):
        self.screen = pyte.Screen(COLS, ROWS)
        self.stream = pyte.Stream(self.screen)
        self.lock = threading.Lock()
        self.raw = []
        self.proc = PtyProcess.spawn(["cmd", "/c", str(ROOT / "run.bat"), *args], dimensions=(ROWS, COLS))
        threading.Thread(target=self._pump, daemon=True).start()

    def _pump(self):
        while True:
            try:
                data = self.proc.read(65536)
            except EOFError:
                break
            except Exception:
                break
            with self.lock:
                self.raw.append(data)
                self.stream.feed(data)

    def send(self, text, wait=0.6):
        self.proc.write(text)
        time.sleep(wait)

    def key(self, name, wait=0.6):
        self.send(KEYS[name], wait)

    def cmd(self, line, wait=0.9):
        for ch in line:
            self.proc.write(ch)
            time.sleep(0.005)
        self.send("\r", wait)

    def lines(self):
        with self.lock:
            return [ln.rstrip() for ln in self.screen.display]

    def text(self):
        return "\n".join(self.lines())

    def dump(self, title):
        log.write(f"\n===== {title} =====\n{self.text()}\n")


def check(name, ok, detail=""):
    results.append((name, bool(ok)))
    print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if detail and not ok else ""))


def wait_for(term, needle, timeout=8):
    end = time.time() + timeout
    while time.time() < end:
        if needle in term.text():
            return True
        time.sleep(0.2)
    return False


# ---------------------------------------------------------------- session 1
t = Term(["--db", str(DB)])
check("startup header", wait_for(t, "Claude Code v2.1.322"))
time.sleep(0.8)
t.dump("startup")
L = t.lines()
check("mascot + model line", L[0].startswith(" ▐▛███▜▌") and "Opus 5.5 · Claude Pro" in L[1], L[:3])
check("effort row right-aligned", L[ROWS - 5].endswith("◐ medium · /effort"), L[ROWS - 5])
check("input rules", set(L[ROWS - 4]) == {"─"} and set(L[ROWS - 2]) == {"─"})
check("placeholder", L[ROWS - 3].startswith('❯ Try "fix lint errors"'), L[ROWS - 3])
check("footer", L[ROWS - 1].startswith("  ⏵⏵ auto mode on (shift+tab to cycle) · ← for agents"), L[ROWS - 1])
check("real cursor in input", (t.screen.cursor.y, t.screen.cursor.x) == (ROWS - 3, 2),
      (t.screen.cursor.y, t.screen.cursor.x))
check("first-run hint", "Type /open <filepath>" in t.text())

t.cmd(f"/open {ROOT / 'samples' / 'sample.epub'}", wait=0.3)
check("loading spinner", wait_for(t, "Reading current document…", 3) or "Read sample.epub" in t.text())
check("EPUB opened", wait_for(t, "Read sample.epub", 10))
time.sleep(0.5)
t.dump("epub opened")
check("novel text (Chinese) shown", "霧港夜話" in t.text() or "這是一份測試用" in t.text())
check("footer progress", "sample.epub · 1/4" in t.lines()[ROWS - 1], t.lines()[ROWS - 1])

check("header at chapter top", t.lines()[0].startswith(" ▐▛███▜▌"))
t.key("RIGHT"); check("Right -> next chapter", "· 2/4 ·" in t.lines()[ROWS - 1] and "霧裡的燈塔" in t.text())
t.key("LEFT"); check("Left -> prev chapter", "· 1/4 ·" in t.lines()[ROWS - 1])
t.cmd("/next"); check("/next", "· 2/4 ·" in t.lines()[ROWS - 1])
t.cmd("/prev"); check("/prev", "· 1/4 ·" in t.lines()[ROWS - 1])
t.cmd("/goto 3"); check("/goto 3", "· 3/4 ·" in t.lines()[ROWS - 1] and "不該出現的船" in t.text())
t.cmd("/font 5"); t.dump("font 5")
for _ in range(4):
    t.key("DOWN", 0.3)
t.dump("scrolled 4 lines")
check("header scrolls away (not sticky)", "Claude Code v2.1.322" not in t.text(), t.lines()[:3])
t.key("HOME")
check("Home -> chapter title back at top", t.lines()[0].startswith("● 第二章"), t.lines()[0])
check("/font 5 (narrow column)", "Font size set to 5" in t.text() and max(len(l) for l in t.lines()[4:20]) < 80)
before = t.text()
t.key("PGDN"); check("PageDown scrolls", t.text() != before)
t.key("PGUP"); check("PageUp back", "不該出現的船" in t.text())
t.key("DOWN"); t.key("UP"); check("Up/Down scroll", "不該出現的船" in t.text())
t.cmd("/goto 3"); t.key("END"); t.key("HOME"); check("Home/End (End -> chapter end, Home -> chapter start)", t.lines()[0].startswith("● 第二章"), t.lines()[0])
t.cmd("/font 3")
before = t.text()
t.key("ENTER"); check("Enter (empty input) does not page", t.text() == before)
t.cmd("/goto 1")
for _ in range(6):
    t.key("PGDN", 0.3)
time.sleep(0.6)
check("continuous scroll flows into next chapters", "· 1/4 ·" not in t.lines()[ROWS - 1], t.lines()[ROWS - 1])
t.cmd("/goto 2")
top = t.lines()[0]
t.send("[<65;20;10M", 0.6)
check("mouse wheel down scrolls", t.lines()[0] != top, (top, t.lines()[0]))
t.send("[<64;20;10M", 0.6)
check("mouse wheel up scrolls back", t.lines()[0] == top, (top, t.lines()[0]))
t.cmd("/goto 3")
t.cmd("/continue"); check("/continue", "Already" not in t.text())
t.key("SHIFT_TAB"); check("Shift+Tab -> plan mode", "plan mode on" in t.lines()[ROWS - 1], t.lines()[ROWS - 1])
t.key("SHIFT_TAB"); check("Shift+Tab -> accept edits", "accept edits on" in t.lines()[ROWS - 1])
t.key("SHIFT_TAB"); check("Shift+Tab -> ? for shortcuts", "? for shortcuts" in t.lines()[ROWS - 1])
t.key("SHIFT_TAB"); check("Shift+Tab -> auto mode", "auto mode on" in t.lines()[ROWS - 1])
t.send("?", 0.8); t.dump("? help")
t.key("PGDN"); check("? shows shortcuts (scroll panel)", "Shift+Tab" in t.text() and "Cycle footer mode" in t.text())
t.key("ESC", 1.0); check("Esc closes panel", "Commands" not in t.text())
t.cmd("/help"); check("/help", "/effort [low|medium|high]" in t.text())
t.key("ENTER"); check("Enter closes panel", "/effort [low|medium|high]" not in t.text())
t.cmd("/ratio 60 20 15 5"); check("/ratio", "Ratio: novel 60%" in t.text())
t.cmd("/ratio code 10"); check("/ratio code 10", "code 10%" in t.text())
t.cmd("/ratio reset"); check("/ratio reset", "novel 62%" in t.text())
t.cmd("/effort high"); check("/effort high", "● high · /effort" in t.lines()[ROWS - 5] and "Effort set to high" in t.text())
t.cmd("/effort medium"); check("/effort medium", "◐ medium · /effort" in t.lines()[ROWS - 5])
t.cmd("/mode reading"); check("/mode reading", "Pure reading mode" in t.text())
t.cmd("/mode mixed"); check("/mode mixed", "Mixed terminal mode" in t.text())
t.cmd("/theme mono"); check("/theme mono", "Theme set to mono" in t.text())
t.cmd("/theme claude"); check("/theme claude", "Theme set to claude" in t.text())
t.cmd(f"/code {ROOT / 'main.py'}"); check("/code file", "Code source: main.py" in t.text())
t.cmd("/code"); check("/code info", "Code source: main.py" in t.text())
t.cmd("/code off"); check("/code off", "Code snippets disabled" in t.text())
t.cmd("/code default"); check("/code default", "built-in (project source)" in t.text())
t.cmd("/toc"); t.dump("toc"); check("/toc", "Chapters (/goto <number>)" in t.text() and "日誌的最後一頁" in t.text())
t.key("ESC", 1.0)
t.cmd("/progress"); t.dump("progress"); check("/progress", "Reading progress" in t.text() and "Total progress" in t.text())
t.key("ESC", 1.0)
t.cmd("/log"); t.dump("log"); t.key("HOME"); check("/log (scroll to top)", "Work log" in t.text() and "Reading current document" in t.text())
t.key("ESC", 1.0)
t.cmd("/clear"); check("/clear", "Work log" not in t.text())
t.cmd("/foo"); check("unknown command", "Unknown command: /foo" in t.text())
t.cmd("hello"); check("plain text", "Commands start with /" in t.text())
t.send("/he", 0.3); t.key("TAB", 0.5); check("Tab completion", "❯ /help" in t.lines()[ROWS - 3], t.lines()[ROWS - 3])
t.key("ESC", 0.8); check("Esc clears input", t.lines()[ROWS - 3].startswith('❯ Try'))
t.send("/next", 0.3); t.key("BS"); t.key("BS"); check("Backspace", t.lines()[ROWS - 3].rstrip() == "❯ /ne")
t.key("ESC", 0.8)
t.send("/", 0.3); t.key("UP"); check("history (Up while typing -> last command)", t.lines()[ROWS - 3] == "❯ hello", t.lines()[ROWS - 3])
t.key("UP"); check("history older", t.lines()[ROWS - 3] != "❯ /", t.lines()[ROWS - 3])
t.key("ESC", 0.8)
t.cmd("/open"); check("/open recent list", "Recent files" in t.text() and "sample.epub" in t.text())
t.key("ESC", 0.8)
t.cmd(f"/open {CN_FILE}", wait=0.3)
check("open Chinese filename (typed Unicode)", wait_for(t, "Read 測試小說.txt", 10))
top_before = t.lines()[0]
t.send("\x11", 1.0); t.dump("ctrl+q cover")
cover = t.text()
check("Ctrl+Q -> code-only view", "● " in cover and "/effort" in cover and "沈既白" not in cover and "霧" not in cover
      and "測試小說" not in cover, t.lines()[ROWS - 1])
check("cover footer hides progress", "測試小說" not in t.lines()[ROWS - 1] and "/4" not in t.lines()[ROWS - 1])
t.cmd("what does load_book do?", 1.2)
found = False
for _ in range(6):
    if "> what does load_book do?" in t.text():
        found = True
        break
    t.key("PGUP", 0.4)
check("cover: typed question -> simulated answer", found and "load_book" in t.text())
t.key("PGUP"); t.key("DOWN")
t.send("\x11", 1.0)
check("Ctrl+Q again -> back to the novel at the same place", t.lines()[0] == top_before, (top_before, t.lines()[0]))
t.cmd("/open D:\\nope\\x.txt"); check("missing file error", "File not found: x.txt" in t.text())
bad = TMP / "x.pdf"; bad.write_bytes(b"%PDF")
t.cmd(f"/open {bad}", wait=1.5); check("unsupported format error", "Unsupported file format" in t.text())
t.cmd("/goto 2"); t.key("DOWN"); t.key("DOWN")
pos_line = t.lines()[ROWS - 1]
t.dump("before quit")
t.key("CTRL_C", 1.5)
check("Ctrl+C exits and saves", wait_for(t, "Progress saved.", 5))
try:
    t.proc.terminate(force=True)
except Exception:
    pass

# ---------------------------------------------------------------- session 2: resume
t2 = Term(["--db", str(DB)])
check("resume last book", wait_for(t2, "Read 測試小說.txt", 10))
time.sleep(0.8)
t2.dump("resumed")
check("resume chapter/position", "· 2/4 ·" in t2.lines()[ROWS - 1] and t2.lines()[ROWS - 1].split("·")[-1] == pos_line.split("·")[-1],
      (pos_line, t2.lines()[ROWS - 1]))
t2.cmd("/quit", 1.5)
check("/quit exits", wait_for(t2, "Progress saved.", 5))
try:
    t2.proc.terminate(force=True)
except Exception:
    pass

# ---------------------------------------------------------------- session 3: missing file keeps progress
CN_FILE.rename(CN_FILE.with_suffix(".bak"))
t3 = Term(["--db", str(DB)])
check("missing last file -> warning", wait_for(t3, "Last file not found: 測試小說.txt", 8))
t3.cmd("/open"); check("progress kept for missing file", "(file missing, progress kept)" in t3.text())
t3.dump("missing")
t3.key("CTRL_C", 1.5)
try:
    t3.proc.terminate(force=True)
except Exception:
    pass

log.close()
passed = sum(ok for _, ok in results)
print(f"\n{passed}/{len(results)} passed; screens saved to {OUT}")
sys.exit(0 if passed == len(results) else 1)
