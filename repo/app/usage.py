# -*- coding: utf-8 -*-
"""花钱账本：每次调用都记一笔，面板能显示这本书到底花了多少。"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

ROOT = Path(os.environ.get("ANNOTATOR_HOME")
            or Path(__file__).resolve().parent.parent)  # 程序所在目录
USAGE = ROOT / "library" / "_usage.jsonl"


def record(book_id: str, task: str, usage: dict, model: str = "") -> None:
    if not usage:
        return
    row = {
        "ts": time.time(),
        "book": book_id,
        "task": task,
        "model": model,
        "in": int(usage.get("prompt_tokens") or 0),
        "out": int(usage.get("completion_tokens") or 0),
        "hit": int(usage.get("prompt_cache_hit_tokens") or 0),
        "miss": int(usage.get("prompt_cache_miss_tokens") or 0),
        "reason": int((usage.get("completion_tokens_details") or {}).get("reasoning_tokens") or 0),
    }
    USAGE.parent.mkdir(parents=True, exist_ok=True)
    with USAGE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def totals(book_id: str | None = None) -> dict:
    tin = tout = calls = hit = miss = 0
    if USAGE.exists():
        for line in USAGE.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
            except Exception:
                continue
            if book_id and row.get("book") != book_id:
                continue
            tin += row.get("in", 0)
            tout += row.get("out", 0)
            hit += row.get("hit", 0)
            miss += row.get("miss", 0)
            calls += 1
    rate = round(100.0 * hit / (hit + miss), 1) if (hit + miss) else 0.0
    return {"in": tin, "out": tout, "calls": calls, "cache_hit": hit, "cache_miss": miss, "cache_rate": rate}