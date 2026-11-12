"""EPUB 解析：依 spine 順序，一個內容文件對應一個章節，不合併不同章節。"""
from __future__ import annotations

import posixpath
import re
import warnings
from pathlib import Path
from urllib.parse import unquote

from core.models import Book, Chapter, NovelLoadError

_BLOCK_TAGS = [
    "p", "div", "h1", "h2", "h3", "h4", "h5", "h6", "li", "blockquote",
    "pre", "tr", "section", "article", "dd", "dt", "figcaption", "header", "footer",
]
_HEADING_TAGS = ["h1", "h2", "h3"]
_WS = re.compile(r"[ \t\r\f\v\xa0]+")


def _norm_href(href: str) -> str:
    href = unquote(href.split("#", 1)[0])
    return posixpath.normpath(href) if href else ""


def _toc_titles(toc, mapping: dict[str, str]) -> None:
    for entry in toc:
        if isinstance(entry, (tuple, list)) and len(entry) == 2:
            section, children = entry
            href = getattr(section, "href", None)
            title = getattr(section, "title", None)
            if href and title:
                mapping.setdefault(_norm_href(href), title.strip())
            _toc_titles(children, mapping)
        else:
            href = getattr(entry, "href", None)
            title = getattr(entry, "title", None)
            if href and title:
                mapping.setdefault(_norm_href(href), title.strip())


def _parser_name() -> str:
    try:
        import lxml  # noqa: F401
        return "lxml"
    except ImportError:
        return "html.parser"


def extract_paragraphs(html: bytes | str, parser: str = "html.parser") -> tuple[str | None, list[str]]:
    """從 XHTML 擷取 (第一個標題, 段落清單)。移除所有 HTML 標籤，保留段落分隔。"""
    from bs4 import BeautifulSoup, NavigableString

    # EPUB 內容多為 XHTML；以容錯的 HTML 解析器處理，避免格式不嚴謹的檔案解析失敗
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        soup = BeautifulSoup(html, parser)
    for tag in soup(["script", "style", "head", "svg", "noscript"]):
        tag.decompose()

    heading = None
    for tag in soup.find_all(_HEADING_TAGS):
        text = " ".join(tag.get_text(" ").split())
        if text:
            heading = text
            break

    for br in soup.find_all("br"):
        br.replace_with(NavigableString("\n"))
    for tag in soup.find_all(_BLOCK_TAGS):
        tag.insert_before(NavigableString("\n"))
        tag.append(NavigableString("\n"))

    root = soup.body or soup
    paragraphs = []
    for line in root.get_text().split("\n"):
        # HTML 中的半形空白無語意，壓縮成單一空白；全形空白（中文縮排）保留
        text = _WS.sub(" ", line).strip(" ")
        if text.strip():
            paragraphs.append(text)
    return heading, paragraphs


def parse_epub(path: Path) -> Book:
    try:
        import ebooklib
        from ebooklib import epub
    except ImportError as exc:
        raise NovelLoadError("Missing package ebooklib, run install.bat first") from exc
    try:
        import bs4  # noqa: F401
    except ImportError as exc:
        raise NovelLoadError("Missing package beautifulsoup4, run install.bat first") from exc

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            book = epub.read_epub(str(path), options={"ignore_ncx": False})
    except Exception as exc:  # ebooklib 會拋出各式例外（壞 zip、缺檔、DRM 等）
        raise NovelLoadError(f"Failed to parse EPUB: {exc}") from exc

    toc_map: dict[str, str] = {}
    try:
        _toc_titles(book.toc, toc_map)
    except Exception:
        toc_map = {}

    titles = book.get_metadata("DC", "title")
    book_title = titles[0][0].strip() if titles and titles[0][0] else path.stem
    parser = _parser_name()

    chapters: list[Chapter] = []
    seen: set[str] = set()
    for spine_entry in book.spine:
        idref = spine_entry[0] if isinstance(spine_entry, (tuple, list)) else spine_entry
        item = book.get_item_with_id(idref)
        if item is None or item.get_type() != ebooklib.ITEM_DOCUMENT:
            continue
        # EPUB3 導覽頁（目錄）不是正文
        if isinstance(item, epub.EpubNav) or "nav" in (getattr(item, "properties", None) or []):
            continue
        name = item.get_name()
        if name in seen:
            continue
        seen.add(name)
        try:
            heading, paragraphs = extract_paragraphs(item.get_content(), parser)
        except Exception:
            continue
        if not paragraphs:
            continue  # 封面圖片頁、空白頁
        title = toc_map.get(_norm_href(name)) or heading or f"Section {len(chapters) + 1}"
        if paragraphs and paragraphs[0].strip() == title.strip():
            paragraphs = paragraphs[1:]
        if not paragraphs:
            continue
        chapters.append(Chapter(title, paragraphs))

    if not chapters:
        raise NovelLoadError("No readable text in EPUB (image-only or DRM protected)")
    return Book(path=path, title=book_title, fmt="EPUB", encoding="UTF-8", chapters=chapters)
