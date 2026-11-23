# -*- coding: utf-8 -*-
"""把 PDF 拖到这个脚本（或它的快捷方式）上：开 Edge 看书 + 右侧开 AI 面板。"""
from __future__ import annotations

import ctypes
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import book as bookmod
import config as cfgmod
import store as storemod
import win

DETACHED = 0x00000008 | 0x00000200
LOG_PATH = HERE.parent / ".launcher.log"


def log(msg: str) -> None:
    try:
        with LOG_PATH.open("a", encoding="utf-8") as f:
            f.write("%s %s\n" % (__import__("time").strftime("%H:%M:%S"), msg))
    except Exception:
        pass


def alert(msg: str) -> None:
    try:
        ctypes.windll.user32.MessageBoxW(0, msg, "AI 批注", 0x40)
    except Exception:
        print(msg)


def health(port: int) -> bool:
    try:
        with urllib.request.urlopen("http://127.0.0.1:%d/api/health" % port, timeout=1.2) as r:
            return bool(json.loads(r.read().decode()).get("ok"))
    except Exception:
        return False


def ensure_server(port: int) -> bool:
    if health(port):
        return True
    exe = Path(sys.executable)
    pyw = exe.with_name("pythonw.exe")
    exe = str(pyw if pyw.exists() else exe)
    subprocess.Popen([exe, str(HERE / "server.py"), "--port", str(port)],
                     creationflags=DETACHED, close_fds=True,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(48):
        if health(port):
            return True
        time.sleep(0.25)
    return False


def prepare(pdf: str) -> dict:
    bk = bookmod.Book(pdf)
    fp = bookmod.fingerprint(pdf)
    cid = storemod.resolve_id(pdf, fp)
    st = storemod.Store(cid)
    fresh = not st.exists()
    if fresh:
        st.save_meta(path=bk.path, title=bk.title(), pages=bk.pages,
                     created=time.time(), scanned=bk.is_scanned(), fingerprint=fp)
        st.save_toc(bk.toc())
        st.save_text(bk.all_text())
        st.save_memory("")
    else:
        st.save_meta(path=bk.path, pages=bk.pages, fingerprint=fp)
    info = {
        "id": cid, "title": bk.title(), "pages": bk.pages,
        "toc": len(st.toc()), "fresh": fresh, "scanned": bk.is_scanned(),
    }
    bk.close()
    return info


def main() -> None:
    if len(sys.argv) < 2:
        alert("用法：把一个 PDF 文件拖到这个快捷方式上。")
        return
    pdf = sys.argv[1]
    if not os.path.exists(pdf):
        alert("找不到文件：%s" % pdf)
        return
    log("=== start pdf=%r" % (pdf,))
    cfg = cfgmod.load()
    port = int(cfg.get("port", 8760))
    info = prepare(pdf)
    log("prepare ok id=%s title=%r pages=%s" % (info["id"], info["title"], info["pages"]))
    alive = ensure_server(port)
    log("server alive=%s" % alive)
    if not alive:
        alert("后端没能启动（端口 %d）。检查一下 Python 环境。" % port)
        return

    edge = cfg.get("edge")
    sw, sh = win.screen_size()
    top_h = sh - 70
    cap = str(cfg.get("capture", "cdp"))
    port_cdp = int(cfg.get("cdp_port", 9222))
    ui_mode = str(cfg.get("ui_mode", "reader"))
    if ui_mode not in ("reader", "window"):
        ui_mode = "reader"

    if ui_mode == "reader":
        import base64
        import urllib.parse

        b64 = base64.urlsafe_b64encode(Path(pdf).as_uri().encode()).decode()
        reader = (HERE / "panel" / "reader.html").as_uri()
        url = reader + "?book=" + info["id"] + "&pdfb64=" + b64
        flags = ["--app=" + url,
                 "--window-position=0,0",
                 "--window-size=%d,%d" % (sw - 40, top_h)]
        if cap == "cdp":
            flags = ["--user-data-dir=" + str(HERE.parent / ".edge-profile"),
                     "--remote-debugging-port=%d" % port_cdp,
                     "--no-first-run", "--no-default-browser-check"] + flags
        log("reader mode: opening %s" % url[:90])
        subprocess.Popen([edge] + flags)

        # 等窗口出来并置前，否则会被用户自己的浏览器盖住
        hwnd = 0
        for _ in range(60):
            time.sleep(0.25)
            hwnd = win.find_panel("")
            if hwnd and not win.is_minimized(hwnd):
                break
        if hwnd:
            win.show_window(hwnd)
            log("reader window hwnd=%s activated" % hwnd)
        return

    uri = Path(pdf).as_uri()
    side_w = max(600, min(860, int(sw * 0.40)))
    left_w = sw - side_w


def _safe_main() -> None:
    try:
        main()
    except Exception:
        import traceback
        try:
            with LOG_PATH.open("a", encoding="utf-8") as f:
                f.write(traceback.format_exc() + "\n")
        except Exception:
            pass
        alert("启动失败，详情见 F:\\看书\\.launcher.log\n\n" + traceback.format_exc()[-400:])


if __name__ == "__main__":
    _safe_main()
