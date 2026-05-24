# -*- coding: UTF-8 -*-
"""Helpers to normalize tag / Japanese label pairs."""

from __future__ import annotations

import re
from html import unescape


def strip_html(text: str) -> str:
    text = unescape(re.sub(r"<code[^>]*>([\s\S]*?)</code>", r"\1", text or "", flags=re.IGNORECASE))
    text = unescape(re.sub(r"<[^>]+>", " ", text))
    return re.sub(r"\s+", " ", text).strip()


def looks_like_japanese(text: str) -> bool:
    for ch in text or "":
        o = ord(ch)
        if 0x3040 <= o <= 0x30FF or 0x4E00 <= o <= 0x9FFF or 0xFF66 <= o <= 0xFF9D:
            return True
    return False


def looks_like_english_tag(text: str) -> bool:
    text = (text or "").strip()
    if not text:
        return False
    if looks_like_japanese(text):
        return False
    ascii_chars = sum(1 for ch in text if ord(ch) < 128)
    return ascii_chars / max(len(text), 1) >= 0.65


def normalize_tag_jp(tag: str, jp: str) -> tuple[str, str]:
    tag = (tag or "").strip()
    jp = (jp or "").strip()
    if looks_like_japanese(tag) and looks_like_english_tag(jp):
        tag, jp = jp, tag
    return tag, jp


def jp_from_img_alt(alt: str) -> str:
    alt = (alt or "").strip()
    if not alt:
        return ""
    alt = alt.split("｜", 1)[0].split("|", 1)[0].strip()
    alt = re.sub(r"（.*?）$", "", alt).strip()
    return alt


def detect_table_columns(headers: list[str]) -> tuple[int, int]:
    if not headers:
        return 0, 1

    prompt_idx = None
    name_idx = None
    for i, header in enumerate(headers):
        h = (header or "").strip()
        hl = h.lower()
        if any(k in h for k in ("プロンプト", "呪文", "英語タグ", "タグ")) or "tag" in hl:
            prompt_idx = i
        if any(k in h for k in ("種類", "表情", "髪型", "名称", "項目", "日本語", "意味")):
            name_idx = i

    if prompt_idx is not None and name_idx is not None and prompt_idx != name_idx:
        return prompt_idx, name_idx
    if prompt_idx == 1:
        return 1, 0
    if prompt_idx == 0:
        return 0, 1
    return 0, 1
