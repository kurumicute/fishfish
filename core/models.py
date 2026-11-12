"""小說資料模型。"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


class NovelLoadError(Exception):
    """小說或程式碼檔讀取失敗（訊息直接顯示給使用者）。"""


@dataclass
class Chapter:
    title: str
    paragraphs: list[str]
    offsets: list[int] = field(default_factory=list, init=False)
    char_count: int = field(default=0, init=False)

    def __post_init__(self) -> None:
        total = 0
        self.offsets = []
        for para in self.paragraphs:
            self.offsets.append(total)
            total += len(para)
        self.char_count = total

    def offset_of(self, para_index: int) -> int:
        if para_index < 0:
            return 0
        if para_index >= len(self.offsets):
            return self.char_count
        return self.offsets[para_index]


@dataclass
class Book:
    path: Path
    title: str
    fmt: str
    encoding: str
    chapters: list[Chapter]
    chapter_starts: list[int] = field(default_factory=list, init=False)
    total_chars: int = field(default=0, init=False)

    def __post_init__(self) -> None:
        total = 0
        self.chapter_starts = []
        for chapter in self.chapters:
            self.chapter_starts.append(total)
            total += chapter.char_count
        self.total_chars = total
