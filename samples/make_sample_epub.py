"""產生 samples/sample.epub（以 sample.txt 的章節內容建立，供測試 EPUB 解析）。

用法：python samples/make_sample_epub.py [輸出路徑]
"""
from __future__ import annotations

import html
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.novel_parser import parse_txt  # noqa: E402


def build(out_path: Path, source: Path) -> Path:
    from ebooklib import epub

    book_src = parse_txt(source)
    book = epub.EpubBook()
    book.set_identifier("novel-terminal-sample")
    book.set_title("霧港夜話（EPUB 範例）")
    book.set_language("zh-Hant")

    items = []
    for i, chapter in enumerate(book_src.chapters, 1):
        item = epub.EpubHtml(title=chapter.title, file_name=f"text/ch{i:02d}.xhtml", lang="zh-Hant")
        body = "".join(f"<p>{html.escape(p)}</p>" for p in chapter.paragraphs)
        # 加入行內標籤，確認解析時不會把段落切斷
        body = body.replace("祖父", "<em>祖父</em>", 1)
        item.content = f"<html><body><h2>{html.escape(chapter.title)}</h2>{body}</body></html>"
        book.add_item(item)
        items.append(item)

    book.toc = items
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ["nav", *items]
    epub.write_epub(str(out_path), book)
    return out_path


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "samples" / "sample.epub"
    print(build(target, ROOT / "samples" / "sample.txt"))
