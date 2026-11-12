"""閱讀狀態：連續捲動（章節首尾相接）、位置與字元位置換算。

畫面是一條連續的「對話紀錄」：章節依序接在一起，往下捲到章尾會直接進入下一章。
位置以 (頂端章節, 章內行號) 表示；保存進度時使用畫面上第一個可見小說段落的字元位置。
"""
from __future__ import annotations

import bisect
from dataclasses import dataclass, field
from typing import Callable

from core.models import Book

MAX_CACHED_CHAPTERS = 16


@dataclass
class RenderedChapter:
    """已排版的章節。lines 為 rich Text；line_char 為每行對應的章內字元位置。"""
    lines: list = field(default_factory=list)
    line_char: list[int] = field(default_factory=list)
    line_is_para: list[bool] = field(default_factory=list)

    def __post_init__(self) -> None:
        self._para_lines = [i for i, p in enumerate(self.line_is_para) if p]
        self._para_chars = [self.line_char[i] for i in self._para_lines]

    def line_for_char(self, char_pos: int) -> int:
        if char_pos <= 0 or not self._para_lines:
            return 0
        idx = bisect.bisect_right(self._para_chars, char_pos) - 1
        return self._para_lines[max(0, idx)]


class Reader:
    def __init__(self) -> None:
        self.book: Book | None = None
        self.chapter = 0          # 畫面頂端所在章節
        self.offset = 0           # 頂端在該章中的行號
        self.page_h = 20
        self._docs: dict[int, RenderedChapter] = {}
        self._key = None
        self._builder: Callable[[int], RenderedChapter] | None = None
        self._anchor: tuple[int, int] | None = None   # 待恢復的 (章節, 字元位置)

    # ---- 書籍 ----------------------------------------------------------
    def set_book(self, book: Book, chapter: int = 0, char_pos: int = 0) -> None:
        self.book = book
        self._docs.clear()
        self._key = None
        self.offset = 0
        self.chapter = max(0, min(chapter, len(book.chapters) - 1))
        self._anchor = (self.chapter, char_pos)

    @property
    def chapter_count(self) -> int:
        return len(self.book.chapters) if self.book else 0

    # ---- 排版快取 ------------------------------------------------------
    def configure(self, key, builder: Callable[[int], RenderedChapter]) -> None:
        """設定排版參數；參數改變時清除快取並維持目前閱讀位置。"""
        if self.book is None:
            return
        if key != self._key:
            if self._key is not None and self._anchor is None:
                self._anchor = self.position()
            self._docs.clear()
            self._key = key
        self._builder = builder
        if self._anchor is not None:
            chapter, char_pos = self._anchor
            self._anchor = None
            self.chapter = max(0, min(chapter, self.chapter_count - 1))
            self.offset = self.doc_for(self.chapter).line_for_char(char_pos)
        self.clamp()

    def invalidate(self) -> None:
        if self.book is not None and self._key is not None and self._anchor is None:
            self._anchor = self.position()
        self._docs.clear()
        self._key = None

    def doc_for(self, index: int) -> RenderedChapter:
        doc = self._docs.get(index)
        if doc is None:
            doc = self._builder(index)
            self._docs[index] = doc
            if len(self._docs) > MAX_CACHED_CHAPTERS:
                far = max(self._docs, key=lambda i: abs(i - self.chapter))
                if far != index:
                    del self._docs[far]
        return doc

    @property
    def doc(self) -> RenderedChapter | None:
        if self.book is None or self._builder is None:
            return None
        return self.doc_for(self.chapter)

    def _len(self, index: int) -> int:
        return len(self.doc_for(index).lines)

    # ---- 可見內容 ------------------------------------------------------
    def visible(self, height: int | None = None) -> list[tuple[int, int]]:
        """回傳畫面上每一行的 (章節, 章內行號)。"""
        height = self.page_h if height is None else height
        rows: list[tuple[int, int]] = []
        ch, off = self.chapter, self.offset
        while len(rows) < height and ch < self.chapter_count:
            n = self._len(ch)
            take = min(n - off, height - len(rows))
            rows.extend((ch, i) for i in range(off, off + take))
            ch, off = ch + 1, 0
        return rows

    def visible_lines(self, height: int) -> list:
        return [self.doc_for(ch).lines[i] for ch, i in self.visible(height)]

    # ---- 捲動 ----------------------------------------------------------
    def _move(self, delta: int) -> None:
        ch, off = self.chapter, self.offset + delta
        while off < 0 and ch > 0:
            ch -= 1
            off += self._len(ch)
        off = max(0, off)
        while ch < self.chapter_count - 1 and off >= self._len(ch):
            off -= self._len(ch)
            ch += 1
        self.chapter, self.offset = ch, min(off, max(0, self._len(ch) - 1))

    def clamp(self) -> None:
        """捲動下限：最後一行停在畫面底部，或最後一章的標題停在頂端（取較後者），
        讓跳到短的末章時章節標題仍在畫面頂端。"""
        if self.book is None or self._builder is None:
            return
        self._move(0)
        last = self.chapter_count - 1
        if self.chapter < last:
            return
        remaining = len(self.visible(self.page_h))
        if remaining < self.page_h:
            self._move(-(self.page_h - remaining))
            if self.chapter < last:
                self.chapter, self.offset = last, 0

    def scroll(self, delta: int) -> bool:
        before = (self.chapter, self.offset)
        self._move(delta)
        self.clamp()
        return (self.chapter, self.offset) != before

    def page_down(self) -> bool:
        return self.scroll(max(1, self.page_h - 1))

    def page_up(self) -> bool:
        return self.scroll(-max(1, self.page_h - 1))

    def goto_chapter(self, index: int) -> bool:
        if not self.book or not (0 <= index < self.chapter_count):
            return False
        self.chapter, self.offset = index, 0
        self.clamp()
        return True

    def next_chapter(self) -> bool:
        return self.goto_chapter(self.chapter + 1)

    def prev_chapter(self) -> bool:
        # 不在章首時先回到本章開頭
        if self.offset > 0:
            return self.goto_chapter(self.chapter)
        return self.goto_chapter(self.chapter - 1)

    def chapter_start(self) -> None:
        self.chapter, self.offset = self.position()[0], 0
        self.clamp()

    def chapter_end(self) -> None:
        ch = self.position()[0]
        self.chapter, self.offset = ch, max(0, self._len(ch) - self.page_h)
        self.clamp()

    def at_end(self) -> bool:
        if not self.book or self._builder is None:
            return False
        rows = self.visible(self.page_h)
        return bool(rows) and rows[-1][0] == self.chapter_count - 1 and rows[-1][1] == self._len(rows[-1][0]) - 1

    # ---- 位置 ----------------------------------------------------------
    def position(self) -> tuple[int, int]:
        """(章節, 章內字元位置)：畫面上第一個可見的小說段落行。"""
        if self.book is None:
            return 0, 0
        if self._anchor is not None:
            return self._anchor
        if self._builder is None:
            return self.chapter, 0
        rows = self.visible(self.page_h)
        for ch, i in rows:
            doc = self.doc_for(ch)
            if doc.line_is_para[i]:
                return ch, doc.line_char[i]
        if not rows:
            return self.chapter, 0
        ch, i = rows[0]
        return ch, self.doc_for(ch).line_char[i]

    def current_chapter(self) -> int:
        return self.position()[0]

    def char_pos(self) -> int:
        return self.position()[1]

    def para_index(self) -> int:
        if not self.book:
            return 0
        ch, pos = self.position()
        offsets = self.book.chapters[ch].offsets
        return max(0, bisect.bisect_right(offsets, pos) - 1) if offsets else 0

    def book_char_pos(self) -> int:
        if not self.book:
            return 0
        ch, pos = self.position()
        return self.book.chapter_starts[ch] + pos

    def book_percent(self) -> float:
        if not self.book or self.book.total_chars <= 0:
            return 0.0
        if self.at_end():
            return 100.0
        return min(100.0, self.book_char_pos() * 100.0 / self.book.total_chars)

    def chapter_percent(self) -> float:
        if not self.book or self._builder is None:
            return 0.0
        ch = self.current_chapter()
        total = self._len(ch)
        rows = [i for c, i in self.visible(self.page_h) if c == ch]
        if not rows or total == 0:
            return 100.0
        return min(100.0, (rows[-1] + 1) * 100.0 / total)
