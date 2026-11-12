"""核心功能測試：python -m unittest discover -s tests -v"""
from __future__ import annotations

import io
import random
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from rich.console import Console  # noqa: E402
from rich.text import Text  # noqa: E402

from core.code_loader import load_builtin_library, load_code_library  # noqa: E402
from core.config import normalize_ratio  # noqa: E402
from core.content_mixer import count_kind_lines, mix_chapter  # noqa: E402
from core.encoding import decode_bytes  # noqa: E402
from core.models import Chapter, NovelLoadError  # noqa: E402
from core.novel_parser import load_book, split_chapters  # noqa: E402
from core.terminal_engine import TerminalEngine  # noqa: E402
from ui.app import App  # noqa: E402

SAMPLE_TXT = ROOT / "samples" / "sample.txt"
TEXT = SAMPLE_TXT.read_text(encoding="utf-8")


def make_app(db_path) -> App:
    console = Console(file=io.StringIO(), width=100, height=32, color_system=None, legacy_windows=False)
    return App(ROOT, console, db_path=db_path, interactive=False)


class EncodingTests(unittest.TestCase):
    def test_utf8_bom_big5_gb(self):
        self.assertEqual(decode_bytes(TEXT.encode("utf-8")), (TEXT, "UTF-8"))
        self.assertEqual(decode_bytes(b"\xef\xbb\xbf" + TEXT.encode("utf-8")), (TEXT, "UTF-8 BOM"))
        text, enc = decode_bytes(TEXT.encode("big5", errors="strict"))
        self.assertEqual(text, TEXT)
        self.assertTrue(enc.startswith("Big5"))
        simplified = "这是一个简体中文的测试段落，他说我们要去那里看看。" * 20
        text, enc = decode_bytes(simplified.encode("gb18030"))
        self.assertEqual(text, simplified)
        self.assertEqual(enc, "GB18030")


