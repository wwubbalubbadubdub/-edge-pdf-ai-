# -*- coding: utf-8 -*-
"""通过 DevTools 协议直接抓 Edge 里 PDF 视口的画面（含未保存的墨迹）。"""
from __future__ import annotations

import base64
import json
import time
import urllib.parse
import urllib.request

try:
    import websocket
except Exception:  # pragma: no cover
    websocket = None

_cache = {"ts": 0.0, "url": None}
LAST_PAGE_RECT = None

PAGE_JS = """(() => {
  const t = document.querySelector('#toolbar');
  const tb = t ? Math.round(t.getBoundingClientRect().bottom) : 0;
  const sel = document.querySelector('#pageselector');
  return JSON.stringify({toolbarBottom: tb, page: sel ? parseInt(sel.value, 10) : null,
                         vw: innerWidth, vh: innerHeight});
})()"""


class Session:
    def __init__(self, url: str, timeout: float = 10.0):
        self.ws = websocket.create_connection(url, timeout=timeout)
        self.mid = 0

    def call(self, method: str, params: dict | None = None) -> dict:
        self.mid += 1
        self.ws.send(json.dumps({"id": self.mid, "method": method, "params": params or {}}))
        while True:
            msg = json.loads(self.ws.recv())
            if msg.get("id") == self.mid:
                return msg.get("result") or {}

    def close(self):
        try:
            self.ws.close()
        except Exception:
            pass



def _post(png: bytes, top: int, vw: float, vh: float, max_side: int = 1400,
          quality: int = 85, box=None) -> bytes:
    """裁掉工具栏和四周灰底，再压成 JPEG。"""
    import io

    from PIL import Image

    im = Image.open(io.BytesIO(png)).convert("RGB")
    w, h = im.size
    if box:
        left, bt, bw, bh = box
        im = im.crop((max(0, int(left)), max(0, int(bt)),
                      min(w, int(left + bw)), min(h, int(bt + bh))))
        w, h = im.size
    elif top > 0:
        im = im.crop((0, min(top, h - 8), w, h))
        h = im.size[1]
    # 去掉四周的灰底（截图里页面两侧/上下是 #f7f7f7 之类）
    try:
        import numpy as np
        arr = np.asarray(im.convert("L"))
        cols = arr.max(axis=0)
        rows = arr.max(axis=1)
        vivid_c = np.where(arr.min(axis=0) < 200)[0]
        vivid_r = np.where(arr.min(axis=1) < 200)[0]
        if len(vivid_c) > 10 and len(vivid_r) > 10:
            im = im.crop((int(vivid_c[0]), int(vivid_r[0]),
                          int(vivid_c[-1]) + 1, int(vivid_r[-1]) + 1))
    except Exception:
        pass
    w, h = im.size
    long_side = max(w, h)
    if long_side > max_side:
        k = max_side / float(long_side)
        im = im.resize((max(16, int(w * k)), max(16, int(h * k))), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, format="JPEG", quality=quality, optimize=True)
    return buf.getvalue()


def _pick(targets, name):
    views = [t for t in targets if t.get("type") == "webview" and "mhjfb" in (t.get("url") or "")]
    if name:
        # 1) 标题里带文件名（独立打开的 PDF）
        for t in views:
            if name.lower() in (t.get("title") or "").lower():
                return t
        # 2) 内嵌在我们的 reader 页里：顺着 target 父子关系找
        children = {}
        for t in targets:
            children.setdefault(t.get("parentId"), []).append(t)
        for page in targets:
            if page.get("type") == "page" and "reader.html" in (page.get("url") or ""):
                for lvl1 in children.get(page.get("id"), []):
                    if lvl1.get("type") == "webview" and "mhjfb" in (lvl1.get("url") or ""):
                        return lvl1
                    for lvl2 in children.get(lvl1.get("id"), []):
                        if lvl2.get("type") == "webview" and "mhjfb" in (lvl2.get("url") or ""):
                            return lvl2
        pages = [t for t in targets if t.get("type") == "page"
                 and name.lower() in urllib.parse.unquote(t.get("url") or "").lower()]
        ids = {p["id"] for p in pages}
        hit = [t for t in targets if t.get("type") == "webview"
               and "mhjfb" in (t.get("url") or "") and t.get("parentId") in ids]
        if hit:
            return hit[0]
    hit = [t for t in targets if t.get("type") == "webview" and "mhjfb" in (t.get("url") or "")]
    return hit[0] if hit else None


def _target_url(port: int, name: str = None, refresh: bool = False):
    key = name or ""
    if not refresh and _cache.get("key") == key and _cache["url"] and time.time() - _cache["ts"] < 5:
        return _cache["url"]
    try:
        with urllib.request.urlopen("http://127.0.0.1:%d/json/list" % port, timeout=3) as r:
            targets = json.load(r)
    except Exception:
        return None
    t = _pick(targets, name)
    url = t["webSocketDebuggerUrl"] if t else None
    _cache.update({"ts": time.time(), "url": url, "key": key})
    return url


def available(port: int = 9222) -> bool:
    if websocket is None:
        return False
    return _target_url(port, refresh=True) is not None


