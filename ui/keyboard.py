"""Keyboard input without echo.

Windows: ReadConsoleInputW (key events with modifier state, so Shift+Tab can be
told apart from Tab; works in conhost, Windows Terminal and other ConPTY hosts),
falling back to msvcrt. Other platforms: termios.
"""
from __future__ import annotations

import os
import sys
import time

WIN_SPECIAL = {
    "H": "UP", "P": "DOWN", "K": "LEFT", "M": "RIGHT", "I": "PGUP", "Q": "PGDN",
    "G": "HOME", "O": "END", "S": "DELETE", "\x0f": "SHIFT_TAB",
}
ANSI_SEQ = {
    "[A": "UP", "[B": "DOWN", "[C": "RIGHT", "[D": "LEFT", "[5~": "PGUP", "[6~": "PGDN",
    "[Z": "SHIFT_TAB", "[H": "HOME", "[F": "END", "[1~": "HOME", "[4~": "END", "[3~": "DELETE",
    "OH": "HOME", "OF": "END",
}
CONTROL = {"\r": "ENTER", "\n": "ENTER", "\x08": "BACKSPACE", "\x7f": "BACKSPACE",
           "\x1b": "ESC", "\t": "TAB", "\x03": "CTRL_C", "\x11": "CTRL_Q"}

VK_NAMES = {
    0x21: "PGUP", 0x22: "PGDN", 0x23: "END", 0x24: "HOME", 0x25: "LEFT", 0x26: "UP",
    0x27: "RIGHT", 0x28: "DOWN", 0x2E: "DELETE", 0x0D: "ENTER", 0x08: "BACKSPACE", 0x1B: "ESC",
}
SHIFT_PRESSED = 0x0010
LEFT_CTRL, RIGHT_CTRL = 0x0008, 0x0004


