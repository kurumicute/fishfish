"""Simulated terminal workflow. Every message comes from local templates;
no external service or AI API is ever contacted."""
from __future__ import annotations

import random
import time
from collections import deque
from dataclasses import dataclass, field

# (title, steps, done)
TASKS = {
    "en": [
        ("Reading current document", ["Checking document structure...", "Analyzing paragraphs...", "Verifying context..."], "Document loaded"),
        ("Processing next section", ["Reading next block...", "Checking continuity...", "Updating work state..."], "Section processed"),
        ("Analyzing paragraph structure", ["Measuring paragraph length...", "Checking line breaks...", "Comparing punctuation..."], "Structure analysis complete"),
        ("Checking current context", ["Reading previous index...", "Matching chapter info...", "Verifying references..."], "Context check complete"),
        ("Organizing document content", ["Ordering paragraphs...", "Merging cached results...", "Writing local cache..."], "Document organized"),
        ("Verifying next block", ["Prefetching next block...", "Checking encoding...", "Validating integrity..."], "Next block verified"),
        ("Updating work state", ["Writing work log...", "Syncing local state...", "Updating progress index..."], "Work state updated"),
        ("Loading next section", ["Locating section start...", "Reading section content...", "Building temp index..."], "Section loaded"),
        ("Running document check", ["Scanning file format...", "Checking UTF-8 encoding...", "Checking line endings..."], "Document check complete"),
    ],
    "zh": [
        ("正在讀取目前文件", ["檢查文件結構...", "分析段落內容...", "確認目前上下文..."], "文件載入完成"),
        ("正在處理下一個區段", ["正在讀取下一段...", "檢查內容連續性...", "更新工作狀態..."], "區段處理完成"),
        ("正在分析段落結構", ["統計段落長度...", "檢查換行格式...", "比對標點符號..."], "段落結構分析完成"),
        ("檢查目前上下文", ["讀取前文索引...", "比對章節資訊...", "確認引用位置..."], "上下文檢查完成"),
        ("正在整理文件內容", ["整理段落順序...", "合併暫存結果...", "寫入本機快取..."], "文件整理完成"),
        ("確認下一段內容", ["預讀下一段...", "檢查字元編碼...", "驗證內容完整性..."], "下一段內容確認完成"),
        ("正在更新工作狀態", ["寫入工作紀錄...", "同步本機狀態...", "更新進度索引..."], "工作狀態已更新"),
        ("正在載入下一個區段", ["定位區段起點...", "讀取區段內容...", "建立暫存索引..."], "區段載入完成"),
        ("執行文件檢查", ["掃描文件格式...", "檢查 UTF-8 編碼...", "確認行尾格式..."], "文件檢查完成"),
    ],
}

STATUS_LINES = {
    "en": [
        "Read {chars:,} chars ({ms} ms)",
        "Updated local cache · {n} sections",
        "Work state: OK · LOCAL",
        "Indexed {n} records",
        "No issues found",
        "Processed {paras} paragraphs ({ms} ms)",
        "Encoding check passed · UTF-8",
        "Found {n} matches",
    ],
    "zh": [
        "已讀取 {chars:,} 字元 · {ms} ms",
        "本機快取已更新 · {n} 個區段",
        "工作狀態：正常 · LOCAL",
        "索引完成 · {n} 筆紀錄",
        "檢查通過 · 0 個警告",
        "已處理 {paras} 個段落 · {ms} ms",
        "編碼檢查完成 · UTF-8",
    ],
}

OPEN_TASK = {
    "en": ("Reading current document", ["Checking document structure...", "Analyzing paragraphs...", "Verifying context..."], "Document loaded"),
    "zh": ("正在讀取目前文件", ["檢查文件結構...", "分析段落內容...", "確認目前上下文..."], "文件載入完成"),
}
CHAPTER_TASK = {
    "en": ("Processing next section", ["Reading next block...", "Checking continuity...", "Updating work state..."], "Section processed"),
    "zh": ("正在處理下一個區段", ["正在讀取下一段...", "檢查內容連續性...", "更新工作狀態..."], "區段處理完成"),
}

# seconds a notice stays on the status row
NOTICE_TTL = {"ok": 8.0, "info": 10.0, "warn": 15.0, "error": 20.0}


@dataclass
class ActiveTask:
    title: str
    steps: list[str]
    done: str
    start: float
    step_times: list[float]
    end: float
    external: bool = False        # waits for real work (e.g. file loading)
    logged_steps: int = 0


@dataclass
class StatusSnapshot:
    state: str                     # running | ok | warn | error | info | idle
    title: str
    detail: str = ""
    elapsed: int = 0
    spin: int = 0
    since: float = 0.0


