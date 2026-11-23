# -*- coding: utf-8 -*-
"""页面渲染：裁掉白边 + 自适应缩放 + JPEG，尽量少花视觉 token。"""
from __future__ import annotations

import math

import numpy as np
import pymupdf


def content_bbox(page: pymupdf.Page, threshold: int = 245, probe_dpi: int = 60, pad: float = 6.0):
    """用低分辨率灰度图找出真正有内容的区域（页面坐标）。"""
    pix = page.get_pixmap(dpi=probe_dpi, colorspace=pymupdf.csGRAY)
    w, h = pix.width, pix.height
    if w < 4 or h < 4:
        return pymupdf.Rect(page.rect)
    arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(h, w)
    mask = arr < threshold
    if not mask.any():
        return pymupdf.Rect(page.rect)
    rows = np.where(mask.any(axis=1))[0]
    cols = np.where(mask.any(axis=0))[0]
    scale = 72.0 / probe_dpi
    rect = pymupdf.Rect(
        cols[0] * scale - pad,
        rows[0] * scale - pad,
        (cols[-1] + 1) * scale + pad,
        (rows[-1] + 1) * scale + pad,
    ) & page.rect
    if rect.is_empty or rect.width < 40 or rect.height < 40:
        return pymupdf.Rect(page.rect)
    return rect


def render_page(page: pymupdf.Page, max_side: int = 1400, trim: bool = True,
                quality: int = 82, gray: bool = False) -> dict:
    rect = content_bbox(page) if trim else pymupdf.Rect(page.rect)
    long_pt = max(rect.width, rect.height)
    dpi = int(max(72, min(400, round(max_side * 72.0 / long_pt))))
    pix = page.get_pixmap(clip=rect, dpi=dpi, colorspace=pymupdf.csGRAY if gray else pymupdf.csRGB)
    try:
        data = pix.tobytes("jpeg", jpg_quality=quality)
        mime = "image/jpeg"
    except Exception:
        data = pix.tobytes("png")
        mime = "image/png"
    return {
        "png": data, "mime": mime, "width": pix.width, "height": pix.height,
        "dpi": dpi, "rect": [round(v, 2) for v in rect],
        "trim_ratio": round((rect.width * rect.height) / (page.rect.width * page.rect.height), 3),
    }


def est_tokens(w: int, h: int) -> dict:
    """两种主流计费口径的粗估，只用于事前量级判断。"""
    qwen = int(math.ceil(w / 28.0) * math.ceil(h / 28.0))
    tiles = math.ceil(w / 512.0) * math.ceil(h / 512.0)
    gpt = int(85 + 170 * tiles)
    return {"qwen_like": qwen, "openai_like": gpt}