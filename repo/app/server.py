# -*- coding: utf-8 -*-
"""本地后端。python server.py [--port 8760]"""
from __future__ import annotations

import concurrent.futures
import json
import threading
import mimetypes
import os
import sys
import traceback
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import book as bookmod
import cdp
import config as cfgmod
import ingest
import llm
import prompt as promptmod
import render
import store as storemod
import usage
import win

PANEL = HERE / "panel"

REVIEW_PROMPT = """这是你刚才给出的初稿。请对照【这一页的内容】和【阅读约定卡】复核一遍，然后**只输出最终答案**：

- 只写学生要看的最终回答，禁止出现「通过」「修正」「核查」「初稿」这类字样，也不要解释你改了什么。
- 初稿没问题就原样给出（可以更精炼）；有错就直接给改正后的版本。
- 不超过 150 字，公式用 LaTeX，符号与约定卡一致。"""

JOBS = {}
CURRENT = {"book": ""}
_THROTTLE = {"until": 0.0, "wait": 3.0}
JOBS_LOCK = __import__("threading").Lock()
START = __import__("time").time()


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "Annotator/0.1"

    def log_message(self, fmt, *args):
        pass

    # ---------- 基础 ----------
    def _send(self, code, body: bytes, ctype="application/json; charset=utf-8"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"))

    def _sse_open(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()

    def _sse(self, obj):
        self.wfile.write(b"data: " + json.dumps(obj, ensure_ascii=False).encode("utf-8") + b"\n\n")
        self.wfile.flush()

    def _body(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        if not n:
            return {}
        try:
            return json.loads(self.rfile.read(n).decode("utf-8"))
        except Exception:
            return {}

    def _query(self) -> dict:
        q = urllib.parse.urlparse(self.path).query
        return {k: v[0] for k, v in urllib.parse.parse_qs(q).items()}

    # ---------- 静态 ----------
    def _static(self, rel: str):
        p = (PANEL / rel).resolve()
        if not str(p).startswith(str(PANEL.resolve())) or not p.exists() or p.is_dir():
            self._json({"error": "not found"}, 404)
            return
        ctype = mimetypes.guess_type(str(p))[0] or "application/octet-stream"
        self._send(200, p.read_bytes(), ctype)

    # ---------- 路由 ----------
    def do_GET(self):
        try:
            path = urllib.parse.urlparse(self.path).path
            if path in ("/", "/index.html"):
                self._static("index.html")
            elif path.startswith("/static/"):
                self._static(path[len("/static/"):])
            elif path == "/api/health":
                self._json({"ok": True, "uptime": round(__import__("time").time() - START, 1)})
            elif path == "/api/brief":
                self._json({"text": storemod.Store(self._query().get("book", "")).brief()})
            elif path == "/api/ingest/plan":
                q = self._query()
                cid = q.get("book", "")
                st = storemod.Store(cid)
                meta = st.meta()
                total_pages = int(meta.get("pages") or 0)
                a = max(1, int(q.get("from") or 1))
                b = min(total_pages or (a), int(q.get("to") or total_pages or a))
                missing = [i for i in range(a - 1, b) if not ingest.read_page_md(st, i).strip()]
                self._json({"from": a, "to": b, "total": max(0, b - a + 1),
                            "missing": len(missing), "done": max(0, b - a + 1) - len(missing)})
            elif path == "/api/ingest/status":
                self._ingest_status(self._query().get("book", ""))
            elif path == "/api/pdfmeta":
                cid = self._query().get("book", "")
                st = storemod.Store(cid)
                p = st.meta().get("path", "")
                try:
                    bk = bookmod.Book(p)
                    r = bk.doc[0].rect
                    info = {"pw": round(r.width, 2), "ph": round(r.height, 2),
                            "pages": bk.pages, "title": bk.title(),
                            "page_rect": cdp.LAST_PAGE_RECT}
                    bk.close()
                except Exception as e:
                    info = {"error": str(e)[:200]}
                self._json(info)
            elif path == "/api/current":
                self._json(CURRENT)
            elif path == "/api/book":
                self._json(self._book_info(self._query().get("id", "")))
            elif path == "/api/config":
                self._json(cfgmod.public())
            else:
                self._json({"error": "not found"}, 404)
        except Exception:
            self._json({"error": traceback.format_exc()[-800:]}, 500)

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        try:
            if path == "/api/ask":
                self._ask(self._body())
            elif path == "/api/current":
                body = self._body()
                if body.get("book"):
                    CURRENT["book"] = body["book"]
                self._json(CURRENT)
            elif path == "/api/brief":
                self._json(self._brief(self._body()))
            elif path == "/api/ingest":
                self._ingest(self._body())
            elif path == "/api/config":
                body = self._body()
                keep = bool(body.pop("save_key", True))
                cfgmod.save(body, persist_key=keep)
                self._json(cfgmod.public())
            elif path == "/api/peek":
                self._json(self._peek(self._body()))
            elif path == "/api/pin":
                self._json(self._pin(self._body()))
            elif path == "/api/sync":
                self._json(self._sync(self._body()))
            elif path == "/api/goto":
                self._json(self._goto(self._body()))
            else:
                self._json({"error": "not found"}, 404)
        except BrokenPipeError:
            pass
        except Exception:
            try:
                self._json({"error": traceback.format_exc()[-800:]}, 500)
            except Exception:
                pass

    # ---------- 业务 ----------
    def _book_info(self, cid: str) -> dict:
        if not cid:
            return {"error": "missing id"}
        st = storemod.Store(cid)
        meta = st.meta()
        total = int(meta.get("pages") or 0)
        done = ingest.count_done(st, total) if total else 0
        return {
            "id": cid,
            "title": meta.get("title", cid),
            "path": meta.get("path", ""),
            "pages": total,
            "toc": st.toc(),
            "ingest": {"done": done, "total": total},
            "cost": usage.totals(cid),
            "thinking": bool(cfgmod.load().get("thinking")),
            "has_brief": bool(st.brief().strip()),
            "memory": st.memory()[-1500:],
            "chat": st.chat(limit=40),
        }

    def _pdf_to_images(self, data):
        pass

    def _ask(self, data: dict):
        cfg = cfgmod.load()
        cid = data.get("book", "")
        question = (data.get("question") or "").strip()
        page = int(data.get("page") or 1) - 1
        if not cid or not question:
            self._json({"error": "需要 book 和 question"}, 400)
            return
        st = storemod.Store(cid)
        path = st.meta().get("path", "")
        if not path or not os.path.exists(path):
            self._json({"error": "找不到原文件，位置可能变了。把它再拖一次到桌面快捷方式上即可恢复。"}, 400)
            return

        bk = bookmod.Book(path)
        marks = bk.marks(page)
        st.add_inks([{k: m[k] for k in ("page", "kind", "xref", "rect")} for m in marks])

        crops, kinds = [], []
        shot = None
        if cfg.get("capture", "cdp") == "cdp":
            port_cdp = int(cfg.get("cdp_port", 9222))
            side = int(cfg.get("max_side", 1400))
            q = int(cfg.get("jpeg_quality", 85))
            shot = cdp.grab_reader(port_cdp, max_side=side, quality=q)
            if not shot:
                shot = cdp.grab(port_cdp, max_side=side, quality=q,
                                name=os.path.basename(path))
        img_mime = "image/jpeg"
        if shot:
            crops = [shot["png"]]
            kinds = ["screen"]
            if shot.get("page"):
                page = max(0, int(shot["page"]) - 1)
        else:
            img_mime = "image/png"
            for m in marks[-2:]:
                r = m.get("rect") or [0, 0, 0, 0]
                pad = 14
                rect = (r[0] - pad, r[1] - pad, r[2] + pad, r[3] + pad)
                try:
                    crops.append(bk.region_png(page, rect, dpi=200))
                    kinds.append(m.get("kind", ""))
                except Exception:
                    pass

        messages = [{"role": "system", "content": promptmod.system_message(st, bk.title())}]
        page_text = promptmod.page_block(st, [page - 1, page, page + 1])
        if page_text:
            messages.append({"role": "user", "content": page_text})
        for turn in st.chat(limit=8):
            messages.append({"role": turn["role"], "content": turn["content"]})

        head = promptmod.mark_hint([{"page": page, **m} for m in marks[-2:]])
        content = [llm.text_part((head + "\n\n" if head else "") + question)]
        for c in crops:
            content.append(llm.image_part(c, img_mime))
        messages.append({"role": "user", "content": content})

        self._sse_open()
        if not str(cfg.get("api_key") or "").strip() and not str(cfg.get("base_url", "")).startswith("mock"):
            self._sse({"type": "delta", "text": "还没填 API key。点右上角 ⚙，把 key 填进去再问一次。"})
            self._sse({"type": "done", "chars": 0, "crops": 0, "page": page + 1, "capture": "none"})
            return
        acc = []
        for kind, val in llm.stream(cfg, messages, model=cfg.get("vision_model") or cfg.get("model")):
            if kind == "reasoning":
                self._sse({"type": "reasoning", "text": val})
            elif kind == "text":
                acc.append(val)
                self._sse({"type": "delta", "text": val})
            elif kind == "usage":
                usage.record(cid, "ask", val, model=cfg.get("vision_model", ""))
                self._sse({"type": "usage", "usage": val})
            elif kind == "error":
                self._sse({"type": "error", "message": str(val)})
        text = "".join(acc)
        if not text.strip():
            text = "（这次没有生成内容，换个问法或再问一次）"
            self._sse({"type": "delta", "text": text})

        # 第三段：关掉思考，对着初稿做一次核查（结合约定卡与自定义提示词）
        review = ""
        if cfg.get("review", True) and text.strip():
            try:
                r_msgs = list(messages)
                r_msgs.append({"role": "assistant", "content": text})
                r_msgs.append({"role": "user", "content": REVIEW_PROMPT})
                r_cfg = dict(cfg)
                r_cfg["thinking"] = False
                self._sse({"type": "review_start"})
                buf = []
                for kind, val in llm.stream(r_cfg, r_msgs, model=cfg.get("model"),
                                            temperature=0.1):
                    if kind == "text":
                        buf.append(val)
                        self._sse({"type": "review", "text": val})
                    elif kind == "usage":
                        usage.record(cid, "review", val, model=cfg.get("model", ""))
                    elif kind == "error":
                        self._sse({"type": "review", "text": "\n（核查失败：" + str(val)[:120] + "）"})
                review = "".join(buf)
            except Exception as e:
                self._sse({"type": "review", "text": "（核查出错：%s）" % str(e)[:120]})

        st.add_chat("user", question)
        st.add_chat("assistant", text, review=review, capture=("screen" if shot else "annot"))
        self._sse({"type": "done", "chars": len(text), "crops": len(crops),
                   "page": page + 1, "capture": "screen" if shot else "annot",
                   "review_chars": len(review)})

    def _peek(self, data: dict) -> dict:
        cfg = cfgmod.load()
        port_cdp = int(cfg.get("cdp_port", 9222))
        side = int(cfg.get("max_side", 1400))
        q = int(cfg.get("jpeg_quality", 85))
        shot = cdp.grab_reader(port_cdp, max_side=side, quality=q)
        if not shot:
            cid = data.get("book", "")
            nm = os.path.basename(storemod.Store(cid).meta().get("path", "")) if cid else None
            shot = cdp.grab(port_cdp, max_side=side, quality=q, name=nm)
        if not shot:
            return {"ok": False, "hint": "抓不到画面：请从桌面快捷方式打开书，别用普通 Edge 窗口"}
        return {"ok": True, "page": shot.get("page"), "bytes": len(shot["png"])}

    def _brief(self, data: dict) -> dict:
        cid = data.get("book", "")
        if not cid:
            return {"ok": False, "error": "missing book"}
        st = storemod.Store(cid)
        text = data.get("text")
        if text is not None:
            st.save_brief(text)
            return {"ok": True, "saved": True, "chars": len(text)}
        if data.get("regenerate"):
            path = st.meta().get("path", "")
            if not path or not os.path.exists(path):
                return {"ok": False, "error": "找不到原文件"}
            bk = bookmod.Book(path)
            try:
                new = ingest.build_brief(st, bk, cfgmod.load())
            finally:
                bk.close()
            return {"ok": bool(new), "text": new, "chars": len(new or "")}
        return {"ok": False, "error": "nothing to do"}

    def _ingest(self, data: dict):
        cid = data.get("book", "")
        st = storemod.Store(cid)
        path = st.meta().get("path", "")
        if not path or not os.path.exists(path):
            self._json({"error": "找不到原文件"}, 400)
            return
        with JOBS_LOCK:
            job = JOBS.get(cid)
            if job and job.get("running"):
                self._json({"started": False, "running": True, **job})
                return
            cfg = cfgmod.load()
            bk = bookmod.Book(path)
            total = bk.pages
            a = max(1, int(data.get("from") or 1)) - 1
            b = min(total, int(data.get("to") or total)) - 1
            JOBS[cid] = {"running": True, "done": 0, "skipped": 0, "failed": 0, "phase": "queued", "brief": False,
                         "total": b - a + 1, "from": a + 1, "to": b + 1,
                         "current": a + 1, "started": __import__("time").time(),
                         "finished": None, "error": ""}
        __import__("threading").Thread(target=self._ingest_worker,
                                       args=(cid, path, a, b, cfg), daemon=True).start()
        self._json({"started": True, "total": b - a + 1, "from": a + 1, "to": b + 1})

    def _ingest_worker(self, cid, path, a, b, cfg):
        st = storemod.Store(cid)
        local = threading.local()
        n = max(1, int(cfg.get("ingest_concurrency", 3)))

        def get_book():
            bk = getattr(local, "bk", None)
            if bk is None:
                bk = bookmod.Book(path)
                local.bk = bk
            return bk

        def one(idx):
            with JOBS_LOCK:
                JOBS[cid]["current"] = idx + 1
            tm = __import__("time")
            while tm.time() < _THROTTLE["until"]:
                tm.sleep(0.4)
            res = {"done": 0, "skipped": 0, "failed": 1}
            last = None
            for attempt in range(3):
                try:
                    res = ingest.ingest_pages(get_book(), st, [idx], cfg=cfg)
                    last = None
                    if res.get("failed") and attempt < 2:
                        __import__("time").sleep(1.2 * (attempt + 1))
                        continue
                    break
                except Exception as e:
                    last = e
                    if attempt < 2:
                        __import__("time").sleep(1.2 * (attempt + 1))
                        continue
                    res = {"done": 0, "skipped": 0, "failed": 1}
            errs = " ".join(res.get("errors") or [])
            if "429" in errs or "Too Many Requests" in errs:
                _THROTTLE["wait"] = min(30.0, _THROTTLE["wait"] * 1.8)
                _THROTTLE["until"] = __import__("time").time() + _THROTTLE["wait"]
                with JOBS_LOCK:
                    JOBS[cid]["throttled"] = JOBS[cid].get("throttled", 0) + 1
            elif res.get("done"):
                _THROTTLE["wait"] = max(2.0, _THROTTLE["wait"] * 0.9)
            if res.get("failed"):
                try:
                    (st.dir / "pages" / ("%04d.err" % (idx + 1))).write_text(
                        str(last or "转写失败（重试 3 次）"), encoding="utf-8")
                except Exception:
                    pass
            with JOBS_LOCK:
                job = JOBS[cid]
                if res.get("done"):
                    job["done"] += 1
                elif res.get("skipped"):
                    job["skipped"] += 1
                else:
                    job["failed"] += 1

        try:
            with JOBS_LOCK:
                JOBS[cid]["phase"] = "pages"
            with concurrent.futures.ThreadPoolExecutor(max_workers=n) as ex:
                list(ex.map(one, range(a, b + 1)))
            with JOBS_LOCK:
                JOBS[cid]["phase"] = "brief"
            try:
                ingest.build_brief(st, bookmod.Book(path), cfg)
                with JOBS_LOCK:
                    JOBS[cid]["brief"] = True
            except Exception as e:
                with JOBS_LOCK:
                    JOBS[cid]["brief_error"] = str(e)[:200]
        except Exception as e:
            with JOBS_LOCK:
                JOBS[cid]["error"] = str(e)[:300]
        finally:
            with JOBS_LOCK:
                JOBS[cid]["running"] = False
                JOBS[cid]["phase"] = "done"
                JOBS[cid]["finished"] = __import__("time").time()
            for b_ in list(getattr(local, "__dict__", {}).values()):
                try:
                    if hasattr(b_, "close"):
                        b_.close()
                except Exception:
                    pass

    def _ingest_status(self, cid: str):
        with JOBS_LOCK:
            job = dict(JOBS.get(cid) or {})
        st = storemod.Store(cid)
        meta = st.meta()
        total = int(meta.get("pages") or 0)
        job["ingested"] = ingest.count_done(st, total) if total else 0
        self._json(job)

    def _pin(self, data: dict) -> dict:
        hwnd = win.find_panel()
        if not hwnd:
            return {"found": False, "topmost": False}
        cur = win.is_topmost(hwnd)
        want = (not cur) if data.get("toggle") else bool(data.get("on"))
        win.set_topmost(hwnd, want)
        return {"found": True, "topmost": bool(want)}

    def _sync(self, data: dict) -> dict:
        cid = data.get("book", "")
        st = storemod.Store(cid)
        name = os.path.basename(st.meta().get("path", ""))
        hwnd = win.find_window([name[:30], "Microsoft Edge"]) if name else win.find_window("Microsoft Edge")
        ok = win.send_ctrl_s(hwnd) if hwnd else False
        import time
        time.sleep(0.6)
        bk = bookmod.Book(st.meta().get("path", ""))
        total = 0
        for i in range(bk.pages):
            ms = bk.marks(i)
            total += st.add_inks([{k: m[k] for k in ("page", "kind", "xref", "rect")} for m in ms])
        return {"saved": ok, "new_marks": total}

    def _goto(self, data: dict) -> dict:
        import subprocess
        cfg = cfgmod.load()
        cid = data.get("book", "")
        page = int(data.get("page") or 1)
        path = storemod.Store(cid).meta().get("path", "")
        if not path:
            return {"ok": False}
        uri = Path(path).as_uri() + "#page=%d" % page
        subprocess.Popen([cfg["edge"], uri])
        return {"ok": True}


def main():
    port = 8760
    args = sys.argv[1:]
    if "--port" in args:
        port = int(args[args.index("--port") + 1])
    else:
        port = int(cfgmod.load().get("port", 8760))
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print("panel: http://127.0.0.1:%d" % port, flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()