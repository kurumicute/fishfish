"""文字編碼偵測：UTF-8 / UTF-8 BOM / UTF-16 / Big5 / GB18030。"""
from __future__ import annotations

# 繁簡常用字，用來判斷哪一種解碼結果比較像正常中文
_COMMON = set(
    "的一是不了在人有我他這这個个們们中來来上大為为和國国地到以說说時时要就出會会可也你"
    "對对生能而子那得於于著着下自之年過过發发後后作裡里她看沒没道還还心事去如麼么"
)


def _score(text: str) -> float:
    sample = text[:30000]
    if not sample:
        return 0.0
    common = sum(1 for ch in sample if ch in _COMMON)
    bad = sample.count("�")
    return (common - bad * 5) / len(sample)


def decode_bytes(data: bytes) -> tuple[str, str]:
    """回傳 (文字, 編碼名稱)。不會拋出例外，最差情況以替換字元解碼。"""
    if data.startswith(b"\xef\xbb\xbf"):
        return data[3:].decode("utf-8", errors="replace"), "UTF-8 BOM"
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16", errors="replace"), "UTF-16"

    try:
        return data.decode("utf-8"), "UTF-8"
    except UnicodeDecodeError:
        pass

    # 嚴格解碼成功的候選，用常用字比例挑選
    candidates: list[tuple[float, str, str]] = []
    for codec, label in (("cp950", "Big5"), ("big5hkscs", "Big5-HKSCS"), ("gb18030", "GB18030")):
        try:
            text = data.decode(codec)
        except UnicodeDecodeError:
            continue
        candidates.append((_score(text), text, label))
    if candidates:
        candidates.sort(key=lambda c: c[0], reverse=True)
        return candidates[0][1], candidates[0][2]

    # 少量損壞位元組的 UTF-8（例如檔案被截斷）
    text = data.decode("utf-8", errors="replace")
    if text.count("�") <= max(3, len(text) // 1000):
        return text, "UTF-8"

    loose = []
    for codec, label in (("cp950", "Big5"), ("gb18030", "GB18030")):
        t = data.decode(codec, errors="replace")
        loose.append((_score(t), t, label + " (partial)"))
    loose.sort(key=lambda c: c[0], reverse=True)
    return loose[0][1], loose[0][2]
