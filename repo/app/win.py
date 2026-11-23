# -*- coding: utf-8 -*-
"""Windows 窗口小工具：找 Edge 窗口、置前、发 Ctrl+S、摆位置。"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import difflib
import os
import time

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

SW_RESTORE = 9
VK_CONTROL = 0x11
VK_S = 0x53
KEYEVENTF_KEYUP = 0x0002


def screen_size() -> tuple:
    return user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)


def _titles():
    out = []

    @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    def cb(hwnd, lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        n = user32.GetWindowTextLengthW(hwnd)
        if n == 0:
            return True
        buf = ctypes.create_unicode_buffer(n + 1)
        user32.GetWindowTextW(hwnd, buf, n + 1)
        out.append((hwnd, buf.value))
        return True

    user32.EnumWindows(cb, 0)
    return out


def find_window(needles) -> int:
    """按标题片段找窗口，返回 hwnd（0 表示没找到）。"""
    if isinstance(needles, str):
        needles = [needles]
    needles = [n.lower() for n in needles if n]
    for hwnd, title in _titles():
        low = title.lower()
        if any(n in low for n in needles):
            return hwnd
    return 0


def activate(hwnd: int) -> bool:
    if not hwnd:
        return False
    try:
        user32.ShowWindow(hwnd, SW_RESTORE)
        user32.SetForegroundWindow(hwnd)
        time.sleep(0.08)
        return True
    except Exception:
        return False


def send_ctrl_s(hwnd: int) -> bool:
    """让 Edge 把墨迹保存进 PDF。"""
    if not activate(hwnd):
        return False
    time.sleep(0.15)
    user32.keybd_event(VK_CONTROL, 0, 0, 0)
    user32.keybd_event(VK_S, 0, 0, 0)
    time.sleep(0.03)
    user32.keybd_event(VK_S, 0, KEYEVENTF_KEYUP, 0)
    user32.keybd_event(VK_CONTROL, 0, KEYEVENTF_KEYUP, 0)
    time.sleep(0.35)
    return True


def layout(hwnd: int, x: int, y: int, w: int, h: int) -> bool:
    if not hwnd:
        return False
    try:
        if user32.IsIconic(wt.HWND(hwnd)):
            user32.ShowWindow(wt.HWND(hwnd), SW_RESTORE)
        user32.MoveWindow(wt.HWND(hwnd), int(x), int(y), int(w), int(h), True)
        return True
    except Exception:
        return False


HWND_TOPMOST = -1
HWND_NOTOPMOST = -2
GWL_EXSTYLE = -20
WS_EX_TOPMOST = 0x00000008


def is_topmost(hwnd: int) -> bool:
    if not hwnd:
        return False
    style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
    return bool(style & WS_EX_TOPMOST)


_SETPOS = user32.SetWindowPos
_SETPOS.argtypes = [wt.HWND, wt.HWND, ctypes.c_int, ctypes.c_int,
                    ctypes.c_int, ctypes.c_int, ctypes.c_uint]
_SETPOS.restype = wt.BOOL
user32.GetWindowLongW.restype = ctypes.c_long


def set_topmost(hwnd: int, on: bool = True) -> bool:
    if not hwnd:
        return False
    after = ctypes.c_void_p(0xFFFFFFFFFFFFFFFF if on else 0xFFFFFFFFFFFFFFFE)
    return bool(_SETPOS(wt.HWND(hwnd), after, 0, 0, 0, 0, 0x0002 | 0x0001))


PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


def _pid_of(hwnd: int) -> int:
    pid = wt.DWORD()
    user32.GetWindowThreadProcessId(wt.HWND(hwnd), ctypes.byref(pid))
    return pid.value


def _exe_of(pid: int) -> str:
    h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = wt.DWORD(1024)
        if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            return buf.value
        return ""
    finally:
        kernel32.CloseHandle(h)


def find_panel(hint: str = "") -> int:
    """只认 Edge 进程、标题以「AI 批注」结尾的窗口，避免误伤别的程序。"""
    for hwnd, title in _titles():
        t = title.strip()
        if not t.endswith("AI 批注"):
            continue
        if hint and hint not in t:
            continue
        if "msedge" not in _exe_of(_pid_of(hwnd)).lower():
            continue
        return hwnd
    return 0


ISICONIC = 0x20000000


def get_rect(hwnd: int):
    r = wt.RECT()
    if not hwnd or not user32.GetWindowRect(wt.HWND(hwnd), ctypes.byref(r)):
        return None
    return (r.left, r.top, r.right, r.bottom)


def is_minimized(hwnd: int) -> bool:
    return bool(user32.IsIconic(wt.HWND(hwnd)))


def find_window_live(needles) -> int:
    """在标题匹配的窗口里挑面积最大、未最小化的那个。"""
    if isinstance(needles, str):
        needles = [needles]
    needles = [n.lower() for n in needles if n]
    best, best_score = 0, -1
    for hwnd, title in _titles():
        low = title.lower()
        if not any(n in low for n in needles):
            continue
        r = get_rect(hwnd)
        area = ((r[2] - r[0]) * (r[3] - r[1])) if r else 0
        score = 0 if is_minimized(hwnd) else area
        if score > best_score:
            best, best_score = hwnd, score
    return best


def close_others(title_hint: str, keep_hwnd: int) -> int:
    """关掉标题含 title_hint 的其它 Edge 窗口（同一本书只留一个）。"""
    if not title_hint:
        return 0
    n = 0
    for hwnd, title in _titles():
        if hwnd == keep_hwnd:
            continue
        if title_hint.lower() not in title.lower():
            continue
        if "msedge" not in _exe_of(_pid_of(hwnd)).lower():
            continue
        user32.PostMessageW(wt.HWND(hwnd), 0x0010, 0, 0)
        n += 1
    return n


def norm_text(s: str) -> str:
    import urllib.parse
    s = urllib.parse.unquote(s or "")
    s = s.replace("\u200b", "").replace("\u200e", "")
    s = s.lower()
    for ch in " \t\r\n_":
        s = s.replace(ch, "")
    return s


def find_by_pdf(pdf_path: str) -> int:
    """按 PDF 完整文件名找窗口；面板窗口（…· AI 批注）永远排除。"""
    stem = os.path.splitext(os.path.basename(pdf_path))[0]
    target = norm_text(stem)
    exact, best, best_ratio = 0, 0, 0.0
    for hwnd, title in _titles():
        if "msedge" not in _exe_of(_pid_of(hwnd)).lower():
            continue
        t = title.strip()
        if t.endswith("AI 批注"):
            continue
        if is_minimized(hwnd):
            continue
        nt = norm_text(t)
        if target and (target in nt or nt.startswith(target)):
            return hwnd
        ratio = difflib.SequenceMatcher(None, target, nt).ratio()
        if ratio > best_ratio:
            best_ratio, best = ratio, hwnd
    if best and best_ratio >= 0.78:
        return best
    return best or 0


def find_panel_of(pdf_path: str) -> int:
    """面板标题是「书名 · AI 批注」，用书名去认。"""
    stem = os.path.splitext(os.path.basename(pdf_path))[0]
    target = norm_text(stem)
    for hwnd, title in _titles():
        t = title.strip()
        if not t.endswith("AI 批注"):
            continue
        if "msedge" not in _exe_of(_pid_of(hwnd)).lower():
            continue
        if not target or target[:12] in norm_text(t):
            return hwnd
    return 0


def show_window(hwnd: int) -> bool:
    """还原 + 置前 + 抢焦点。"""
    if not hwnd:
        return False
    try:
        SW_SHOW, SW_RESTORE = 5, 9
        u = user32
        if u.IsIconic(wt.HWND(hwnd)):
            u.ShowWindow(wt.HWND(hwnd), SW_RESTORE)
        else:
            u.ShowWindow(wt.HWND(hwnd), SW_SHOW)
        # 先临时置顶再取消：Windows 不允许后台进程抢焦点，但这样能把它翻到最前面
        u.SetWindowPos(wt.HWND(hwnd), wt.HWND(-1), 0, 0, 0, 0, 0x0001 | 0x0002)
        time.sleep(0.25)
        u.SetWindowPos(wt.HWND(hwnd), wt.HWND(-2), 0, 0, 0, 0, 0x0001 | 0x0002)
        u.SetForegroundWindow(wt.HWND(hwnd))
        return True
    except Exception:
        return False


def client_origin(hwnd: int):
    """窗口客户区左上角在屏幕上的坐标。"""
    if not hwnd:
        return None
    pt = wt.POINT(0, 0)
    user32.ClientToScreen(wt.HWND(hwnd), ctypes.byref(pt))
    return (pt.x, pt.y)


def find_reader_window() -> int:
    for hwnd, title in _titles():
        t = title.strip()
        if t.endswith("· AI 批注") and "msedge" in _exe_of(_pid_of(hwnd)).lower():
            return hwnd
    return 0


def grab_screen_region(x: int, y: int, w: int, h: int):
    from PIL import ImageGrab
    return ImageGrab.grab(bbox=(int(x), int(y), int(x + w), int(y + h)), all_screens=True)
