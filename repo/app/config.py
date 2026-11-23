# -*- coding: utf-8 -*-
"""配置：工作区根目录下的 config.json，面板里可改，避免把 key 贴在聊天里。"""
from __future__ import annotations

import json
import os
from pathlib import Path

ROOT = Path(os.environ.get("ANNOTATOR_HOME")
            or Path(__file__).resolve().parent.parent)  # 程序所在目录
CONFIG_PATH = ROOT / "config.json"

_SESSION_KEY = ""

DEFAULTS = {
    "base_url": "https://api.deepseek.com/v1",
    "api_key": "",
    "model": "deepseek-chat",
    "vision_model": "",
    "port": 8760,
    "edge": r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    "layout": "split",
    "temperature": 0.2,
    "max_side": 1400,
    "jpeg_quality": 82,
    "trim_margin": True,
    "capture": "cdp",
    "ui_mode": "reader",
    "sidebar_ratio": 0.30,
    "sidebar_min": 460,
    "custom_prompt": (
        "你是一个陪读助教，正在和学生一起读这本书。"
        "回答要短、要准、不要客套；先给结论，再给必要的一步推理。"
        "公式一律用 LaTeX（行内 $...$，独立 $$...$$）。"
    ),
    "ingest_concurrency": 3,
    "review": False,
    "thinking": True,
    "reasoning_effort": "high",
    "cdp_port": 9222,
    "currency_per_million_in": 0.0,
    "currency_per_million_out": 0.0,
}


def load() -> dict:
    data = dict(DEFAULTS)
    if CONFIG_PATH.exists():
        try:
            data.update(json.loads(CONFIG_PATH.read_text(encoding="utf-8")))
        except Exception:
            pass
    if _SESSION_KEY:
        data["api_key"] = _SESSION_KEY
    for k in ("api_key", "base_url", "model", "vision_model"):
        env = os.environ.get("ANNOTATOR_" + k.upper())
        if env:
            data[k] = env
    if not data.get("vision_model"):
        data["vision_model"] = data.get("model", "")
    return data


def save(patch: dict, persist_key: bool = True) -> dict:
    """persist_key=False 时 key 只留在内存里，不写盘（重启即失效）。"""
    global _SESSION_KEY
    patch = dict(patch or {})
    key = patch.pop("api_key", None)
    data = load()
    for k, v in patch.items():
        if k in DEFAULTS:
            data[k] = v
    if key is not None:
        if persist_key:
            data["api_key"] = key
            _SESSION_KEY = ""
        else:
            _SESSION_KEY = key
            data["api_key"] = key
    on_disk = data.copy()
    if not persist_key and key is not None:
        on_disk["api_key"] = ""
    CONFIG_PATH.write_text(json.dumps(on_disk, ensure_ascii=False, indent=2), encoding="utf-8")
    return data


def public() -> dict:
    """给前端看的配置：不带 key 原文。"""
    data = load()
    data["api_key_set"] = bool(data.get("api_key"))
    data["api_key_saved"] = bool(_SESSION_KEY) is False and bool(data.get("api_key"))
    data["api_key_session"] = bool(_SESSION_KEY)
    data.pop("api_key", None)
    return data