class TxtParserTests(unittest.TestCase):
    def test_chapters_and_paragraphs_preserved(self):
        chapters = split_chapters(TEXT)
        titles = [c.title for c in chapters]
        self.assertEqual(titles, ["Preface", "第一章　霧裡的燈塔", "第二章　不該出現的船", "第三章　日誌的最後一頁"])
        original = [ln.rstrip() for ln in TEXT.splitlines() if ln.strip() and ln.strip() not in titles]
        parsed = [p for c in chapters for p in c.paragraphs]
        self.assertEqual(parsed, original)           # 原文逐字保留（含全形縮排與標點）
        self.assertTrue(parsed[1].startswith("　　"))

    def test_heading_variants(self):
        text = "第1章初入江湖\n內容一\n第二回 風起\n內容二\n楔子\n內容三\nChapter 4\n內容四\n"
        self.assertEqual([c.title for c in split_chapters(text)], ["第1章初入江湖", "第二回 風起", "楔子", "Chapter 4"])
        self.assertEqual(len(split_chapters("第三章就講到這裡，他心想這件事情恐怕沒有那麼簡單，於是又多看了幾眼。\n")), 1)

    def test_auto_sections_without_headings(self):
        chapters = split_chapters("\n".join(["段落" * 50] * 100), 4000)
        self.assertGreater(len(chapters), 1)
        self.assertTrue(chapters[0].title.startswith("Part"))

    def test_big5_file_and_errors(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "big5.txt"
            p.write_bytes(TEXT.encode("big5"))
            book = load_book(p)
            self.assertEqual(len(book.chapters), 4)
            self.assertIn("煤油燈", book.chapters[1].paragraphs[1])
            bad = Path(d) / "x.pdf"
            bad.write_bytes(b"%PDF")
            with self.assertRaisesRegex(NovelLoadError, "Unsupported file format"):
                load_book(bad)
            with self.assertRaisesRegex(NovelLoadError, "File not found"):
                load_book(Path(d) / "none.txt")


class EpubTests(unittest.TestCase):
    def test_epub_order_titles_and_inline_tags(self):
        sys.path.insert(0, str(ROOT / "samples"))
        from make_sample_epub import build
        with tempfile.TemporaryDirectory() as d:
            path = build(Path(d) / "s.epub", SAMPLE_TXT)
            book = load_book(path)
            txt = load_book(SAMPLE_TXT)
            self.assertEqual(book.fmt, "EPUB")
            self.assertEqual([c.title for c in book.chapters], [c.title for c in txt.chapters])
            for a, b in zip(book.chapters, txt.chapters):
                self.assertEqual(a.paragraphs, b.paragraphs)  # 不合併章節、<em> 不切斷段落

    def test_broken_epub(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "broken.epub"
            p.write_bytes(b"not a zip")
            with self.assertRaisesRegex(NovelLoadError, "EPUB"):
                load_book(p)


class CodeLoaderTests(unittest.TestCase):
    def test_snippets_are_real_code(self):
        src = ROOT / "core" / "reader.py"
        lines = src.read_text(encoding="utf-8").splitlines()
        lib = load_code_library(src, min_lines=4, max_lines=8)
        self.assertGreater(len(lib.snippets), 5)
        for sn in lib.snippets:
            self.assertEqual(sn.lines, [ln.expandtabs(4).rstrip() for ln in lines[sn.start - 1: sn.end]])

    def test_snippets_are_complete_blocks(self):
        from core.code_loader import split_snippets
        funcs = []
        for i in range(8):
            body = [f"    int v{k} = call_{k}(x, {k});" for k in range(3 + i * 3)]
            funcs += [f"/* helper {i} */", f"static int helper_{i}(int x)", "{", "    if (x < 0) {",
                      "        return -1;", "    }", "", *body, "    return x;", "}", ""]
        snippets = split_snippets(chr(10).join(funcs), "a.c", "c", 5, 40)
        for sn in snippets:
            self.assertEqual(sum(l.count("{") - l.count("}") for l in sn.lines), 0, sn.start)
            self.assertTrue(sn.lines[0].startswith("/* helper"), sn.lines[0])
        py = chr(10).join(["def f(a):", "    x = 1", "", "    return x", "", "", "class K:",
                         "    def m(self):", "        pass", "", "    def n(self):", "        return 2"])
        starts = [sn.lines[0] for sn in split_snippets(py, "a.py", "python", 1, 40)]
        self.assertEqual(starts, ["def f(a):", "class K:"])

    def test_binary_rejected_and_builtin(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "a.bin"
            p.write_bytes(b"\x00\x01\x02" * 100)
            with self.assertRaisesRegex(NovelLoadError, "Binary"):
                load_code_library(p)
        self.assertGreater(len(load_builtin_library(ROOT).snippets), 20)


class MixerTests(unittest.TestCase):
    def setUp(self):
        self.chapter = Chapter("第一章", [f"　　第{i}段，" + "這是用來測試比例的中文內容。" * 6 for i in range(300)])
        self.lib = load_code_library(ROOT / "core" / "reader.py")
        self.engine = TerminalEngine("zh")

    def mix(self, ratio, mode="mixed"):
        return mix_chapter(self.chapter, width=80, ratio=normalize_ratio(ratio), mode=mode,
                           code_lib=self.lib, engine=self.engine, rng=random.Random(1), spacing=1)

    def test_reading_mode_only_novel(self):
        blocks = self.mix({"novel": 78, "work": 12, "code": 7, "status": 3}, mode="reading")
        self.assertEqual({b.kind for b in blocks}, {"title", "para"})

    def test_mixed_preserves_novel_and_ratio(self):
        ratio = {"novel": 78, "work": 12, "code": 7, "status": 3}
        blocks = self.mix(ratio)
        self.assertEqual([b.text for b in blocks if b.kind == "para"], self.chapter.paragraphs)
        counts = count_kind_lines(blocks, 80, 1)
        total = sum(counts.values())
        for key, target in ratio.items():
            self.assertAlmostEqual(counts[key] * 100 / total, target, delta=3, msg=key)
        # 程式碼片段分散於章節中，而非集中在末尾
        code_pos = [i for i, b in enumerate(blocks) if b.kind == "code"]
        self.assertLess(code_pos[0], len(blocks) * 0.3)
        self.assertGreater(code_pos[-1], len(blocks) * 0.7)

    def test_ratio_adjustable(self):
        low = count_kind_lines(self.mix({"novel": 95, "work": 2, "code": 2, "status": 1}), 80, 1)
        high = count_kind_lines(self.mix({"novel": 60, "work": 15, "code": 20, "status": 5}), 80, 1)
        self.assertGreater(high["code"], low["code"] * 4)

    def test_normalize_ratio(self):
        self.assertEqual(sum(normalize_ratio({"novel": 1, "work": 1, "code": 1, "status": 1}).values()), 100)
        self.assertGreaterEqual(normalize_ratio({"novel": 1, "work": 50, "code": 50, "status": 0})["novel"], 40)


class AppProgressTests(unittest.TestCase):
    def test_save_and_restore_position(self):
        with tempfile.TemporaryDirectory() as d:
            db = Path(d) / "p.db"
            app = make_app(db)
            app.startup(str(SAMPLE_TXT), sync=True)
            app.build_frame(100, 14)
            app.goto_chapter(2)
            app.build_frame(100, 14)
            for _ in range(200):
                if app.reader.char_pos() > 0:
                    break
                app.scroll(1)
            app.set_font(4)
            app.build_frame(100, 14)
            chapter, char_pos = app.reader.chapter, app.reader.char_pos()
            self.assertGreater(char_pos, 0)
            app.shutdown()

            app2 = make_app(db)
            app2.startup(sync=True)                 # 未指定檔案 → 自動恢復上次閱讀
            app2.build_frame(100, 14)
            self.assertEqual(app2.reader.chapter, chapter)
            self.assertEqual(app2.reader.char_pos(), char_pos)
            self.assertEqual(app2.font, 4)
            app2.shutdown()

    def test_missing_file_keeps_progress(self):
        with tempfile.TemporaryDirectory() as d:
            novel = Path(d) / "book.txt"
            novel.write_text(TEXT, encoding="utf-8")
            db = Path(d) / "p.db"
            app = make_app(db)
            app.startup(str(novel), sync=True)
            app.build_frame(100, 20)
            app.change_chapter(+1)
            app.shutdown()
            novel.unlink()
            app2 = make_app(db)
            app2.startup(sync=True)
            self.assertIsNone(app2.reader.book)
            self.assertIn("not found", app2.engine.status.title)
            rec = app2.pm.load(novel)
            self.assertIsNotNone(rec)
            self.assertEqual(rec["chapter"], 1)
            app2.shutdown()

    def test_commands_and_paging(self):
        with tempfile.TemporaryDirectory() as d:
            app = make_app(Path(d) / "p.db")
            app.startup(str(SAMPLE_TXT), sync=True)
            app.build_frame(100, 16)
            for cmd in ["/next", "/prev", "/continue", "/progress", "/toc", "/goto 3", "/font +",
                        "/font 2", "/ratio 70 15 10 5", "/ratio code 5", "/ratio reset", "/mode reading",
                        "/mode mixed", "/effort high", "/effort", "/effort low", "/theme mono", "/theme", "/log", "/help", "/code off",
                        "/code default", f"/code {ROOT / 'main.py'}", "/open", "/clear", "/unknown", "hello"]:
                app.commands.execute(cmd)
                frame = app.build_frame(100, 16)
                self.assertEqual(len(frame.renderables), 16, cmd)
            app.overlay = None
            for key in ["RIGHT", "LEFT", "PGDN", "PGUP", "DOWN", "UP", "END", "HOME", " ", "ENTER", "SHIFT_TAB", "?", "ESC", "ESC"]:
                app.handle_key(key)
                app.build_frame(100, 16)
            app.commands.execute("/quit")
            self.assertFalse(app.running)
            app.shutdown()


class ClaudeLayoutTests(unittest.TestCase):
    def test_cjk_wrap_rules(self):
        from ui.terminal_view import NO_END, NO_START, cjk_wrap
        text = "　　林予安沒有回答。他翻開祖父留下的航海日誌，在最後一頁找到一行褪色的字：「綠船來時，勿應其鈴。」" * 3
        for width in range(10, 90, 3):
            lines = cjk_wrap(text, width)
            self.assertEqual("".join(lines), text)
            for i, ln in enumerate(lines):
                self.assertLessEqual(Text(ln).cell_len, width)
                if i:
                    self.assertNotIn(ln[0], NO_START)
                if i < len(lines) - 1:
                    self.assertNotIn(ln[-1], NO_END)

    def test_layout_matches_screenshot(self):
        with tempfile.TemporaryDirectory() as d:
            app = make_app(Path(d) / "p.db")
            app.startup(sync=True)
            con = Console(file=io.StringIO(), width=110, height=24, color_system=None, legacy_windows=False)
            con.print(app.build_frame(110, 24))
            rows = con.file.getvalue().splitlines()
            self.assertTrue(rows[0].startswith(" ▐▛███▜▌   Claude Code v2.1.322"))
            self.assertIn("Opus 5.5 · Claude Pro", rows[1])
            self.assertTrue(rows[19].rstrip().endswith("◐ medium · /effort"))
            self.assertEqual(set(rows[20].strip()), {"─"})
            self.assertTrue(rows[21].startswith('❯ Try "fix lint errors"'))
            self.assertEqual(set(rows[22].strip()), {"─"})
            self.assertTrue(rows[23].startswith("  ⏵⏵ auto mode on (shift+tab to cycle) · ← for agents"))
            self.assertEqual(app._cursor, (21, 2))
            app.handle_key("SHIFT_TAB")
            con = Console(file=io.StringIO(), width=110, height=24, color_system=None, legacy_windows=False)
            con.print(app.build_frame(110, 24))
            self.assertIn("plan mode on", con.file.getvalue())
            for k in "/hi":
                app.handle_key(k)
            app.build_frame(110, 24)
            self.assertEqual(app._cursor, (21, 5))
            app.shutdown()

    def test_effort_and_interrupt(self):
        with tempfile.TemporaryDirectory() as d:
            app = make_app(Path(d) / "p.db")
            app.commands.execute("/effort high")
            self.assertEqual(app.effort, "high")
            self.assertEqual(app.ratio["novel"], 48)
            app.engine.start_task("Reading current document", ["a", "b"], "done")
            app.handle_key("ESC")
            self.assertIsNone(app.engine.active)
            self.assertEqual(app.engine.status.title, "Interrupted by user")
            app.shutdown()


C_SAMPLE = """#include <stdio.h>
#include "freertos/queue.h"

typedef struct {
    int type;      // 0=Mgmt
    int len;
} frame_t;

/* parse one packet and queue it */
static void packet_cb(void *buf, int type)
{
    if (type != 1 && type != 2) {
        return;
    }
    frame_t info = {0};
    info.type = type;
    info.len  = 24;
    xQueueSend(s_queue, &info, 0);
}
static void hop_task(void *arg)
{
    while (1) {
        esp_wifi_set_channel(ch, 0);
        vTaskDelay(200);
    }
}
"""


class AnalysisTests(unittest.TestCase):
    def setUp(self):
        from core.code_loader import split_snippets
        self.snippets = {s.lines[0]: s for s in split_snippets(C_SAMPLE, "x.c", "c", 1, 40)}

    def facts(self, first_line):
        from core.code_analysis import analyze
        sn = next(s for k, s in self.snippets.items() if k.startswith(first_line))
        return analyze(sn)

    def test_facts_come_from_code(self):
        self.assertEqual(self.facts("#include").includes, ["stdio.h", "freertos/queue.h"])
        st = self.facts("typedef struct")
        self.assertEqual((st.kind, st.name, st.struct_fields), ("struct", "frame_t", ["type", "len"]))
        cb = self.facts("/* parse")
        self.assertEqual((cb.name, cb.params, cb.comment), ("packet_cb", ["buf", "type"], "parse one packet and queue it"))
        self.assertEqual(cb.early_returns, ["type != 1 && type != 2"])
        self.assertEqual(cb.fields_set, {"info": ["type", "len"]})
        self.assertTrue(any("xQueueSend" in i for i in cb.issues))
        self.assertFalse(cb.infinite_loop)
        hop = self.facts("static void hop_task")      # no blank line before it: still its own snippet
        self.assertTrue(hop.infinite_loop)
        self.assertTrue(any("never exits" in i for i in hop.issues))

    def test_answers_follow_intent(self):
        import random
        from core.code_loader import CodeLibrary
        from core.cover import detect_intent, make_exchange
        lib = CodeLibrary(snippets=list(self.snippets.values()))
        self.assertEqual(detect_intent("is there a bug in hop_task?"), "bug")
        self.assertEqual(detect_intent("review packet_cb"), "review")
        ex = make_exchange(lib, random.Random(1), "explain how packet_cb works")
        text = str(ex.items)
        self.assertIn("packet_cb", text)
        self.assertIn("type != 1 && type != 2", text)
        reads = [i[1] for i in ex.items if i[0] == "read"]
        self.assertEqual(reads[0].lines[-1], "}")
        for item in ex.items:
            if item[0] == "search":
                self.assertEqual(item[3], sum(1 for ln in C_SAMPLE.splitlines() if item[1] in ln))

    def test_more_file_types_and_multiple_sources(self):
        from core.code_loader import is_code_file, load_code_sources, split_paths
        for name in ("a.ino", "b.swift", "c.lua", "Dockerfile", "Makefile", "x.tf", "y.kt", "z.rs"):
            self.assertTrue(is_code_file(Path(name)), name)
        self.assertEqual(split_paths('a.py;b.go'), ["a.py", "b.go"])
        self.assertEqual(split_paths(r'"C:\a b\x.py" "y.go"'), [r"C:\a b\x.py", "y.go"])
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "Dockerfile").write_text("FROM python:3.12\nRUN pip install rich\nCMD [\"python\"]\n", encoding="utf-8")
            lib = load_code_sources([str(ROOT / "main.py"), str(Path(d) / "Dockerfile"), str(Path(d) / "missing.py")])
            self.assertEqual(lib.file_count, 2)
            self.assertEqual(len(lib.errors), 1)
            self.assertIn("docker", {s.lexer for s in lib.snippets})


class FakeDiffTests(unittest.TestCase):
    def test_diff_uses_real_line_and_claude_colors(self):
        import random
        from core.code_loader import split_snippets
        from core.cover import make_exchange
        from core.code_loader import CodeLibrary
        from core.fake_diff import make_diff
        sn = next(x for x in split_snippets(C_SAMPLE, "x.c", "c", 1, 40) if "packet_cb" in "".join(x.lines))
        diff = make_diff(sn, random.Random(0), prefer=["xQueueSend"])
        removed = [r for r in diff.rows if r[0] == "-"]
        added = [r for r in diff.rows if r[0] == "+"]
        self.assertEqual(removed[0][2], "    xQueueSend(s_queue, &info, 0);")      # real original line
        self.assertEqual(added[0][2], "    if (xQueueSend(s_queue, &info, 0) != 0) {")
        self.assertEqual(diff.summary, "Updated x.c with 3 additions and 1 removal")
        view_lines = make_app_view().diff_rows(diff, "c", 100)
        minus = next(t for t, r in zip(view_lines, diff.rows) if r[0] == "-")
        plus = next(t for t, r in zip(view_lines, diff.rows) if r[0] == "+")
        self.assertIn("on #3d0100", " ".join(str(sp.style) for sp in minus.spans))
        self.assertIn("on #022800", " ".join(str(sp.style) for sp in plus.spans))
        # a review answer that finds an issue ends with a pretend fix
        lib = CodeLibrary(snippets=[sn])
        kinds = set()
        for seed in range(10):
            kinds |= {i[0] for i in make_exchange(lib, random.Random(seed), "review packet_cb").items}
        self.assertIn("update", kinds)


def make_app_view():
    from ui.terminal_view import TerminalView
    from ui.theme import GLYPHS_UNICODE, get_theme
    return TerminalView(Console(file=io.StringIO(), width=100), get_theme("claude"), GLYPHS_UNICODE, {})


class CoverModeTests(unittest.TestCase):
    def test_ctrl_q_hides_novel_and_restores(self):
        with tempfile.TemporaryDirectory() as d:
            app = make_app(Path(d) / "p.db")
            app.startup(str(SAMPLE_TXT), str(ROOT / "core" / "reader.py"), sync=True)
            app.build_frame(100, 30)
            app.goto_chapter(2)
            app.build_frame(100, 30)
            before = (app.reader.chapter, app.reader.offset)

            def frame_text():
                con = Console(file=io.StringIO(), width=100, height=30, color_system=None, legacy_windows=False)
                con.print(app.build_frame(100, 30))
                return con.file.getvalue()

            app.handle_key("CTRL_Q")
            text = frame_text()
            self.assertTrue(app.cover)
            for leak in ("sample.txt", "霧", "第二章", "林予安"):
                self.assertNotIn(leak, text)
            self.assertIn("● ", text)
            self.assertTrue(any(i[0] == "read" for ex in app.cover_exchanges for i in ex.items))
            for ch in "how does page_down work?":
                app.handle_key(ch)
            app.handle_key("ENTER")
            text = frame_text()
            self.assertEqual(app.cover_exchanges[-1].prompt, "how does page_down work?")
            self.assertIn("page_down", text)
            app.handle_key("UP")
            app.handle_key("LEFT")                      # chapter keys are ignored in cover mode
            app.handle_key("CTRL_Q")
            self.assertFalse(app.cover)
            app.build_frame(100, 30)
            self.assertEqual((app.reader.chapter, app.reader.offset), before)
            self.assertIn("霧", frame_text())
            app.shutdown()


class SafetyTests(unittest.TestCase):
    def test_no_network_or_exec(self):
        banned = re.compile(r"^\s*(import|from)\s+(socket|http|requests|urllib\.request|aiohttp|httpx|openai|anthropic|subprocess|webbrowser)\b", re.M)
        for path in list((ROOT / "core").glob("*.py")) + list((ROOT / "ui").glob("*.py")) + [ROOT / "main.py"]:
            source = path.read_text(encoding="utf-8")
            self.assertIsNone(banned.search(source), path.name)
            self.assertNotRegex(source, r"\b(exec|eval)\(", path.name)

    def test_snapshot_cli(self):
        out = subprocess.run(
            [sys.executable, str(ROOT / "main.py"), str(SAMPLE_TXT), "--snapshot", "--chapter", "2"],
            capture_output=True, timeout=60,
        )
        self.assertEqual(out.returncode, 0, out.stderr.decode("utf-8", "replace"))
        text = out.stdout.decode("utf-8")
        self.assertNotIn("Claude Code v2.1.322", text)   # header only at the start of the book
        self.assertIn("霧裡的燈塔", text)
        self.assertIn("auto mode on (shift+tab to cycle)", text)


if __name__ == "__main__":
    unittest.main()
