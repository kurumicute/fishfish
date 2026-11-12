"""小說檔案載入：依副檔名分派至 TXT / EPUB 解析器。"""
from __future__ import annotations

import re
from pathlib import Path

from core.encoding import decode_bytes
from core.models import Book, Chapter, NovelLoadError

SUPPORTED = {".txt": "TXT", ".epub": "EPUB"}
PREFACE = "Preface"

_NUM = r"[0-9０-９零〇○一二兩两三四五六七八九十百千萬万壹貳參肆伍陸柒捌玖拾佰仟]+"
_SEP = r"(?=$|[\s　:：、.．\-—－·・(（【\[《「])"
# 第一章 / 第12回 / 第三卷 第五節 ...（標題行通常很短，允許標題緊接文字，例如「第1章初入江湖」）
_RE_NUMBERED = re.compile(rf"^[\s　]*第[\s　]*{_NUM}[\s　]*[章回節节卷集部篇話话幕]")
_RE_KEYWORD = re.compile(
    r"^[\s　]*(?:序章|序言|序幕|序|楔子|引子|引言|前言|後記|后记|尾聲|尾声|終章|终章|番外篇?|後日談|后日谈)" + _SEP
)
_RE_ENGLISH = re.compile(r"^\s*(?:chapter|prologue|epilogue)\b(?:\s+\d+)?", re.IGNORECASE)


def is_chapter_heading(line: str) -> bool:
    stripped = line.strip()
    if not stripped or len(stripped) > 40:
        return False
    return bool(
        _RE_NUMBERED.match(stripped) or _RE_KEYWORD.match(stripped) or _RE_ENGLISH.match(stripped)
    )


def load_book(path, *, max_file_mb: float = 200, auto_section_chars: int = 4000,
              max_chapter_chars: int = 30000) -> Book:
    p = Path(str(path)).expanduser()
    if not p.exists():
        raise NovelLoadError(f"File not found: {p}")
    if p.is_dir():
        raise NovelLoadError(f"Is a directory, not a novel file: {p}")
    suffix = p.suffix.lower()
    if suffix not in SUPPORTED:
        raise NovelLoadError(
            f"Unsupported file format '{suffix or 'no extension'}' (supported: TXT, EPUB)"
        )
    try:
        size = p.stat().st_size
    except OSError as exc:
        raise NovelLoadError(f"Cannot stat file: {exc}") from exc
    if size > max_file_mb * 1024 * 1024:
        raise NovelLoadError(f"File too large ({size / 1024 / 1024:.1f} MB), limit is {max_file_mb} MB")

    if suffix == ".epub":
        from core.epub_parser import parse_epub
        book = parse_epub(p)
    else:
        book = parse_txt(p, auto_section_chars)
    book.chapters[:] = split_oversized(book.chapters, max_chapter_chars)
    book.__post_init__()
    return book


def parse_txt(path: Path, auto_section_chars: int = 4000) -> Book:
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise NovelLoadError(f"Cannot read file: {exc}") from exc
    text, encoding = decode_bytes(data)
    chapters = split_chapters(text, auto_section_chars)
    if not chapters or not any(c.paragraphs for c in chapters):
        raise NovelLoadError("No readable text in file")
    return Book(path=path, title=path.stem, fmt="TXT", encoding=encoding, chapters=chapters)


def split_chapters(text: str, auto_section_chars: int = 4000) -> list[Chapter]:
    """依章節標題切割；每個非空行視為一個段落，保留行首縮排與原始標點。"""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    chapters: list[Chapter] = []
    title: str | None = None
    paras: list[str] = []
    found_heading = False

    for raw in text.split("\n"):
        line = raw.rstrip()
        if not line.strip():
            continue
        if is_chapter_heading(line):
            if paras or title is not None:
                chapters.append(Chapter(title if title is not None else PREFACE, paras))
            title = line.strip()
            paras = []
            found_heading = True
            continue
        paras.append(line)
    if paras or title is not None:
        chapters.append(Chapter(title if title is not None else PREFACE, paras))

    if not found_heading:
        all_paras = [p for c in chapters for p in c.paragraphs]
        return auto_sections(all_paras, auto_section_chars)
    return chapters


def auto_sections(paragraphs: list[str], section_chars: int) -> list[Chapter]:
    """沒有章節標題的 TXT：依字數切成「片段」，方便翻章與保存進度。"""
    sections: list[Chapter] = []
    current: list[str] = []
    count = 0
    for para in paragraphs:
        current.append(para)
        count += len(para)
        if count >= section_chars:
            sections.append(Chapter(f"Part {len(sections) + 1}", current))
            current, count = [], 0
    if current:
        sections.append(Chapter(f"Part {len(sections) + 1}", current))
    return sections


def split_oversized(chapters: list[Chapter], max_chars: int) -> list[Chapter]:
    """單章過長時切成多個部分（只切在段落邊界，不改動內容），避免單次排版過久。"""
    if max_chars <= 0:
        return chapters
    result: list[Chapter] = []
    for chapter in chapters:
        if chapter.char_count <= max_chars:
            result.append(chapter)
            continue
        parts: list[list[str]] = [[]]
        count = 0
        for para in chapter.paragraphs:
            if count >= max_chars and parts[-1]:
                parts.append([])
                count = 0
            parts[-1].append(para)
            count += len(para)
        for i, part in enumerate(parts):
            title = chapter.title if i == 0 else f"{chapter.title} (cont. {i + 1})"
            result.append(Chapter(title, part))
    return result
