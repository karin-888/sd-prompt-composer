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
    if is_catalog_label_id(jp):
        return tag, jp
    if looks_like_japanese(tag) and looks_like_english_tag(jp):
        tag, jp = jp, tag
    return tag, jp


_NOPLOG_CATEGORY_SAMPLE_RE = re.compile(r"^「.+」カテゴリの作例画像$")
_NOPLOG_GENERIC_SAMPLE_RE = re.compile(r".+(の作例画像?|の作例)$")
_NOPLOG_ARTICLE_LABEL_RE = re.compile(r"[_\-]\d+－|－人物設定|－背景|－装飾")
_TAG_CLAUSE_SPLIT_RE = re.compile(r"[,，]")
_CATALOG_ID_RE = re.compile(r"^[A-Za-z]{1,4}-\d{2,3}$")
_CATALOG_JP_PREFIX_RE = re.compile(r"^[A-Za-z]{1,4}-\d{2,3}\s+")


def is_catalog_label_id(text: str) -> bool:
    return bool(_CATALOG_ID_RE.match((text or "").strip()))


def is_valid_english_prompt_tag(
    text: str,
    *,
    max_len: int = 120,
    max_commas: int = 8,
) -> bool:
    t = (text or "").strip()
    if not t or len(t) > max_len:
        return False
    if t.count(",") > max_commas:
        return False
    if is_catalog_label_id(t):
        return False
    if not looks_like_english_tag(t):
        return False
    if not re.search(r"[a-zA-Z]{3,}", t):
        return False
    return True


def clean_catalog_jp_label(jp: str) -> str:
    jp = (jp or "").strip()
    if not jp or is_catalog_label_id(jp):
        return ""
    jp = _CATALOG_JP_PREFIX_RE.sub("", jp).strip()
    jp = re.sub(r"\s+[A-Za-z]{1,4}-\d{2,3}\s*$", "", jp).strip()
    return jp


def normalize_lookup_key(text: str) -> str:
    text = (text or "").strip().lower()
    for ch in ("\u2011", "\u2010", "‑", "–", "—"):
        text = text.replace(ch, "-")
    text = text.replace("?", "-")
    return re.sub(r"\s+", " ", text)


def tag_first_clause(tag: str) -> str:
    return _TAG_CLAUSE_SPLIT_RE.split(tag or "", 1)[0].strip()


def jp_quality_score(tag: str, jp: str) -> int:
    jp = (jp or "").strip()
    tag = (tag or "").strip()
    if not jp:
        return -1000
    if is_low_quality_jp(tag, jp):
        return -1000
    if normalize_lookup_key(jp) in {
        normalize_lookup_key(tag),
        normalize_lookup_key(tag_first_clause(tag)),
    }:
        return -1000
    if re.match(r"^[a-z]{2}-\d{3}$", jp, re.IGNORECASE):
        return -1000
    score = max(0, 120 - len(jp))
    if looks_like_japanese(jp):
        score += 40
    return score


def is_low_quality_jp(tag: str, jp: str) -> bool:
    """True when jp is a noplog gallery/category caption, not a tag translation."""
    jp = (jp or "").strip()
    tag = (tag or "").strip()
    if not jp or jp == tag:
        return False
    if _NOPLOG_CATEGORY_SAMPLE_RE.match(jp):
        return True
    if _NOPLOG_ARTICLE_LABEL_RE.search(jp):
        return True
    if _NOPLOG_GENERIC_SAMPLE_RE.match(jp):
        clause = normalize_lookup_key(tag_first_clause(tag))
        words = [w for w in re.split(r"[\s\-_/]+", clause) if len(w) >= 4]
        if len(jp) >= 15 and words and not any(w in jp.lower() for w in words):
            return True
    return False


def sanitize_tag_jp(tag: str, jp: str) -> str:
    jp = (jp or "").strip()
    if is_low_quality_jp(tag, jp):
        return ""
    return jp


def build_jp_lookup(items) -> dict[str, str]:
    """Map normalized tag / first-clause keys to the best known Japanese label."""
    lookup: dict[str, str] = {}
    scores: dict[str, int] = {}

    def remember(key: str, tag: str, jp: str) -> None:
        key = normalize_lookup_key(key)
        jp = (jp or "").strip()
        if not key or not jp:
            return
        score = jp_quality_score(tag, jp)
        if score <= -1000:
            return
        prev = scores.get(key)
        if prev is None or score > prev:
            lookup[key] = jp
            scores[key] = score

    for item in items or []:
        tag = (item.get("tag") if isinstance(item, dict) else "") or ""
        jp = (item.get("jp") if isinstance(item, dict) else "") or ""
        tag = str(tag).strip()
        jp = sanitize_tag_jp(tag, str(jp).strip())
        if not tag or not jp:
            continue
        remember(tag, tag, jp)
        remember(tag_first_clause(tag), tag, jp)
    return lookup


def resolve_jp_label(tag: str, jp: str, lookup: dict[str, str] | None = None) -> str:
    tag = (tag or "").strip()
    jp = sanitize_tag_jp(tag, (jp or "").strip())
    if jp and jp_quality_score(tag, jp) > -1000:
        return jp
    if not lookup:
        return ""
    best = ""
    best_score = -1000
    for key in (tag, tag_first_clause(tag)):
        candidate = lookup.get(normalize_lookup_key(key), "")
        if not candidate:
            continue
        score = jp_quality_score(tag, candidate)
        if score > best_score:
            best = candidate
            best_score = score
    return best if best_score > -1000 else ""


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
