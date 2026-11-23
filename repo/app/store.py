# -*- coding: utf-8 -*-
"""记忆容器：每本 PDF 一个目录，存目录树、正文缓存、记忆、圈画、对话。"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

ROOT = Path(os.environ.get("ANNOTATOR_HOME")
            or Path(__file__).resolve().parent.parent)  # 程序所在目录
LIB = ROOT / "library"


def now() -> float:
    return time.time()


def jdump(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        if path.exists():
            bak = path.with_suffix(path.suffix + ".bak")
            bak.write_bytes(path.read_bytes())
    except Exception:
        pass
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        f.write(json.dumps(data, ensure_ascii=False, indent=2))
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def jload(path: Path, default=None):
    """读坏了就退回上一次的备份，绝不删/改名原文件。"""
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        bak = path.with_suffix(path.suffix + ".bak")
        try:
            return json.loads(bak.read_text(encoding="utf-8"))
        except Exception:
            return default


def jappend(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def jreadlines(path: Path) -> list:
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except Exception:
            continue
    return out


def find_by_fingerprint(fp: str) -> str:
    """返回已有容器的 id（同一个文件被移动过时复用旧容器）。"""
    if not fp or not LIB.exists():
        return ""
    for d in LIB.iterdir():
        if not d.is_dir():
            continue
        meta = jload(d / "meta.json", {}) or {}
        if meta.get("fingerprint") == fp:
            return d.name
    return ""


def resolve_id(path: str, fp: str) -> str:
    import hashlib
    import os as _os
    cid = hashlib.sha1(_os.path.normcase(_os.path.abspath(path)).encode("utf-8")).hexdigest()[:12]
    if (LIB / cid / "meta.json").exists():
        return cid
    old = find_by_fingerprint(fp)
    return old or cid


_META_CACHE = {}


class Store:
    def __init__(self, cid: str):
        self.cid = cid
        self.dir = LIB / cid
        self.dir.mkdir(parents=True, exist_ok=True)

    # ---------- 路径 ----------
    @property
    def meta_path(self) -> Path:
        return self.dir / "meta.json"

    @property
    def toc_path(self) -> Path:
        return self.dir / "toc.json"

    @property
    def text_path(self) -> Path:
        return self.dir / "text.jsonl"

    @property
    def memory_path(self) -> Path:
        return self.dir / "memory.md"

    @property
    def ink_path(self) -> Path:
        return self.dir / "ink.jsonl"

    @property
    def chat_path(self) -> Path:
        return self.dir / "chat.jsonl"

    @property
    def brief_path(self) -> Path:
        return self.dir / "brief.md"

    @property
    def map_path(self) -> Path:
        return self.dir / "map.md"

    # ---------- 元信息 ----------
    def exists(self) -> bool:
        return self.meta_path.exists()

    def meta(self) -> dict:
        m = jload(self.meta_path, None)
        if not isinstance(m, dict) or not m:
            m = dict(_META_CACHE.get(self.cid, {}))
        else:
            _META_CACHE[self.cid] = dict(m)
        return dict(m)

    def save_meta(self, **kw) -> dict:
        m = dict(_META_CACHE.get(self.cid, {}))
        disk = jload(self.meta_path, None)
        if isinstance(disk, dict):
            m.update(disk)
        m.update(kw)
        m["updated"] = now()
        _META_CACHE[self.cid] = dict(m)
        jdump(self.meta_path, m)
        return m

    # ---------- 目录 / 正文 ----------
    def save_toc(self, toc: list) -> None:
        jdump(self.toc_path, toc)

    def toc(self) -> list:
        return jload(self.toc_path, []) or []

    def save_text(self, texts: list) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        tmp = self.text_path.with_suffix(".jsonl.tmp")
        with tmp.open("w", encoding="utf-8") as f:
            for i, t in enumerate(texts):
                f.write(json.dumps({"p": i, "t": t}, ensure_ascii=False) + "\n")
        os.replace(tmp, self.text_path)

    def texts(self) -> list:
        rows = jreadlines(self.text_path)
        if not rows:
            return []
        n = max(r.get("p", 0) for r in rows) + 1
        out = [""] * n
        for r in rows:
            p = r.get("p", 0)
            if 0 <= p < n:
                out[p] = r.get("t", "")
        return out

    def page_text(self, index: int) -> str:
        texts = self.texts()
        return texts[index] if 0 <= index < len(texts) else ""

    # ---------- 记忆 ----------
    def brief(self) -> str:
        try:
            return self.brief_path.read_text(encoding="utf-8")
        except Exception:
            return ""

    def save_brief(self, text: str) -> None:
        self.brief_path.parent.mkdir(parents=True, exist_ok=True)
        self.brief_path.write_text(text, encoding="utf-8")

    def memory(self) -> str:
        try:
            return self.memory_path.read_text(encoding="utf-8")
        except Exception:
            return ""

    def save_memory(self, text: str) -> None:
        self.memory_path.parent.mkdir(parents=True, exist_ok=True)
        self.memory_path.write_text(text, encoding="utf-8")

    def append_memory(self, line: str) -> None:
        text = self.memory()
        if not text.strip():
            text = f"# 记忆容器：{self.cid}\n"
        self.save_memory(text.rstrip() + "\n" + line.strip() + "\n")

    # ---------- 圈画 ----------
    def add_inks(self, items: list) -> int:
        known = {r.get("xref") for r in jreadlines(self.ink_path) if r.get("xref")}
        n = 0
        for it in items:
            if it.get("xref") in known:
                continue
            it = dict(it)
            it["ts"] = now()
            jappend(self.ink_path, it)
            n += 1
        return n

    def inks(self) -> list:
        return jreadlines(self.ink_path)

    def recent_inks(self, limit: int = 6) -> list:
        rows = self.inks()
        return rows[-limit:]

    # ---------- 对话 ----------
    def add_chat(self, role: str, content: str, **extra) -> None:
        row = {"ts": now(), "role": role, "content": content}
        row.update(extra or {})
        jappend(self.chat_path, row)

    def chat(self, limit: int = 20) -> list:
        return jreadlines(self.chat_path)[-limit:]