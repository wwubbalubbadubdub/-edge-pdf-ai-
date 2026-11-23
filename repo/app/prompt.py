# -*- coding: utf-8 -*-
"""拼 prompt。核心纪律：稳定内容一律放最前面，保证缓存前缀不漂移。"""
from __future__ import annotations

import ingest

SYSTEM_TMPL = """{custom}

【这本书的背景】
{brief}

【怎么回答】
1. 先给结论，一两句话说清楚。不要"这个问题很好"这类开场。
2. 默认不超过 150 字；学生明确要展开时才详细讲。
3. 只讲这一步为什么成立、用了哪个定义/定理，不要复述题意、不要泛泛而谈。
4. 引用书里的内容要落到具体位置：「定义 2.2.5」「页脚那行」「第二行」。
5. 公式必须是合法 LaTeX。
6. 看不清就说「这处看不清」，不要猜、不要编公式。
7. 不要用大标题、不要分很多层、不要堆 emoji。需要列步骤时最多 3 条。

【目录】
{toc}

【已经积累的理解】
{memory}
"""


def _toc_block(toc: list) -> str:
    if not toc:
        return "（这本书没有可用的书签目录）"
    lines = []
    for item in toc[:200]:
        indent = "  " * max(0, int(item.get("level", 1)) - 1)
        lines.append("%s- p%d %s" % (indent, item.get("page", 0), item.get("title", "")))
    return "\n".join(lines)


def system_message(store, title: str) -> str:
    import config as cfgmod

    cfg = cfgmod.load()
    custom = (cfg.get("custom_prompt") or "").strip() or "你是一个陪读助教。"
    brief = (store.brief() or "").strip()
    if not brief:
        brief = "（这本书还没有生成背景，你只看到了当前这一页的截图，回答时不要臆测全书内容。）"
    elif len(brief) > 3000:
        brief = brief[:3000] + "\n……（后略）"
    memory = (store.memory() or "").strip()
    if len(memory) > 4000:
        memory = memory[:4000] + "\n……（后略）"
    return SYSTEM_TMPL.format(
        custom=custom,
        brief=brief,
        toc=_toc_block(store.toc()),
        memory=memory or "（还没有）",
    )


def page_block(store, indices: list, limit_per_page: int = 3000) -> str:
    chunks = []
    for i in indices:
        md = ingest.read_page_md(store, i).strip()
        if not md:
            continue
        if len(md) > limit_per_page:
            md = md[:limit_per_page] + "\n……（本页后略）"
        chunks.append("### 第 %d 页\n\n%s" % (i + 1, md))
    if not chunks:
        return ""
    return "以下是这本书的三页原文（上/中/下）：\n\n" + "\n\n".join(chunks)


def mark_hint(marks: list) -> str:
    if not marks:
        return ""
    parts = []
    for m in marks[:4]:
        r = m.get("rect") or [0, 0, 0, 0]
        parts.append("第%d页 区域(x0=%.0f,y0=%.0f,x1=%.0f,y1=%.0f, %s)" % (
            m.get("page", 0) + 1, r[0], r[1], r[2], r[3], m.get("kind", "")))
    return "学生最近的圈画：" + "；".join(parts)