# -*- coding: UTF-8 -*-
"""
Import tags and preview images from note.com (image-generation prompt articles).

Uses the public note.com API v3 to discover articles by hashtag and extract
prompts with optional Japanese labels and sample images.

Usage:
  python import_note.py [--dry-run] [--limit N] [--hashtag TAG] [--article-url URL]

Outputs:
  group_tags/note.yaml
  {data_path}/sd-prompt-composer/tag-previews/{tag}.webp
  {data_path}/sd-prompt-composer/note-import-manifest.json
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from html import unescape
from typing import Dict, List, Optional, Set, Tuple

import yaml

_TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
_SCRIPT_DIR = os.path.dirname(_TOOLS_DIR)
for _p in (_SCRIPT_DIR, _TOOLS_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import user_storage
import tag_text_utils
import preview_filenames
import preview_convert

USER_AGENT = "PromptComposerImporter/1.0 (personal local import)"
SECTION_NAME = "note"
REQUEST_DELAY = 0.4
MAX_TAG_LEN = 2000
MAX_TAG_COMMAS = 12
NOTE_API = "https://note.com/api/v3"

DEFAULT_HASHTAGS = (
    "画像生成AI",
    "プロンプト",
    "AIイラスト",
    "Illustrious",
    "Danbooru",
)

PROMPT_TITLE_KEYWORDS = (
    "プロンプト",
    "prompt",
    "Prompt",
    "タグ",
    "呪文",
    "Danbooru",
    "Illustrious",
    "Stable Diffusion",
    "SD ",
    "画風",
    "LoRA",
    "Midjourney",
    "ChatGPT",
    "Gemini",
    "Nanobanana",
    "NovelAI",
)

SKIP_URL_PARTS = ("/membership", "embedded-service")

HEADING_RE = re.compile(r"<h([23])[^>]*>([\s\S]*?)</h\1>", re.IGNORECASE)
FIGURE_RE = re.compile(r"<figure[^>]*>([\s\S]*?)</figure>", re.IGNORECASE)
IMG_RE = re.compile(
    r'<img[^>]+src="([^"]+)"[^>]*(?:alt="([^"]*)")?',
    re.IGNORECASE,
)
BLOCKQUOTE_RE = re.compile(r"<blockquote>([\s\S]*?)</blockquote>", re.IGNORECASE)
TABLE_RE = re.compile(r"<table[\s\S]*?</table>", re.IGNORECASE)
TR_RE = re.compile(r"<tr[^>]*>([\s\S]*?)</tr>", re.IGNORECASE)
TD_RE = re.compile(r"<td[^>]*>([\s\S]*?)</td>", re.IGNORECASE)
TH_RE = re.compile(r"<t[dh][^>]*>([\s\S]*?)</t[dh]>", re.IGNORECASE)
CODE_RE = re.compile(r"<(?:pre|code)[^>]*>([\s\S]*?)</(?:pre|code)>", re.IGNORECASE)
P_BEFORE_FIG_RE = re.compile(
    r"<p[^>]*>([\s\S]*?)</p>\s*<figure[^>]*><img[^>]+src=\"([^\"]+)\"",
    re.IGNORECASE,
)
NUMBERED_TAG_RE = re.compile(
    r"(?:^|\s)(\d{1,4})\s+((?:[a-zA-Z(][a-zA-Z0-9_(),:\-\s]*?[a-zA-Z0-9)]))(?=\s+\d{1,4}\s+[a-zA-Z(]|$)",
    re.IGNORECASE,
)
JP_EN_PAREN_RE = re.compile(
    r"^(.+?)（(.+?)）$|^(.+?)\((.+?)\)$",
)
JP_EN_QUOTE_RE = re.compile(
    r"「([^」:]+)[：:]\s*([^」]+)」",
)
FIG_THEN_P_RE = re.compile(
    r'<figure[^>]*><img[^>]+src="([^"]+)"[^>]*>[\s\S]*?</figure>\s*<p[^>]*>([\s\S]*?)</p>',
    re.IGNORECASE,
)
FIGCAPTION_TAG_RE = re.compile(
    r"\(?([a-zA-Z0-9][a-zA-Z0-9_(),:\-\s]*?:\d+(?:\.\d+)?)\)?",
)
MODEL_CHECKPOINT_RE = re.compile(
    r"waiNSFW|illustrious|noobai|animagine|ponyXL|\.safetensors|_\d{1,3}$|_v\d+",
    re.IGNORECASE,
)
NOTE_META_TAG_RE = re.compile(
    r"「[^」]+」\s*(あり|なし)|での成功例|での出力|強度\s*\d|左が|右が|真ん中が",
)
SKIP_TAG_VALUES = {
    "copy",
    "プロンプト",
    "意味",
    "区分",
    "コピー",
    "copy",
}

SKIP_GROUP_NAMES = (
    "おわりに",
    "はじめに",
    "免責",
    "おまけ",
    "概要",
    "参考",
    "関連",
)


def extension_dir() -> str:
    return os.path.dirname(_SCRIPT_DIR)


def resolve_previews_dir(ext_dir: str) -> str:
    repo_root = os.path.dirname(os.path.dirname(ext_dir))
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)
    try:
        from modules.paths_internal import data_path

        path = os.path.join(data_path, user_storage.USER_SUBDIR, "tag-previews")
    except Exception:
        path = os.path.join(repo_root, user_storage.USER_SUBDIR, "tag-previews")
    os.makedirs(path, exist_ok=True)
    return path


def strip_html(text: str) -> str:
    return tag_text_utils.strip_html(text)


def fetch_json(url: str, timeout: int = 60) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))


def is_note_meta_tag(text: str) -> bool:
    """True for model names, comparison captions, and other non-prompt note.com noise."""
    t = (text or "").strip()
    if not t:
        return True
    if MODEL_CHECKPOINT_RE.search(t):
        return True
    if NOTE_META_TAG_RE.search(t):
        return True
    if re.fullmatch(r"「[^」]+」", t):
        return True
    if t.startswith("（") and ("http" in t or "github" in t.lower()):
        return True
    return False


def is_plausible_tag(tag: str) -> bool:
    t = (tag or "").strip()
    if not t or len(t) > MAX_TAG_LEN:
        return False
    if is_note_meta_tag(t):
        return False
    if t.count(",") > MAX_TAG_COMMAS:
        return False
    if t.lower() in SKIP_TAG_VALUES:
        return False
    if t.startswith("http://") or t.startswith("https://"):
        return False
    if "note.com" in t.lower():
        return False
    if t.startswith("💡") or t.startswith("【免責") or "免責事項" in t:
        return False
    if len(t) > 80 and not re.search(r"[a-zA-Z]", t):
        return False
    if len(t) > 40 and tag_text_utils.looks_like_japanese(t) and not tag_text_utils.looks_like_english_tag(t):
        if "⇒" in t or "修正プロンプト" in t:
            return False
    return True


def should_skip_group(group: str) -> bool:
    g = (group or "").strip()
    if not g:
        return False
    return any(name in g for name in SKIP_GROUP_NAMES)


def title_looks_relevant(title: str) -> bool:
    t = title or ""
    return any(k in t for k in PROMPT_TITLE_KEYWORDS)


def note_article_url(note: dict) -> str:
    user = note.get("user") or {}
    urlname = user.get("urlname") or ""
    key = note.get("key") or ""
    if urlname and key:
        return f"https://note.com/{urlname}/n/{key}"
    return ""


def list_hashtag_articles(
    hashtag: str,
    *,
    max_pages: int = 5,
    free_only: bool = True,
) -> List[dict]:
    encoded = urllib.parse.quote(hashtag, safe="")
    found: List[dict] = []
    seen_keys: Set[str] = set()

    for page in range(1, max_pages + 1):
        url = f"{NOTE_API}/hashtags/{encoded}/notes?sort=popular&page={page}"
        try:
            payload = fetch_json(url)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                break
            raise

        notes = (payload.get("data") or {}).get("notes") or []
        if not notes:
            break

        for note in notes:
            key = note.get("key") or ""
            if not key or key in seen_keys:
                continue
            if free_only:
                if note.get("price", 0) > 0:
                    continue
                if note.get("can_read_note_all") is False:
                    continue
            title = note.get("name") or ""
            if not title_looks_relevant(title):
                continue
            seen_keys.add(key)
            found.append(note)
        time.sleep(REQUEST_DELAY)

    return found


def fetch_note_detail(note_key: str) -> Optional[dict]:
    url = f"{NOTE_API}/notes/{note_key}"
    try:
        payload = fetch_json(url)
    except Exception as e:
        print(f"  [error] fetch failed: {e}")
        return None
    data = payload.get("data") or {}
    if data.get("price", 0) > 0 and not data.get("can_read", False):
        print("  [skip] paid / unreadable note")
        return None
    if not data.get("can_read", True) and data.get("body", "").endswith("..."):
        print("  [skip] truncated body (likely paid)")
        return None
    return data


def parse_title(note: dict) -> str:
    title = (note.get("name") or "").strip()
    title = re.sub(r"\s*\|\s*note.*$", "", title, flags=re.IGNORECASE)
    return title.strip() or "未分類"


def split_by_headings(html: str) -> List[Tuple[str, str]]:
    chunks: List[Tuple[str, str]] = []
    matches = list(HEADING_RE.finditer(html))
    if not matches:
        return [("一覧", html)]

    if matches[0].start() > 0:
        chunks.append(("概要", html[: matches[0].start()]))

    for i, match in enumerate(matches):
        group = strip_html(match.group(2)) or "一覧"
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(html)
        chunks.append((group, html[start:end]))
    return chunks


def jp_from_parenthetical(text: str) -> Tuple[str, str]:
    text = (text or "").strip()
    m = JP_EN_PAREN_RE.match(text)
    if not m:
        return "", ""
    if m.group(1) and m.group(2):
        left, right = m.group(1).strip(), m.group(2).strip()
    else:
        left, right = (m.group(3) or "").strip(), (m.group(4) or "").strip()
    if tag_text_utils.looks_like_japanese(left) and tag_text_utils.looks_like_english_tag(right):
        return right, left
    if tag_text_utils.looks_like_english_tag(left) and tag_text_utils.looks_like_japanese(right):
        return left, right
    return "", ""


def jp_from_group_and_tag(group: str, tag: str) -> str:
    group = (group or "").strip().lstrip("・").strip()
    tag = (tag or "").strip()
    if not tag:
        return ""
    if group and group not in ("一覧", "概要"):
        return f"{group}: {tag}"
    return tag


def parse_numbered_tag_line(text: str) -> List[str]:
    tags: List[str] = []
    for _num, raw in NUMBERED_TAG_RE.findall(text or ""):
        tag = raw.strip().strip(",").strip()
        if tag and is_plausible_tag(tag):
            tags.append(tag)
    return tags


def is_embedded_figure(fig_html: str) -> bool:
    lower = (fig_html or "").lower()
    return any(part in lower for part in SKIP_URL_PARTS)


def normalize_image_url(url: str) -> str:
    url = (url or "").strip()
    if not url:
        return ""
    if url.startswith("//"):
        url = "https:" + url
    return url


def is_content_image(url: str) -> bool:
    url = (url or "").lower()
    if not url:
        return False
    if "profile" in url or "/icons/" in url:
        return False
    return "assets.st-note.com/img/" in url or "d2l930y2yx77uc.cloudfront.net" in url


def parse_sequential_figures(chunk: str, group: str) -> List[Dict]:
    """Pair blockquote-only figures with the next image figure(s) in order."""
    items: List[Dict] = []
    pending_tag = ""
    pending_jp = ""

    for fig_html in FIGURE_RE.findall(chunk):
        if is_embedded_figure(fig_html):
            continue

        imgs = [(normalize_image_url(u), alt) for u, alt in IMG_RE.findall(fig_html)]
        imgs = [(u, alt) for u, alt in imgs if is_content_image(u)]
        blockquotes = [strip_html(b) for b in BLOCKQUOTE_RE.findall(fig_html)]

        if blockquotes and not imgs:
            text = blockquotes[0]
            tag, jp = tag_text_utils.normalize_tag_jp(text, "")
            paren_tag, paren_jp = jp_from_parenthetical(text)
            if paren_tag:
                tag, jp = paren_tag, paren_jp or jp
            if is_plausible_tag(tag):
                pending_tag = tag
                pending_jp = jp or jp_from_group_and_tag(group, tag)
            continue

        if imgs and pending_tag:
            url, alt = imgs[0]
            alt_jp = tag_text_utils.jp_from_img_alt(alt)
            items.append(
                {
                    "tag": pending_tag,
                    "jp": pending_jp or alt_jp or jp_from_group_and_tag(group, pending_tag),
                    "image_url": url,
                    "group": group,
                }
            )
            pending_tag = ""
            pending_jp = ""
            continue

        if blockquotes and imgs:
            items.extend(parse_figure_entries(fig_html, group))

    return items


def parse_figure_entries(fig_html: str, group: str) -> List[Dict]:
    if is_embedded_figure(fig_html):
        return []

    items: List[Dict] = []
    imgs = [(normalize_image_url(u), alt) for u, alt in IMG_RE.findall(fig_html)]
    imgs = [(u, alt) for u, alt in imgs if is_content_image(u)]
    blockquotes = [strip_html(b) for b in BLOCKQUOTE_RE.findall(fig_html)]

    for bq in blockquotes:
        tag, jp = tag_text_utils.normalize_tag_jp(bq, "")
        paren_tag, paren_jp = jp_from_parenthetical(bq)
        if paren_tag:
            tag, jp = paren_tag, paren_jp or jp
        if not is_plausible_tag(tag):
            continue
        image_url = imgs[0][0] if imgs else ""
        alt_jp = tag_text_utils.jp_from_img_alt(imgs[0][1]) if imgs else ""
        items.append(
            {
                "tag": tag,
                "jp": jp or alt_jp or jp_from_group_and_tag(group, tag),
                "image_url": image_url,
                "group": group,
            }
        )

    if not blockquotes and len(imgs) == 1:
        url, alt = imgs[0]
        alt_jp = tag_text_utils.jp_from_img_alt(alt)
        tag, jp = jp_from_parenthetical(alt)
        if tag and is_plausible_tag(tag):
            items.append(
                {
                    "tag": tag,
                    "jp": jp or alt_jp or jp_from_group_and_tag(group, tag),
                    "image_url": url,
                    "group": group,
                }
            )
    return items


def parse_jp_en_quotes(text: str) -> List[Tuple[str, str]]:
    pairs: List[Tuple[str, str]] = []
    for jp, tag in JP_EN_QUOTE_RE.findall(text or ""):
        jp = jp.strip()
        tag = tag.strip().strip("()").strip()
        tag = re.sub(r"^\d{1,4}\s+", "", tag)
        if tag and is_plausible_tag(tag):
            pairs.append((tag, jp))
    return pairs


def parse_group_name_entries(group_name: str, chunk: str) -> List[Dict]:
    """When the section heading itself is 「JP: tag」, pair it with images in the chunk."""
    quotes = parse_jp_en_quotes(group_name)
    if not quotes:
        plain = (group_name or "").strip().strip("「」")
        if ":" in plain or "：" in plain:
            parts = re.split(r"[：:]", plain, maxsplit=1)
            if len(parts) == 2:
                jp, tag = parts[0].strip(), parts[1].strip()
                tag = re.sub(r"^\d{1,4}\s+", "", tag)
                if tag and is_plausible_tag(tag):
                    quotes = [(tag, jp)]
    if not quotes:
        return []

    image_url = ""
    for fig_html in FIGURE_RE.findall(chunk):
        if is_embedded_figure(fig_html):
            continue
        imgs = [(normalize_image_url(u), alt) for u, alt in IMG_RE.findall(fig_html)]
        imgs = [(u, alt) for u, alt in imgs if is_content_image(u)]
        if imgs:
            image_url = imgs[0][0]
            break

    items: List[Dict] = []
    for tag, jp in quotes:
        tag, jp = tag_text_utils.normalize_tag_jp(tag, jp)
        items.append(
            {
                "tag": tag,
                "jp": jp or tag,
                "image_url": image_url,
                "group": group_name,
            }
        )
    return items


def parse_heading_tag_entries(chunk: str, group: str) -> List[Dict]:
    """h2/h3 headings like 「JP: english tag」 paired with the next content image."""
    items: List[Dict] = []
    heading_tag_re = re.compile(
        r"<h([23])[^>]*>([\s\S]*?)</h\1>\s*([\s\S]*?)(?=<h[23][^>]*>|$)",
        re.IGNORECASE,
    )

    for _level, heading_html, section in heading_tag_re.findall(chunk):
        heading = strip_html(heading_html)
        quotes = parse_jp_en_quotes(heading)
        if not quotes and ":" not in heading and "：" not in heading:
            continue
        if not quotes:
            parts = re.split(r"[：:]", heading, maxsplit=1)
            if len(parts) == 2:
                jp, tag = parts[0].strip().strip("「」"), parts[1].strip().strip("「」")
                tag = re.sub(r"^\d{1,4}\s+", "", tag)
                if tag and is_plausible_tag(tag):
                    quotes = [(tag, jp)]

        image_url = ""
        for fig_html in FIGURE_RE.findall(section):
            if is_embedded_figure(fig_html):
                continue
            imgs = [(normalize_image_url(u), alt) for u, alt in IMG_RE.findall(fig_html)]
            imgs = [(u, alt) for u, alt in imgs if is_content_image(u)]
            if imgs:
                image_url = imgs[0][0]
                break

        sub_group = heading if quotes else group
        for tag, jp in quotes:
            tag, jp = tag_text_utils.normalize_tag_jp(tag, jp)
            items.append(
                {
                    "tag": tag,
                    "jp": jp or jp_from_group_and_tag(group, tag),
                    "image_url": image_url,
                    "group": sub_group if sub_group != heading else group,
                }
            )
    return items


def parse_figure_then_paragraph_pairs(chunk: str, group: str) -> List[Dict]:
    """Image figure followed by paragraph containing 「JP: tag」 quotes."""
    items: List[Dict] = []
    for image_url, para_html in FIG_THEN_P_RE.findall(chunk):
        image_url = normalize_image_url(image_url)
        if not is_content_image(image_url):
            continue
        text = strip_html(para_html)
        for tag, jp in parse_jp_en_quotes(text):
            tag, jp = tag_text_utils.normalize_tag_jp(tag, jp)
            items.append(
                {
                    "tag": tag,
                    "jp": jp or jp_from_group_and_tag(group, tag),
                    "image_url": image_url,
                    "group": group,
                }
            )
    return items


def parse_figcaption_tags(chunk: str, group: str) -> List[Dict]:
    items: List[Dict] = []
    for fig_html in FIGURE_RE.findall(chunk):
        if is_embedded_figure(fig_html):
            continue
        imgs = [(normalize_image_url(u), alt) for u, alt in IMG_RE.findall(fig_html)]
        imgs = [(u, alt) for u, alt in imgs if is_content_image(u)]
        if not imgs:
            continue
        image_url = imgs[0][0]
        cap_m = re.search(r"<figcaption>([\s\S]*?)</figcaption>", fig_html, re.IGNORECASE)
        if not cap_m:
            continue
        cap = strip_html(cap_m.group(1)).strip("（）()")
        if not cap or cap.startswith("http") or is_note_meta_tag(cap):
            continue
        weight_m = FIGCAPTION_TAG_RE.search(cap)
        if weight_m:
            tag = weight_m.group(1).strip().strip("()")
        elif (
            len(cap) <= 64
            and tag_text_utils.looks_like_english_tag(cap)
            and re.search(r"[a-zA-Z_][a-zA-Z0-9_ ]*[a-zA-Z0-9_]", cap)
        ):
            tag = cap
        else:
            continue
        if not is_plausible_tag(tag):
            continue
        items.append(
            {
                "tag": tag,
                "jp": jp_from_group_and_tag(group, tag),
                "image_url": image_url,
                "group": group,
            }
        )
    return items


def parse_paragraph_figure_pairs(chunk: str, group: str) -> List[Dict]:
    items: List[Dict] = []
    for para_html, image_url in P_BEFORE_FIG_RE.findall(chunk):
        text = strip_html(para_html)
        if not text or len(text) > 800:
            continue
        image_url = normalize_image_url(image_url)
        if not is_content_image(image_url):
            continue

        numbered = parse_numbered_tag_line(text)
        if numbered:
            for tag in numbered:
                tag, jp = tag_text_utils.normalize_tag_jp(tag, jp_from_group_and_tag(group, tag))
                items.append(
                    {
                        "tag": tag,
                        "jp": jp,
                        "image_url": image_url,
                        "group": group,
                    }
                )
            continue

        paren_tag, paren_jp = jp_from_parenthetical(text)
        if paren_tag and is_plausible_tag(paren_tag):
            items.append(
                {
                    "tag": paren_tag,
                    "jp": paren_jp or jp_from_group_and_tag(group, paren_tag),
                    "image_url": image_url,
                    "group": group,
                }
            )
            continue

        if tag_text_utils.looks_like_english_tag(text) and is_plausible_tag(text):
            items.append(
                {
                    "tag": text,
                    "jp": jp_from_group_and_tag(group, text),
                    "image_url": image_url,
                    "group": group,
                }
            )

        for tag, jp in parse_jp_en_quotes(text):
            tag, jp = tag_text_utils.normalize_tag_jp(tag, jp)
            items.append(
                {
                    "tag": tag,
                    "jp": jp or jp_from_group_and_tag(group, tag),
                    "image_url": image_url,
                    "group": group,
                }
            )
    return items


def parse_code_blocks(chunk: str, group: str) -> List[Dict]:
    items: List[Dict] = []
    for block in CODE_RE.findall(chunk):
        text = strip_html(block)
        if not text or len(text) > MAX_TAG_LEN:
            continue
        paren_tag, paren_jp = jp_from_parenthetical(text)
        if paren_tag and is_plausible_tag(paren_tag):
            items.append({"tag": paren_tag, "jp": paren_jp, "image_url": "", "group": group})
            continue
        if is_plausible_tag(text) and tag_text_utils.looks_like_english_tag(text):
            items.append(
                {
                    "tag": text,
                    "jp": jp_from_group_and_tag(group, text),
                    "image_url": "",
                    "group": group,
                }
            )
    return items


def parse_table_rows(table_html: str) -> List[Tuple[str, str]]:
    rows: List[Tuple[str, str]] = []
    tag_col, jp_col = 0, 1
    header_seen = False

    for tr in TR_RE.findall(table_html):
        if "<th" in tr.lower() or (not header_seen and "プロンプト" in tr):
            headers = [strip_html(c) for c in TH_RE.findall(tr)]
            if headers:
                tag_col, jp_col = tag_text_utils.detect_table_columns(headers)
                header_seen = True
            if "<th" in tr.lower():
                continue

        cells = [strip_html(c) for c in TD_RE.findall(tr)]
        if len(cells) < 2:
            continue
        tag = cells[tag_col].strip() if tag_col < len(cells) else ""
        jp = cells[jp_col].strip() if jp_col < len(cells) else ""
        tag, jp = tag_text_utils.normalize_tag_jp(tag, jp)
        if not tag or not is_plausible_tag(tag):
            continue
        rows.append((tag, jp))
    return rows


def parse_article(note: dict, article_url: str) -> Dict:
    title = parse_title(note)
    body = note.get("body") or ""
    by_tag: Dict[str, Dict] = {}

    def merge(entry: Dict) -> None:
        tag = (entry.get("tag") or "").strip()
        if not tag or not is_plausible_tag(tag):
            return
        tag, jp = tag_text_utils.normalize_tag_jp(tag, entry.get("jp") or "")
        rec = by_tag.get(tag) or {
            "tag": tag,
            "jp": "",
            "image_url": "",
            "group": entry.get("group") or "一覧",
            "article": title,
            "source_url": article_url,
        }
        if jp and (not rec.get("jp") or len(jp) > len(rec.get("jp", ""))):
            rec["jp"] = jp
        if entry.get("image_url"):
            rec["image_url"] = entry["image_url"]
        if entry.get("group"):
            rec["group"] = entry["group"]
        by_tag[tag] = rec

    for group_name, chunk in split_by_headings(body):
        if should_skip_group(group_name):
            continue
        for entry in parse_group_name_entries(group_name, chunk):
            merge(entry)
        for entry in parse_sequential_figures(chunk, group_name):
            merge(entry)
        for entry in parse_paragraph_figure_pairs(chunk, group_name):
            merge(entry)
        for entry in parse_heading_tag_entries(chunk, group_name):
            merge(entry)
        for entry in parse_figure_then_paragraph_pairs(chunk, group_name):
            merge(entry)
        for entry in parse_figcaption_tags(chunk, group_name):
            merge(entry)
        for entry in parse_code_blocks(chunk, group_name):
            merge(entry)
        for table_html in TABLE_RE.findall(chunk):
            for tag, jp in parse_table_rows(table_html):
                merge({"tag": tag, "jp": jp, "image_url": "", "group": group_name})

    return {"title": title, "url": article_url, "entries": list(by_tag.values())}


def copy_related_previews(previews_dir: str, entries: List[Dict]) -> int:
    copied = 0
    existing: Dict[str, str] = {}
    for entry in entries:
        tag = (entry.get("tag") or "").strip()
        if not tag:
            continue
        for ext in (".webp", ".png", ".jpg", ".jpeg", ".gif"):
            path = preview_filenames.preview_path_for_tag(previews_dir, tag, ext)
            if os.path.isfile(path):
                existing[tag.lower()] = path
                break

    for entry in entries:
        tag = (entry.get("tag") or "").strip()
        if not tag or tag.lower() in existing:
            continue
        src = existing.get(tag.split(",", 1)[0].strip().lower())
        if not src:
            for key, path in existing.items():
                if tag.lower().startswith(key + ","):
                    src = path
                    break
        if not src:
            continue
        ext = os.path.splitext(src)[1]
        dest = preview_filenames.preview_path_for_tag(previews_dir, tag, ".webp")
        if os.path.isfile(dest):
            existing[tag.lower()] = dest
            continue
        try:
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            if ext.lower() == ".webp":
                shutil.copy2(src, dest)
            else:
                preview_convert.save_image_as_webp(src, dest)
            existing[tag.lower()] = dest
            copied += 1
        except OSError:
            pass
    return copied


def preview_path_for_tag(previews_dir: str, tag: str) -> str:
    return preview_filenames.preview_path_for_tag(previews_dir, tag, ".webp")


def _encode_request_url(url: str) -> str:
    parts = urllib.parse.urlsplit(url)
    path = urllib.parse.quote(parts.path, safe="/:%")
    return urllib.parse.urlunsplit((parts.scheme, parts.netloc, path, parts.query, parts.fragment))


def download_image(image_url: str, dest_path: str, dry_run: bool = False) -> bool:
    dest_path = preview_convert.webp_dest_path(dest_path)
    if os.path.isfile(dest_path) and os.path.getsize(dest_path) > 0:
        return True
    if dry_run:
        return True
    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
    safe_url = _encode_request_url(image_url)
    req = urllib.request.Request(safe_url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = resp.read()
        return preview_convert.save_bytes_as_webp(data, dest_path)
    except Exception as e:
        print(f"  [warn] image download failed: {image_url} ({e})")
        return False


def build_yaml_structure(articles: List[Dict]) -> List[Dict]:
    categories: Dict[str, Dict] = {}
    for article in articles:
        cat_name = article["title"]
        cat = categories.setdefault(cat_name, {"name": cat_name, "groups": {}})
        groups = cat["groups"]
        for entry in article["entries"]:
            group_name = entry.get("group") or "一覧"
            grp = groups.setdefault(group_name, {"name": group_name, "tags": {}})
            tag = entry["tag"]
            jp = entry.get("jp") or tag
            grp["tags"][tag] = jp

    section = {"name": SECTION_NAME, "categories": []}
    for cat_name in sorted(categories.keys()):
        cat = categories[cat_name]
        cat_obj = {"name": cat_name, "groups": []}
        for group_name in sorted(cat["groups"].keys()):
            grp = cat["groups"][group_name]
            cat_obj["groups"].append(
                {
                    "name": group_name,
                    "tags": dict(sorted(grp["tags"].items(), key=lambda kv: kv[0].lower())),
                }
            )
        section["categories"].append(cat_obj)
    return [section]


MAGazine_URL_RE = re.compile(
    r"note\.com/[^/]+/m/(m[a-f0-9]+)",
    re.IGNORECASE,
)


def parse_magazine_key(ref: str) -> str:
    """Accept magazine URL or raw key (m...)."""
    ref = (ref or "").strip().rstrip("/")
    if not ref:
        return ""
    m = MAGazine_URL_RE.search(ref)
    if m:
        return m.group(1)
    if re.fullmatch(r"m[a-f0-9]+", ref, re.IGNORECASE):
        return ref
    return ""


def list_magazine_articles(
    magazine_key: str,
    *,
    max_pages: int = 5,
    free_only: bool = True,
) -> List[Tuple[str, str]]:
    """Return [(note_key, article_url), ...] from a note.com magazine (マガジン/マイリスト)."""
    found: List[Tuple[str, str]] = []
    seen: Set[str] = set()

    for page in range(1, max_pages + 1):
        url = f"https://note.com/api/v1/magazines/{magazine_key}/notes?page={page}"
        try:
            payload = fetch_json(url)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                break
            raise

        notes = (payload.get("data") or {}).get("notes") or []
        if not notes:
            break

        for note in notes:
            key = note.get("key") or ""
            if not key or key in seen:
                continue
            if free_only and note.get("price", 0) > 0:
                continue
            user = note.get("user") or {}
            urlname = user.get("urlname") or ""
            article_url = f"https://note.com/{urlname}/n/{key}" if urlname else ""
            seen.add(key)
            found.append((key, article_url))
        time.sleep(REQUEST_DELAY)

    return found


def list_creator_articles(
    urlname: str,
    *,
    max_pages: int = 20,
    free_only: bool = True,
) -> List[Tuple[str, str]]:
    found: List[Tuple[str, str]] = []
    seen: Set[str] = set()

    for page in range(1, max_pages + 1):
        url = f"https://note.com/api/v2/creators/{urlname}/contents?kind=note&page={page}"
        try:
            payload = fetch_json(url)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                break
            raise

        contents = (payload.get("data") or {}).get("contents") or []
        if not contents:
            break

        for note in contents:
            key = note.get("key") or ""
            if not key or key in seen:
                continue
            if free_only and note.get("price", 0) > 0:
                continue
            title = note.get("name") or ""
            if not title_looks_relevant(title):
                continue
            seen.add(key)
            found.append((key, f"https://note.com/{urlname}/n/{key}"))
        time.sleep(REQUEST_DELAY)

    return found


def load_existing_yaml_entries(yaml_path: str) -> Dict[str, Dict[str, Dict]]:
    if not os.path.isfile(yaml_path):
        return {}
    try:
        with open(yaml_path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or []
    except Exception:
        return {}

    by_article: Dict[str, Dict[str, Dict]] = {}
    for section in data:
        if (section or {}).get("name") != SECTION_NAME:
            continue
        for cat in section.get("categories", []) or []:
            title = cat.get("name") or ""
            tags: Dict[str, Dict] = {}
            for group in cat.get("groups", []) or []:
                group_name = group.get("name") or "一覧"
                for tag, jp in (group.get("tags") or {}).items():
                    tags[str(tag)] = {
                        "tag": str(tag),
                        "jp": str(jp or tag),
                        "image_url": "",
                        "group": group_name,
                        "article": title,
                        "source_url": "",
                    }
            if title:
                by_article[title] = tags
    return by_article


def merge_article_entries(existing: Dict[str, Dict[str, Dict]], article: Dict) -> None:
    title = article["title"]
    bucket = existing.setdefault(title, {})
    for entry in article["entries"]:
        tag = entry["tag"]
        prev = bucket.get(tag)
        if not prev:
            bucket[tag] = dict(entry)
            continue
        if entry.get("jp") and (not prev.get("jp") or len(entry["jp"]) > len(prev.get("jp", ""))):
            prev["jp"] = entry["jp"]
        if entry.get("image_url"):
            prev["image_url"] = entry["image_url"]
        if entry.get("group"):
            prev["group"] = entry["group"]
        if entry.get("source_url"):
            prev["source_url"] = entry["source_url"]
        bucket[tag] = prev


def replace_article_entries(existing: Dict[str, Dict[str, Dict]], article: Dict) -> None:
    """Replace one article category entirely (drop stale tags from prior imports)."""
    existing[article["title"]] = {}
    merge_article_entries(existing, article)


def articles_from_existing(existing: Dict[str, Dict[str, Dict]]) -> List[Dict]:
    articles: List[Dict] = []
    for title, tags in sorted(existing.items()):
        if not tags:
            continue
        sample = next(iter(tags.values()))
        articles.append(
            {
                "title": title,
                "url": sample.get("source_url") or "",
                "entries": list(tags.values()),
            }
        )
    return articles


def discover_articles(
    hashtags: List[str],
    *,
    max_pages: int = 5,
    article_urls: Optional[List[str]] = None,
    creators: Optional[List[str]] = None,
    magazines: Optional[List[str]] = None,
) -> List[Tuple[str, str]]:
    """Return [(note_key, article_url), ...]"""
    if article_urls:
        out: List[Tuple[str, str]] = []
        for url in article_urls:
            m = re.search(r"note\.com/([^/]+)/n/([a-z0-9]+)", url, re.IGNORECASE)
            if m:
                out.append((m.group(2), url.rstrip("/")))
        return out

    found: List[Tuple[str, str]] = []
    seen: Set[str] = set()

    for mag_ref in magazines or []:
        mag_key = parse_magazine_key(mag_ref)
        if not mag_key:
            print(f"[note import] [warn] invalid magazine ref: {mag_ref}")
            continue
        mag_notes = list_magazine_articles(mag_key, max_pages=max_pages)
        print(f"[note import] magazine {mag_key}: {len(mag_notes)} articles")
        for key, url in mag_notes:
            if key in seen:
                continue
            seen.add(key)
            found.append((key, url))

    for urlname in creators or []:
        creator_notes = list_creator_articles(urlname, max_pages=max_pages)
        print(f"[note import] creator @{urlname}: {len(creator_notes)} candidate articles")
        for key, url in creator_notes:
            if key in seen:
                continue
            seen.add(key)
            found.append((key, url))

    scan_hashtags = hashtags if hashtags is not None else (
        [] if (creators or magazines) else list(DEFAULT_HASHTAGS)
    )
    for hashtag in scan_hashtags:
        notes = list_hashtag_articles(hashtag, max_pages=max_pages)
        print(f"[note import] hashtag #{hashtag}: {len(notes)} candidate articles")
        for note in notes:
            key = note.get("key") or ""
            if not key or key in seen:
                continue
            seen.add(key)
            found.append((key, note_article_url(note)))
    return found


def run_import(
    dry_run: bool = False,
    limit: Optional[int] = None,
    hashtags: Optional[List[str]] = None,
    article_urls: Optional[List[str]] = None,
    creators: Optional[List[str]] = None,
    magazines: Optional[List[str]] = None,
    max_pages: int = 5,
    min_tags: int = 3,
    merge_existing: bool = False,
) -> Dict:
    ext_dir = extension_dir()
    previews_dir = resolve_previews_dir(ext_dir)
    yaml_path = os.path.join(ext_dir, "group_tags", "note.yaml")
    manifest_path = user_storage.bootstrap_json(ext_dir, "note-import-manifest.json")

    tags_list = hashtags if hashtags is not None else (
        [] if (creators or magazines) else list(DEFAULT_HASHTAGS)
    )
    candidates = discover_articles(
        tags_list,
        max_pages=max_pages,
        article_urls=article_urls,
        creators=creators,
        magazines=magazines,
    )
    if limit:
        candidates = candidates[:limit]

    print(f"[note import] fetching {len(candidates)} articles")
    parsed_articles: List[Dict] = []
    all_entries: List[Dict] = []
    images_ok = 0
    images_fail = 0
    skipped = 0
    partial_import = merge_existing or bool(article_urls) or bool(creators) or bool(magazines)
    existing_by_article = load_existing_yaml_entries(yaml_path) if partial_import and os.path.isfile(yaml_path) else {}

    for i, (note_key, article_url) in enumerate(candidates, 1):
        print(f"[{i}/{len(candidates)}] {article_url or note_key}")
        note = fetch_note_detail(note_key)
        if not note:
            skipped += 1
            continue
        article = parse_article(note, article_url)
        if len(article["entries"]) < min_tags:
            print(f"  [skip] only {len(article['entries'])} tags (< {min_tags})")
            skipped += 1
            continue
        parsed_articles.append(article)
        if partial_import:
            if magazines:
                replace_article_entries(existing_by_article, article)
            else:
                merge_article_entries(existing_by_article, article)
        print(f"  title: {article['title']}  tags: {len(article['entries'])}")

        for entry in article["entries"]:
            all_entries.append(entry)
            image_url = entry.get("image_url") or ""
            if not image_url:
                continue
            dest = preview_path_for_tag(previews_dir, entry["tag"])
            ok = download_image(image_url, dest, dry_run=dry_run)
            if ok:
                images_ok += 1
                entry["preview_file"] = os.path.basename(dest)
            else:
                images_fail += 1
            time.sleep(REQUEST_DELAY * 0.25)

        time.sleep(REQUEST_DELAY)

    if partial_import and existing_by_article:
        parsed_articles = articles_from_existing(existing_by_article)
        all_entries = [entry for article in parsed_articles for entry in article["entries"]]

    preview_copied = 0
    if not dry_run and all_entries:
        preview_copied = copy_related_previews(previews_dir, all_entries)
        if preview_copied:
            print(f"[note import] copied {preview_copied} related preview files for compound tags")

    yaml_data = build_yaml_structure(parsed_articles)
    tag_count = len({e["tag"] for e in all_entries})
    with_image = sum(1 for e in all_entries if e.get("image_url"))

    if not dry_run and parsed_articles:
        os.makedirs(os.path.dirname(yaml_path), exist_ok=True)
        with open(yaml_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(
                yaml_data,
                f,
                allow_unicode=True,
                sort_keys=False,
                default_flow_style=False,
                width=120,
            )

        known_tags = {e["tag"] for e in all_entries}
        mig = preview_filenames.migrate_preview_files(previews_dir, known_tags=known_tags)
        if mig.get("migrated") or mig.get("removed_dirs"):
            print(f"[note import] preview migration: {mig}")

        manifest = {
            "imported_at": time.time(),
            "source": "https://note.com/",
            "hashtags": tags_list,
            "creators": creators or [],
            "magazines": magazines or [],
            "article_count": len(parsed_articles),
            "skipped_articles": skipped,
            "tag_count": tag_count,
            "entries_with_image_url": with_image,
            "images_downloaded_ok": images_ok,
            "images_failed": images_fail,
            "related_previews_copied": preview_copied,
            "yaml_path": yaml_path,
            "previews_dir": previews_dir,
            "articles": [
                {
                    "title": a["title"],
                    "url": a["url"],
                    "tag_count": len(a["entries"]),
                }
                for a in parsed_articles
            ],
        }
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)

    summary = {
        "articles": len(parsed_articles),
        "skipped": skipped,
        "tags": tag_count,
        "with_image_url": with_image,
        "images_ok": images_ok,
        "images_fail": images_fail,
        "yaml_path": yaml_path,
        "previews_dir": previews_dir,
    }
    print("[note import] done:", summary)
    return summary


def main():
    parser = argparse.ArgumentParser(description="Import note.com image-AI prompt tags and preview images")
    parser.add_argument("--dry-run", action="store_true", help="Parse only; do not write files")
    parser.add_argument("--limit", type=int, default=0, help="Limit number of articles (debug)")
    parser.add_argument(
        "--hashtag",
        action="append",
        default=[],
        help="Hashtag to scan (repeatable). Default: built-in list",
    )
    parser.add_argument(
        "--article-url",
        action="append",
        default=[],
        help="Import specific note article URL(s); can be repeated",
    )
    parser.add_argument(
        "--creator",
        action="append",
        default=[],
        help="Import free prompt articles from note creator urlname (repeatable)",
    )
    parser.add_argument(
        "--magazine",
        action="append",
        default=[],
        help="Import articles from note magazine URL or key (repeatable), e.g. "
        "https://note.com/user/m/m26a152580745",
    )
    parser.add_argument("--max-pages", type=int, default=5, help="Pages per hashtag/creator/magazine (default 5)")
    parser.add_argument("--min-tags", type=int, default=None, help="Skip articles with fewer tags (default: 1 for magazine, 3 otherwise)")
    args = parser.parse_args()

    hashtags = args.hashtag if args.hashtag else None
    urls = [u.rstrip("/") for u in args.article_url] if args.article_url else None
    creators = args.creator or None
    magazines = args.magazine or None
    merge = bool(args.article_url or args.creator or args.magazine)
    min_tags = args.min_tags
    if min_tags is None:
        min_tags = 1 if magazines else 3
    run_import(
        dry_run=args.dry_run,
        limit=args.limit or None,
        hashtags=hashtags,
        article_urls=urls,
        creators=creators,
        magazines=magazines,
        max_pages=max(1, args.max_pages),
        min_tags=max(1, min_tags),
        merge_existing=merge,
    )


if __name__ == "__main__":
    main()