@dataclass
class TerminalEngine:
    lang: str = "en"
    min_interval: float = 35
    max_interval: float = 90
    ambient_enabled: bool = True
    rng: random.Random = field(default_factory=random.Random)
    log: deque = field(default_factory=lambda: deque(maxlen=500))

    def __post_init__(self) -> None:
        if self.lang not in TASKS:
            self.lang = "en"
        self.active: ActiveTask | None = None
        self.status = StatusSnapshot("idle", "")
        self._spin_frame = -1
        self.next_ambient = time.monotonic() + self._interval()

    # ---- templates ---------------------------------------------------
    def _interval(self) -> float:
        lo = max(5.0, float(self.min_interval))
        hi = max(lo, float(self.max_interval))
        return self.rng.uniform(lo, hi)

    def random_task(self, rng: random.Random) -> tuple[str, list[str], str]:
        title, steps, done = rng.choice(TASKS[self.lang])
        count = rng.randint(1, len(steps))
        return title, steps[:count], done

    def random_status(self, rng: random.Random, chars: int, paras: int) -> str:
        template = rng.choice(STATUS_LINES[self.lang])
        return template.format(chars=chars, paras=paras, ms=rng.randint(12, 480), n=rng.randint(3, 64))

    # ---- log / notices -------------------------------------------------
    def add_log(self, kind: str, text: str) -> None:
        self.log.append((time.strftime("%H:%M:%S"), kind, text))

    def clear(self) -> None:
        self.log.clear()
        self.active = None
        self.status = StatusSnapshot("idle", "")

    def _set_status(self, kind: str, text: str, detail: str = "") -> None:
        self.status = StatusSnapshot(kind, text, detail, since=time.monotonic())

    def notify(self, text: str, kind: str = "ok", detail: str = "") -> None:
        """Command result. It takes precedence over a simulated task (which is
        completed silently); while a real load is running only the log receives it."""
        task = self.active
        if task is not None and not task.external:
            for step in task.steps[task.logged_steps:]:
                self.add_log("step", step)
            self.add_log("ok", task.done)
            self.active = None
            self.next_ambient = time.monotonic() + self._interval()
        self.add_log(kind, text)
        if self.active is None:
            self._set_status(kind, text, detail)

    # ---- workflow ------------------------------------------------------
    def start_task(self, title: str, steps: list[str], done: str, *, external: bool = False,
                   now: float | None = None) -> None:
        now = time.monotonic() if now is None else now
        times, t = [], now
        for _ in steps:
            t += self.rng.uniform(0.45, 1.1)
            times.append(t)
        self.active = ActiveTask(title, list(steps), done, now, times, t + self.rng.uniform(0.3, 0.8), external)
        self.add_log("run", title)

    def start_named(self, table: dict, *, external: bool = False) -> None:
        title, steps, done = table[self.lang]
        self.start_task(title, steps, done, external=external)

    def finish_external(self, ok: bool = True, text: str | None = None, detail: str = "") -> None:
        task = self.active
        if task is None:
            if text:
                self.notify(text, "ok" if ok else "error", detail)
            return
        for step in task.steps[task.logged_steps:]:
            self.add_log("step", step)
        self.active = None
        message = text or task.done
        self.add_log("ok" if ok else "error", message)
        self._set_status("ok" if ok else "error", message, detail)

    def interrupt(self) -> bool:
        """Esc while a simulated task runs (file loading cannot be interrupted)."""
        if self.active is None or self.active.external:
            return False
        self.active = None
        self.notify("Interrupted by user", "error")
        self.next_ambient = time.monotonic() + self._interval()
        return True

    def tick(self, now: float | None = None) -> bool:
        """Advance the workflow; return True when the screen needs a redraw."""
        now = time.monotonic() if now is None else now
        task = self.active
        if task is not None:
            changed = False
            reached = sum(1 for t in task.step_times if now >= t)
            while task.logged_steps < reached:
                self.add_log("step", task.steps[task.logged_steps])
                task.logged_steps += 1
                changed = True
            if not task.external and now >= task.end:
                self.active = None
                self.add_log("ok", task.done)
                self._set_status("ok", task.done)
                self.status.since = now
                self.next_ambient = now + self._interval()
                return True
            frame = int((now - task.start) / 0.12)
            if frame != self._spin_frame:
                self._spin_frame = frame
                changed = True
            return changed
        st = self.status
        if st.state != "idle" and now - st.since > NOTICE_TTL.get(st.state, 10.0):
            self.status = StatusSnapshot("idle", "")
            return True
        if self.ambient_enabled and now >= self.next_ambient:
            title, steps, done = self.random_task(self.rng)
            self.start_task(title, steps, done, now=now)
            return True
        return False

    def snapshot(self, now: float | None = None) -> StatusSnapshot:
        now = time.monotonic() if now is None else now
        task = self.active
        if task is None:
            return self.status
        idx = min(task.logged_steps, len(task.steps) - 1) if task.steps else -1
        detail = task.steps[idx] if idx >= 0 else ""
        return StatusSnapshot("running", task.title, detail, int(now - task.start), int((now - task.start) / 0.12))
