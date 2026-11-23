# -*- coding: utf-8 -*-
"""侧栏守护：让 AI 面板始终贴在 Edge 书页的右侧，跟着它移动/缩放。

用法：pythonw sidebar.py "<pdf 路径>"
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import win

GAP = 0
LOG = HERE.parent / ".sidebar.log"


def log(msg: str) -> None:
    try:
        with LOG.open("a", encoding="utf-8") as f:
            f.write("%s %s\n" % (time.strftime("%H:%M:%S"), msg))
    except Exception:
        pass


def main() -> None:
    pdf = sys.argv[1] if len(sys.argv) > 1 else ""
    title = sys.argv[2] if len(sys.argv) > 2 else ""
    if not pdf:
        return
    import config as cfgmod
    cfg = cfgmod.load()
    sw, sh = win.screen_size()
    ratio = float(cfg.get("sidebar_ratio", 0.30) or 0.30)
    width = max(int(cfg.get("sidebar_min", 460) or 460), int(sw * ratio))
    log("start pdf=..%s title=%s" % (pdf[-20:], title))
    last = None
    while True:
        try:
            b = win.find_by_pdf(pdf)
            p = win.find_panel(title) if title else win.find_panel_of(pdf)
            if not b or not p:
                time.sleep(1.0)
                continue
            br = win.get_rect(b)
            if not br:
                time.sleep(1.0)
                continue
            left, top, right, bottom = br
            h = bottom - top
            if h < 200:
                time.sleep(1.0)
                continue
            # 书页固定贴左，右侧留给面板，保证面板右缘顶到屏幕边
            bw = sw - width
            if abs((right - left) - bw) > 4 or abs(left) > 4:
                win.layout(b, 0, top, bw, h)
                right = bw
            target = (sw - width, top, width, h)
            cur = win.get_rect(p)
            if cur is None or abs(cur[0] - target[0]) > 2 or abs(cur[1] - target[1]) > 2 \
                    or abs((cur[2] - cur[0]) - width) > 4 or abs((cur[3] - cur[1]) - h) > 4:
                win.layout(p, target[0], target[1], target[2], target[3])
            win.set_topmost(p, True)
            last = target
        except Exception as e:
            log("ERR %r" % (e,))
        time.sleep(0.35)


if __name__ == "__main__":
    main()