def grab(port: int = 9222, max_side: int = 1400, quality: int = 85, name: str = None) -> dict | None:
    """返回 {"png": bytes, "page": int|None, "clip": [x,y,w,h]}，失败返回 None。"""
    if websocket is None:
        return None
    url = _target_url(port, name)
    if not url:
        return None
    s = None
    try:
        s = Session(url)
        raw = s.call("Runtime.evaluate", {"expression": PAGE_JS, "returnByValue": True})
        val = (raw.get("result") or {}).get("value")
        info = json.loads(val) if val else {}
        shot = s.call("Page.captureScreenshot", {"format": "png", "captureBeyondViewport": False})
        data = base64.b64decode(shot.get("data") or "")
        if not data:
            return None
        img = _post(data, int(info.get("toolbarBottom") or 0),
                    float(info.get("vw") or 0), float(info.get("vh") or 0),
                    max_side=max_side, quality=quality)
        if img is None:
            return None
        return {"png": img, "page": info.get("page"), "mime": "image/jpeg"}
    except Exception:
        _cache["url"] = None
        return None
    finally:
        if s:
            s.close()


def current_page(port: int = 9222):
    if websocket is None:
        return None
    url = _target_url(port)
    if not url:
        return None
    s = None
    try:
        s = Session(url)
        raw = s.call("Runtime.evaluate", {"expression": PAGE_JS, "returnByValue": True})
        val = (raw.get("result") or {}).get("value")
        return (json.loads(val) or {}).get("page") if val else None
    except Exception:
        return None
    finally:
        if s:
            s.close()

READER_RECT_JS = """(() => {
  const f = document.getElementById('pdf');
  if (!f) return 'null';
  const r = f.getBoundingClientRect();
  return JSON.stringify({x: r.left, y: r.top, w: r.width, h: r.height,
                         dpr: window.devicePixelRatio || 1});
})()"""


def grab_reader(port: int = 9222, max_side: int = 1400, quality: int = 85) -> dict | None:
    """单页阅读器：从页面拿到书页矩形 → 窗口置前 → 屏幕截取 → 裁切压缩。

    PDF 是独立进程（OOPIF），CDP 截图和 PrintWindow 都拿不到它，只能屏幕截取。
    """
    if websocket is None:
        return None
    try:
        with urllib.request.urlopen("http://127.0.0.1:%d/json/list" % port, timeout=3) as r:
            targets = json.load(r)
    except Exception:
        return None

    page = None
    for t in targets:
        if t.get("type") == "page" and "reader.html" in (t.get("url") or ""):
            page = t
            break
    if not page:
        return None

    info = None
    s = None
    try:
        s = Session(page["webSocketDebuggerUrl"], timeout=10)
        raw = s.call("Runtime.evaluate", {"expression": PROBE_RECT_JS, "returnByValue": True})
        val = (raw.get("result") or {}).get("value")
        if val and val != "null":
            info = json.loads(val)
    except Exception:
        return None
    finally:
        if s:
            s.close()
    if not info:
        return None

    import win as winmod

    hwnd = winmod.find_reader_window()
    if not hwnd:
        return None
    origin = winmod.client_origin(hwnd)
    if not origin:
        return None

    dpr = float(info.get("dpr") or 1)
    x = origin[0] + info["x"] * dpr
    y = origin[1] + info["y"] * dpr
    w = info["w"] * dpr
    h = info["h"] * dpr
    if w < 50 or h < 50:
        return None

    was_top = winmod.is_topmost(hwnd)
    if not was_top:
        winmod.set_topmost(hwnd, True)
        time.sleep(0.18)
    try:
        im = winmod.grab_screen_region(x, y, w, h)
    except Exception:
        return None
    finally:
        if not was_top:
            winmod.set_topmost(hwnd, False)

    try:
        import io

        import numpy as np
        from PIL import Image
        if im.mode != "RGB":
            im = im.convert("RGB")
        # 自动裁到书页：页面是纯白，阅读器背景是浅灰
        try:
            arr = np.asarray(im)
            mask = (arr[:, :, 0] > 250) & (arr[:, :, 1] > 250) & (arr[:, :, 2] > 250)
            rows = np.where(mask.sum(axis=1) > im.size[0] * 0.35)[0]
            cols = np.where(mask.sum(axis=0) > im.size[1] * 0.35)[0]
            if len(rows) > 50 and len(cols) > 50:
                pad = 3
                box = (max(0, int(cols[0]) - pad), max(0, int(rows[0]) - pad),
                       min(im.size[0], int(cols[-1]) + pad), min(im.size[1], int(rows[-1]) + pad))
                if (box[2] - box[0]) > 60 and (box[3] - box[1]) > 60:
                    global LAST_PAGE_RECT
                    LAST_PAGE_RECT = {
                        "x": info["x"] + box[0] / dpr,
                        "y": info["y"] + box[1] / dpr,
                        "w": (box[2] - box[0]) / dpr,
                        "h": (box[3] - box[1]) / dpr,
                    }
                    im = im.crop(box)
        except Exception:
            pass
        lw, lh = im.size
        long_side = max(lw, lh)
        if long_side > max_side:
            k = max_side / float(long_side)
            im = im.resize((max(16, int(lw * k)), max(16, int(lh * k))), Image.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=quality, optimize=True)
        data = buf.getvalue()
    except Exception:
        return None
    if not data:
        return None
    return {"png": data, "page": current_page(port), "mime": "image/jpeg"}


PROBE_RECT_JS = """(() => {
  if (typeof window.__aiPageRect === 'function') {
    const r = window.__aiPageRect();
    return JSON.stringify({x: r.x, y: r.y, w: r.w, h: r.h, dpr: r.dpr});
  }
  const f = document.getElementById('pdf');
  if (!f) return 'null';
  const b = f.getBoundingClientRect();
  return JSON.stringify({x: b.left, y: b.top, w: b.width, h: b.height,
                         dpr: window.devicePixelRatio || 1});
})()"""
