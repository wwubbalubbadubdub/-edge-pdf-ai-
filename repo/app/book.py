# -*- coding: utf-8 -*-
"""PDF 访问层：目录、正文、Edge 墨迹注记、区域小图。"""
from __future__ import annotations

import hashlib
import os

import pymupdf

# 值得当作「用户标记」的注记类型名
MARK_KINDS = {
    "Ink", "Highlight", "Underline", "StrikeOut",
    "Square", "Circle", "Text", "FreeText", "Squiggly",
}


def norm_path(path: str) -> str:
    return os.path.normcase(os.path.abspath(path))


def book_id(path: str) -> str:
    """稳定 id：只跟路径有关，Edge 保存墨迹后文件变了也不会换容器。"""
    return hashlib.sha1(norm_path(path).encode("utf-8")).hexdigest()[:12]


class Book:
    def __init__(self, path: str):
        self.path = os.path.abspath(path)
        self.doc = pymupdf.open(self.path)
        self.id = book_id(self.path)

    # ---------- 基本信息 ----------
    @property
    def pages(self) -> int:
        return self.doc.page_count

    def title(self) -> str:
        meta = self.doc.metadata or {}
        t = (meta.get("title") or "").strip()
        if t and not t.lower().endswith(".pdf"):
            return t
        return os.path.splitext(os.path.basename(self.path))[0]

    def toc(self) -> list:
        raw = self.doc.get_toc(simple=True) or []
        out = []
        for lv, title, page in raw:
            title = (title or "").strip()
            if title:
                out.append({"level": int(lv), "title": title, "page": int(page)})
        return out

    def chapter_of(self, page_index: int) -> dict:
        """page_index 是 0 基，返回该页所属的最近目录条目。"""
        num = page_index + 1
        cur = None
        for item in self.toc():
            if item["page"] <= num:
                cur = item
            else:
                break
        return cur or {}

    # ---------- 正文 ----------
    def page_text(self, index: int) -> str:
        if not (0 <= index < self.pages):
            return ""
        return self.doc[index].get_text("text").strip()

    def all_text(self) -> list:
        return [self.page_text(i) for i in range(self.pages)]

    def text_hash(self, texts=None) -> str:
        texts = texts if texts is not None else self.all_text()
        h = hashlib.sha1()
        for t in texts:
            h.update(t.encode("utf-8", "ignore"))
            h.update(b"\x00")
        return h.hexdigest()

    def char_count(self) -> int:
        return sum(len(t) for t in self.all_text())

    def is_scanned(self) -> bool:
        """粗暴但够用：平均每页不到 30 个字，就当成图片版。"""
        texts = self.all_text()
        if not texts:
            return True
        return sum(len(t) for t in texts) / max(1, len(texts)) < 30

    # ---------- 墨迹 ----------
    def marks(self, page_index: int, since: float = 0.0) -> list:
        """取某页上的用户标记。since 用于只拿新标记（按 xref 过滤由上层负责）。"""
        if not (0 <= page_index < self.pages):
            return []
        page = self.doc[page_index]
        out = []
        for a in page.annots() or []:
            kind = a.type[1]
            if kind not in MARK_KINDS:
                continue
            rect = pymupdf.Rect(a.rect)
            item = {
                "page": page_index,
                "kind": kind,
                "xref": a.xref,
                "rect": [round(v, 2) for v in rect],
                "lines": self.lines_in_rect(page_index, rect),
            }
            try:
                item["vertices"] = a.vertices
            except Exception:
                item["vertices"] = None
            out.append(item)
        return out

    def all_marks(self) -> list:
        out = []
        for i in range(self.pages):
            out.extend(self.marks(i))
        return out

    def lines_in_rect(self, page_index: int, rect, pad: float = 2.0) -> list:
        """把矩形落到具体的文字行上，返回整行文字（比 get_textbox 稳）。"""
        page = self.doc[page_index]
        r = pymupdf.Rect(rect) + (-pad, -pad, pad, pad)
        out = []
        for block in page.get_text("dict").get("blocks", []):
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                lr = pymupdf.Rect(line["bbox"])
                inter = lr & r
                if inter.is_empty or inter.height < lr.height * 0.45:
                    continue
                text = "".join(s.get("text", "") for s in line.get("spans", [])).strip()
                if text:
                    out.append({"text": text, "bbox": [round(v, 2) for v in lr]})
        return out

    # ---------- 小图（给视觉模型看公式/图） ----------
    def region_png(self, page_index: int, rect, dpi: int = 180) -> bytes:
        page = self.doc[page_index]
        return page.get_pixmap(clip=pymupdf.Rect(rect), dpi=dpi).tobytes("png")

    def page_png(self, page_index: int, dpi: int = 110) -> bytes:
        return self.doc[page_index].get_pixmap(dpi=dpi).tobytes("png")

    def close(self):
        try:
            self.doc.close()
        except Exception:
            pass

def fingerprint(path: str, head: int = 131072) -> str:
    """用大小 + 前 128KB 算指纹：文件被改名/挪位置也能认出是同一本。"""
    h = hashlib.sha1()
    size = os.path.getsize(path)
    h.update(str(size).encode())
    with open(path, "rb") as f:
        h.update(f.read(head))
    return h.hexdigest()[:16]
