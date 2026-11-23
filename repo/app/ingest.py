# -*- coding: utf-8 -*-
"""把每一页「图」转成 Markdown+LaTeX 文本，存进记忆容器。
只在第一次打开这本书时花一次钱，之后提问都用这份文本。"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

import pymupdf

import config as cfgmod
import llm
import render
import usage

PAGE_PROMPT = r"""你在为一本数学书做逐页转写。请把这一页的内容转成 Markdown：

1. 正文按原文逐字转写，不要总结、不要翻译、不要评论。
2. 行内公式用 $...$，独立公式用 $$...$$，必须是合法 LaTeX。
3. 定理/定义/引理请保留编号与格式，例如 **定义 2.2.5**、*证明*、$\\square$。
4. 图表用一句话说明内容，不要臆造图中文字。
5. 页眉页脚中的书名、章节名、页码放在最后一行，格式：`<footer>第35页 §2.2 函子与自然变换</footer>`。
6. 看不清的地方写 `[[?]]`，不要猜。
7. **交换图不要用 TikZ**（\begin{tikzpicture} 一律禁止）。用一句话描述节点和箭头走向，例如：
   「图中 $C_1 \xrightarrow{F} C_2 \xrightarrow{G} C_1$，以及 $\mathrm{id}_F: F\Rightarrow F$ 的双箭头」。
   简单的情形可以用 $\begin{array}{c} A \\ \downarrow \\ B \end{array}$ 这种纯 LaTeX 数组表达。"""


def page_md_path(store, index: int) -> Path:
    d = store.dir / "pages"
    d.mkdir(parents=True, exist_ok=True)
    return d / ("%04d.md" % (index + 1))


def read_page_md(store, index: int) -> str:
    p = page_md_path(store, index)
    if p.exists():
        return p.read_text(encoding="utf-8")
    return ""


def _clean(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```(?:markdown|md)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


def ingest_pages(book, store, indices: list, cfg: dict | None = None,
                 force: bool = False, on_page=None) -> dict:
    """逐页转写。返回统计。on_page(idx, md) 用来推进度。"""
    cfg = cfg or cfgmod.load()
    vision = cfg.get("vision_model") or cfg.get("model")
    done, skipped, failed = 0, 0, 0
    errors = []
    total_in = total_out = 0

    for idx in indices:
        if not force and read_page_md(store, idx).strip():
            skipped += 1
            if on_page:
                on_page(idx, read_page_md(store, idx))
            continue
        try:
            page = book.doc[idx]
            img = render.render_page(
                page,
                max_side=int(cfg.get("max_side", 1400)),
                trim=bool(cfg.get("trim_margin", True)),
                quality=int(cfg.get("jpeg_quality", 82)),
            )
            msgs = [{
                "role": "user",
                "content": [
                    llm.text_part(PAGE_PROMPT),
                    llm.image_part(img["png"], img["mime"]),
                ],
            }]
            out = llm.complete(cfg, msgs, model=vision)
            md = _clean(out.get("content", ""))
            if not md:
                raise RuntimeError("空返回")
            page_md_path(store, idx).write_text(md, encoding="utf-8")
            u = out.get("usage") or {}
            total_in += int(u.get("prompt_tokens") or 0)
            total_out += int(u.get("completion_tokens") or 0)
            usage.record(store.cid, "ingest", u, model=vision)
            done += 1
            if on_page:
                on_page(idx, md)
        except Exception as e:
            failed += 1
            errors.append(str(e)[:200])
            page_md_path(store, idx).parent.mkdir(parents=True, exist_ok=True)
            (store.dir / "pages" / ("%04d.err" % (idx + 1))).write_text(str(e), encoding="utf-8")
            if on_page:
                on_page(idx, "")

    store.save_meta(
        ingest_state={
            "pages_total": book.pages,
            "pages_done": count_done(store, book.pages),
            "last_run": time.time(),
        }
    )
    return {"done": done, "skipped": skipped, "failed": failed,
            "in": total_in, "out": total_out, "errors": errors[:3]}


def count_done(store, total: int) -> int:
    return sum(1 for i in range(total) if read_page_md(store, i).strip())


def missing_pages(store, total: int) -> list:
    return [i for i in range(total) if not read_page_md(store, i).strip()]

BRIEF_PROMPT = r"""你在为这本书记一张「阅读约定卡」。之后学生每次提问，它都会被放进提示词里，作用是**统一符号和用语**，让回答和书里的写法一致。

严格按下面的结构输出 Markdown，600 字以内：

## 这本书讲什么
一两句话。

## 符号约定
用表格列出书里高频出现的记号，三列：符号 | 含义 | 书里的写法。至少 8 行，只写材料里真实出现过的。例如：

| 符号 | 含义 | 书里的写法 |
|---|---|---|
| $\mathcal{C}$ | 范畴 | 花体，不用 $C$ |
| $\operatorname{id}_X$ | 恒等态射 | 用 \operatorname{id}，不用 1 或 id |

## 用语约定
这本书特有的译名和叫法（例如「态射」而不是「箭头」），以及定理/定义的编号格式（例如 定义 2.2.5）。

## 前置知识
一句话。

要求：
- 只写从材料里能确认的内容，不确定就写「材料不足，未确认」，不要编。
- 符号必须是合法 LaTeX。
- 这张卡是给模型看的写作规范，不要写成书评。"""


def build_brief(store, book, cfg: dict | None = None, sample_chars: int = 900) -> str:
    """用目录 + 每章开头几页，让模型写一份全书背景卡。"""
    import config as cfgmod

    cfg = cfg or cfgmod.load()
    toc = store.toc()
    parts = ["书名：%s" % book.title(), "", "目录："]
    for item in toc[:150]:
        parts.append("%s- 第%d页 %s" % ("  " * max(0, item.get("level", 1) - 1),
                                        item.get("page", 0), item.get("title", "")))
    tops = [t for t in toc if t.get("level") == 1][:12]
    for t in tops:
        md = read_page_md(store, max(0, t["page"] - 1))
        if md:
            parts.append("\n【%s 开头】\n%s" % (t["title"], md[:sample_chars]))
    if len(tops) == 0:
        for i in range(min(3, book.pages)):
            md = read_page_md(store, i)
            if md:
                parts.append("\n【第%d页】\n%s" % (i + 1, md[:sample_chars]))
    body = "\n".join(parts)
    out = llm.complete(cfg, [{"role": "user", "content": BRIEF_PROMPT + "\n\n" + body}],
                       model=cfg.get("model"))
    text = _clean(out.get("content", ""))
    if text:
        store.save_brief(text)
        usage.record(store.cid, "brief", out.get("usage") or {}, model=cfg.get("model", ""))
    return text
