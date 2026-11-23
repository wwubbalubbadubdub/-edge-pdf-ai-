# -*- coding: utf-8 -*-
"""极简 OpenAI 兼容客户端（urllib，流式 SSE）。"""
from __future__ import annotations

import base64
import json
import urllib.error
import urllib.request


def _endpoints(base_url: str) -> list:
    base = (base_url or "").rstrip("/")
    if base.endswith("/chat/completions"):
        return [base]
    if base.endswith("/v1"):
        return [base + "/chat/completions"]
    return [base + "/chat/completions", base + "/v1/chat/completions"]


def _endpoint(base_url: str) -> str:
    return _endpoints(base_url)[0]


def _headers(cfg: dict) -> dict:
    h = {"Content-Type": "application/json", "Accept": "text/event-stream"}
    key = (cfg.get("api_key") or "").strip()
    if key:
        h["Authorization"] = "Bearer " + key
    return h


def image_part(data: bytes, mime: str = "image/jpeg") -> dict:
    b64 = base64.b64encode(data).decode("ascii")
    return {"type": "image_url", "image_url": {"url": "data:%s;base64,%s" % (mime, b64)}}


def text_part(text: str) -> dict:
    return {"type": "text", "text": text}


def build_messages(system: str, turns: list) -> list:
    msgs = []
    if system:
        msgs.append({"role": "system", "content": system})
    msgs.extend(turns)
    return msgs


def stream(cfg: dict, messages: list, model: str | None = None, temperature: float | None = None):
    """逐块产出 ("text", str) 或 ("usage", dict)。"""
    if str(cfg.get("base_url", "")).startswith("mock"):
        demo = ("这是**模拟回答**（还没配模型 key），用来验证界面：\n\n"
                "设 $A \\in M_n(\\mathbb{k})$，则\n\n"
                "$$\\det A \\neq 0 \\iff A \\text{ 可逆}$$\n\n"
                "1. 第一步行列式展开\n2. 第二步用初等变换\n\n"
                "> 圈住的那一行是定理的前提条件。\n")
        for ch in demo:
            yield ("text", ch)
        yield ("usage", {"prompt_tokens": 1200, "completion_tokens": 80})
        return
    payload = {
        "model": model or cfg.get("model"),
        "messages": messages,
        "stream": True,
        "stream_options": {"include_usage": True},
        "temperature": cfg.get("temperature", 0.2) if temperature is None else temperature,
    }
    if cfg.get("thinking"):
        payload["thinking"] = {"type": "enabled"}
        if cfg.get("reasoning_effort"):
            payload["reasoning_effort"] = cfg["reasoning_effort"]
    else:
        payload["thinking"] = {"type": "disabled"}
    resp = None
    last = None
    for url in _endpoints(cfg.get("base_url", "")):
        req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"),
                                     headers=_headers(cfg), method="POST")
        try:
            resp = urllib.request.urlopen(req, timeout=300)
            break
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "ignore")[:500]
            last = "HTTP %s: %s" % (e.code, body)
            if e.code != 404:
                break
        except Exception as e:
            last = "连接失败：%s" % e
            break
    if resp is None:
        yield ("error", last or "请求失败")
        return
    with resp:
        for raw in resp:
            line = raw.decode("utf-8", "ignore").strip()
            if not line or not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            try:
                obj = json.loads(data)
            except Exception:
                continue
            if obj.get("usage"):
                yield ("usage", obj["usage"])
            err = obj.get("error")
            if err:
                yield ("error", str(err)[:300])
            for ch in obj.get("choices") or []:
                delta = ch.get("delta") or {}
                reasoning = delta.get("reasoning_content") or delta.get("reasoning")
                if reasoning:
                    yield ("reasoning", reasoning)
                piece = delta.get("content")
                if piece:
                    yield ("text", piece)


def complete(cfg: dict, messages: list, model: str | None = None) -> dict:
    """非流式，用于后台整理记忆这类任务。"""
    if str(cfg.get("base_url", "")).startswith("mock"):
        return {
            "content": ("**定义 2.2.5**（模拟转写）设 $F, G: C \\to C'$ 为函子，"
                        "若 $\\theta: F \\Rightarrow G$ 使得对任意 $f: X \\to Y$ 有\n\n"
                        "$$\\theta_Y \\circ Ff = Gf \\circ \\theta_X$$\n\n"
                        "则称 $\\theta$ 为从 $F$ 到 $G$ 的**自然变换**。"),
            "usage": {"prompt_tokens": 1024, "completion_tokens": 120},
            "model": "mock",
        }
    payload = {
        "model": model or cfg.get("model"),
        "messages": messages,
        "temperature": 0.2,
        "thinking": {"type": "disabled"},
    }
    req = urllib.request.Request(
        _endpoint(cfg.get("base_url", "")),
        data=json.dumps(payload).encode("utf-8"),
        headers={**_headers(cfg), "Accept": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=300) as resp:
        obj = json.loads(resp.read().decode("utf-8", "ignore"))
    content = ""
    for ch in obj.get("choices") or []:
        content += (ch.get("message") or {}).get("content") or ""
    return {"content": content, "usage": obj.get("usage") or {}, "model": obj.get("model", "")}