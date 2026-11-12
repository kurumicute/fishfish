"""傳統 CMD 視窗 (conhost) 的字型大小調整（盡力而為）。

Windows Terminal、VS Code 終端機等不支援由程式更改字型，此時只使用欄寬與行距模擬。
"""
from __future__ import annotations

import os
import sys


class ConsoleFont:
    def __init__(self) -> None:
        self.supported = (
            sys.platform == "win32"
            and not os.environ.get("WT_SESSION")
            and not os.environ.get("TERM_PROGRAM")
        )
        self._original = None
        if self.supported:
            try:
                self._setup()
                self._original = self._get()
                if self._original is None:
                    self.supported = False
            except Exception:
                self.supported = False

    def _setup(self) -> None:
        import ctypes
        from ctypes import wintypes

        class COORD(ctypes.Structure):
            _fields_ = [("X", wintypes.SHORT), ("Y", wintypes.SHORT)]

        class FONTINFO(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.ULONG), ("nFont", wintypes.DWORD),
                        ("dwFontSize", COORD), ("FontFamily", wintypes.UINT),
                        ("FontWeight", wintypes.UINT), ("FaceName", wintypes.WCHAR * 32)]

        self._ct = ctypes
        self._info_cls = FONTINFO
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.GetStdHandle.restype = wintypes.HANDLE
        k32.GetCurrentConsoleFontEx.argtypes = [wintypes.HANDLE, wintypes.BOOL, ctypes.POINTER(FONTINFO)]
        k32.SetCurrentConsoleFontEx.argtypes = [wintypes.HANDLE, wintypes.BOOL, ctypes.POINTER(FONTINFO)]
        self._k32 = k32
        self._handle = k32.GetStdHandle(-11)

    def _get(self):
        info = self._info_cls()
        info.cbSize = self._ct.sizeof(info)
        if not self._k32.GetCurrentConsoleFontEx(self._handle, False, self._ct.byref(info)):
            return None
        return info

    def set_height(self, px: int) -> bool:
        if not self.supported:
            return False
        try:
            info = self._get()
            if info is None:
                return False
            info.dwFontSize.X = 0
            info.dwFontSize.Y = int(px)
            return bool(self._k32.SetCurrentConsoleFontEx(self._handle, False, self._ct.byref(info)))
        except Exception:
            return False

    def restore(self) -> None:
        if self.supported and self._original is not None:
            try:
                self._k32.SetCurrentConsoleFontEx(self._handle, False, self._ct.byref(self._original))
            except Exception:
                pass