class _WinConsoleInput:
    def __init__(self) -> None:
        import ctypes
        from ctypes import wintypes

        class KEY_EVENT_RECORD(ctypes.Structure):
            _fields_ = [("bKeyDown", wintypes.BOOL), ("wRepeatCount", wintypes.WORD),
                        ("wVirtualKeyCode", wintypes.WORD), ("wVirtualScanCode", wintypes.WORD),
                        ("uChar", wintypes.WCHAR), ("dwControlKeyState", wintypes.DWORD)]

        class MOUSE_EVENT_RECORD(ctypes.Structure):
            _fields_ = [("X", wintypes.SHORT), ("Y", wintypes.SHORT), ("dwButtonState", wintypes.DWORD),
                        ("dwControlKeyState", wintypes.DWORD), ("dwEventFlags", wintypes.DWORD)]

        class EVENT_UNION(ctypes.Union):
            _fields_ = [("KeyEvent", KEY_EVENT_RECORD), ("MouseEvent", MOUSE_EVENT_RECORD),
                        ("_pad", ctypes.c_byte * 16)]

        class INPUT_RECORD(ctypes.Structure):
            _fields_ = [("EventType", wintypes.WORD), ("Event", EVENT_UNION)]

        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.GetStdHandle.restype = wintypes.HANDLE
        k32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        k32.WaitForSingleObject.restype = wintypes.DWORD
        k32.GetNumberOfConsoleInputEvents.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        k32.ReadConsoleInputW.argtypes = [wintypes.HANDLE, ctypes.POINTER(INPUT_RECORD),
                                          wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
        k32.GetConsoleMode.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        k32.SetConsoleMode.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        self._ct, self._wt, self._k32 = ctypes, wintypes, k32
        self._rec = INPUT_RECORD
        self._handle = k32.GetStdHandle(-10)
        count = wintypes.DWORD()
        if not k32.GetNumberOfConsoleInputEvents(self._handle, ctypes.byref(count)):
            raise OSError("stdin is not a console")
        self._high = ""   # pending UTF-16 high surrogate
        # Deliver Ctrl+C as a key event (like Claude Code) instead of a signal, so it
        # always reaches the reader and progress is saved before exit.
        self._mode = wintypes.DWORD()
        self._saved_mode = None
        if k32.GetConsoleMode(self._handle, ctypes.byref(self._mode)):
            self._saved_mode = self._mode.value
            # - ENABLE_PROCESSED_INPUT (Ctrl+C as key), - ENABLE_QUICK_EDIT_MODE,
            # + ENABLE_MOUSE_INPUT (wheel scrolling) + ENABLE_EXTENDED_FLAGS
            mode = (self._saved_mode & ~0x0001 & ~0x0040) | 0x0010 | 0x0080
            k32.SetConsoleMode(self._handle, mode)

    def close(self) -> None:
        if self._saved_mode is not None:
            self._k32.SetConsoleMode(self._handle, self._saved_mode)
            self._saved_mode = None

    def read(self, timeout: float, limit: int) -> list[str]:
        ct, wt, k32 = self._ct, self._wt, self._k32
        if k32.WaitForSingleObject(self._handle, int(timeout * 1000)) != 0:
            return []
        count = wt.DWORD()
        k32.GetNumberOfConsoleInputEvents(self._handle, ct.byref(count))
        if not count.value:
            return []
        buf = (self._rec * min(count.value, 512))()
        read = wt.DWORD()
        if not k32.ReadConsoleInputW(self._handle, buf, len(buf), ct.byref(read)):
            return []
        keys: list[str] = []
        for rec in buf[: read.value]:
            if rec.EventType == 2:          # MOUSE_EVENT: wheel scrolling
                me = rec.Event.MouseEvent
                if me.dwEventFlags & 0x0004:  # MOUSE_WHEELED
                    delta = ct.c_short((me.dwButtonState >> 16) & 0xFFFF).value
                    keys.append("WHEEL_UP" if delta > 0 else "WHEEL_DOWN")
                continue
            if rec.EventType != 1:          # KEY_EVENT
                continue
            ev = rec.Event.KeyEvent
            if not ev.bKeyDown:
                continue
            vk, ch, state = ev.wVirtualKeyCode, ev.uChar, ev.dwControlKeyState
            for _ in range(max(1, ev.wRepeatCount)):
                if vk == 0x09:
                    keys.append("SHIFT_TAB" if state & SHIFT_PRESSED else "TAB")
                elif vk in VK_NAMES:
                    keys.append(VK_NAMES[vk])
                elif ch == "\x03" or (vk == 0x43 and state & (LEFT_CTRL | RIGHT_CTRL)):
                    keys.append("CTRL_C")
                elif ch and ch != "\x00":
                    if "\ud800" <= ch <= "\udbff":
                        self._high = ch
                        continue
                    if "\udc00" <= ch <= "\udfff" and self._high:
                        ch = (self._high + ch).encode("utf-16", "surrogatepass").decode("utf-16")
                        self._high = ""
                    keys.append(CONTROL.get(ch, ch))
            if len(keys) >= limit:
                break
        return keys


class Keyboard:
    def __init__(self) -> None:
        self.windows = sys.platform == "win32"
        self._old = None
        self._win = None
        if self.windows:
            try:
                self._win = _WinConsoleInput()
            except Exception:
                self._win = None          # fall back to msvcrt
        else:
            import termios
            import tty
            self._fd = sys.stdin.fileno()
            self._old = termios.tcgetattr(self._fd)
            tty.setcbreak(self._fd)
            attrs = termios.tcgetattr(self._fd)
            attrs[0] &= ~termios.IXON          # let Ctrl+Q reach the app (no XON/XOFF)
            termios.tcsetattr(self._fd, termios.TCSADRAIN, attrs)

    def close(self) -> None:
        if self._win is not None:
            self._win.close()
        if self._old is not None:
            import termios
            termios.tcsetattr(self._fd, termios.TCSADRAIN, self._old)
            self._old = None

    def read_keys(self, timeout: float = 0.05, limit: int = 256) -> list[str]:
        """Wait up to `timeout` seconds and return all pending keys (pastes arrive at once)."""
        if self._win is not None:
            return self._win.read(timeout, limit)
        return self._read_msvcrt(timeout, limit) if self.windows else self._read_posix(timeout, limit)

    def _read_msvcrt(self, timeout: float, limit: int) -> list[str]:
        import msvcrt
        deadline = time.monotonic() + timeout
        while not msvcrt.kbhit():
            if time.monotonic() >= deadline:
                return []
            time.sleep(0.01)
        keys: list[str] = []
        while msvcrt.kbhit() and len(keys) < limit:
            ch = msvcrt.getwch()
            if ch in ("\x00", "\xe0"):
                code = msvcrt.getwch()
                if code in WIN_SPECIAL:
                    keys.append(WIN_SPECIAL[code])
                continue
            keys.append(CONTROL.get(ch, ch))
        return keys

    def _read_posix(self, timeout: float, limit: int) -> list[str]:
        import select
        fd = self._fd
        ready, _, _ = select.select([fd], [], [], timeout)
        if not ready:
            return []
        data = os.read(fd, 4096).decode("utf-8", errors="ignore")
        keys: list[str] = []
        i = 0
        while i < len(data) and len(keys) < limit:
            ch = data[i]
            if ch == "\x1b" and i + 1 < len(data):
                for seq, name in ANSI_SEQ.items():
                    if data.startswith(seq, i + 1):
                        keys.append(name)
                        i += 1 + len(seq)
                        break
                else:
                    keys.append("ESC")
                    i += 1
                continue
            keys.append(CONTROL.get(ch, ch))
            i += 1
        return keys
