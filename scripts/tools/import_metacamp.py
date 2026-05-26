#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""Import meta-camp.net (METACAMP:ABYSS) image-generation prompts into a YAML dictionary.

The site is a WordPress installation where each article is structured as
``<h2>`` sub-system → ``<h3>`` sub-group → ``<table>`` with three columns
``日本語 / プロンプト / ひとこと解説``. Some pages use only two columns
(``日本語 / プロンプト``). This importer crawls a curated list of prompt
articles and aggregates their tags into a single YAML file.

Output:
    extensions/sd-prompt-composer/group_tags/metacamp.yaml
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import time
import urllib.request
from html import unescape
from typing import Dict, List, Optional, Tuple

import yaml

_TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
_SCRIPT_DIR = os.path.dirname(_TOOLS_DIR)
for _p in (_SCRIPT_DIR, _TOOLS_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

USER_AGENT = "Mozilla/5.0 (compatible; PromptComposerImporter/1.0; metacamp)"
BASE = "https://meta-camp.net"
SECTION_NAME = "METACAMP:ABYSS (meta-camp.net)"
CACHE_DIR = "/tmp/pc-tag-import/metacamp"
REQUEST_DELAY = 0.4

# (category_label_for_yaml, article_slug)
ARTICLES: List[Tuple[str, str]] = [
    ("NSFW入門ガイド", "stable-diffusion-nsfw-prompt"),
    ("フェチ表現700選", "stable-diffusion-fetish-prompt"),
    ("美少女639選", "stable-diffusion-girl-prompts"),
    ("胸プロンプト完全版", "breasts-prompt-perfect-guide"),
    ("お尻突き出し", "pushing-hips-prompts"),
    ("スレンダー攻略", "slender-lady-prompt"),
    ("靴下・タイツ・パンスト", "pantyhose-tights-socks-prompt"),
    ("OL職場NSFW", "office-situation-nsfw-prompts"),
    ("全身衣装69選", "full-body-clothing-prompt"),
    ("カメラアングル140選", "camera-angle-prompt"),
    ("NSFW表情", "nsfw-face-expression-prompts"),
    ("NSFW前戯", "stablediffusion-nsfw-sex-action"),
    ("NSFW体位", "stablediffusion-nsfw-sex-position"),
    ("体型チェックポーズ", "body-preview-prompt"),
    ("1girl顔", "beginners-creating-beautiful-girls-face"),
    ("1girl体", "beginners-creating-beautiful-girls-body"),
    ("1girl完成編", "beginners-creating-beautiful-girls-complete"),
    ("全身衣装モダン編", "prompt-genesis-modern-edition"),
]

POST_CONTENT_RE = re.compile(
    r'class="(?:entry-content|post_content|p-postContent|c-postContent)[^"]*"[^>]*>([\s\S]+?)(?=<footer|class="article_footer|class="post-end|class="end-of-post|<aside)',
    re.IGNORECASE,
)
HEADING_RE = re.compile(r"<h([234])[^>]*>([\s\S]*?)</h\1>", re.IGNORECASE)
TABLE_RE = re.compile(r"<table[\s\S]*?</table>", re.IGNORECASE)
TR_RE = re.compile(r"<tr[^>]*>([\s\S]*?)</tr>", re.IGNORECASE)
TD_RE = re.compile(r"<t[dh][^>]*>([\s\S]*?)</t[dh]>", re.IGNORECASE)
TAG_STRIP_RE = re.compile(r"<[^>]+>")

ENG_TAG_RE = re.compile(r"^[a-zA-Z0-9 _\-,'\.!?()/:]+$")

SKIP_HEADINGS = (
    "コメント",
    "目次",
    "関連記事",
    "あわせて読みたい",
    "プロフィール",
    "PROFILE",
    "新着",
    "人気",
    "Comment",
)
GROUP_COUNT_SUFFIX = re.compile(r"\s*[\(（][0-9０-９]+[個選]?[\)）]\s*$")

CYBER_TABLE_RE = re.compile(r'<table[^>]*class="[^"]*cyber-rich-table[^"]*"[\s\S]*?</table>', re.IGNORECASE)
CYBER_MAIN_ROW_RE = re.compile(r'<tr[^>]*class="[^"]*main-row[^"]*"[\s\S]*?</tr>', re.IGNORECASE)
TAG_CODE_RE = re.compile(r'<div[^>]*class="tag-code"[^>]*>([\s\S]*?)</div>', re.IGNORECASE)
ALIAS_MAIN_RE = re.compile(r'<div[^>]*class="alias-main"[^>]*>([\s\S]*?)</div>', re.IGNORECASE)


def fetch_url(url: str, cache_name: Optional[str] = None, force: bool = False, timeout: int = 60) -> str:
    if cache_name:
        os.makedirs(CACHE_DIR, exist_ok=True)
        cache = os.path.join(CACHE_DIR, cache_name)
        if not force and os.path.isfile(cache):
            with open(cache, encoding="utf-8") as f:
                return f.read()
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        text = resp.read().decode("utf-8", errors="replace")
    if cache_name:
        with open(os.path.join(CACHE_DIR, cache_name), "w", encoding="utf-8") as f:
            f.write(text)
        time.sleep(REQUEST_DELAY)
    return text


def _strip_html(s: str) -> str:
    return unescape(TAG_STRIP_RE.sub("", s)).strip()


def _cell_to_lines(cell_html: str) -> List[str]:
    s = re.sub(r"<br\s*/?>", "\n", cell_html, flags=re.IGNORECASE)
    s = unescape(TAG_STRIP_RE.sub("", s))
    return [line.strip() for line in s.splitlines() if line.strip()]


def _clean_en(text: str) -> str:
    text = text.strip().strip("`")
    text = text.replace("\u2018", "'").replace("\u2019", "'")
    text = re.sub(r"\s+", " ", text)
    text = text.strip(",.;:!?")
    return text


def _clean_jp(text: str) -> str:
    text = text.strip()
    text = re.sub(r"\s+", " ", text)
    return text


def _is_useful_english(text: str) -> bool:
    if not text or len(text) > 120:
        return False
    if "○" in text:
        return False
    if "<" in text and ">" in text:
        return False
    return bool(ENG_TAG_RE.match(text))


def parse_article(category_label: str, html: str) -> Dict[Tuple[str, str], Dict[str, str]]:
    m = POST_CONTENT_RE.search(html)
    if not m:
        return {}
    body = m.group(1)

    heads = []
    for hm in HEADING_RE.finditer(body):
        level = int(hm.group(1))
        text = _strip_html(hm.group(2))
        heads.append((level, text, hm.start(), hm.end()))

    if not heads:
        # The article may have a single big table without headings — fall back
        # to treating the whole body as one group named after the article.
        heads = [(2, category_label, 0, 0)]

    head_positions = [
        (h[0], h[1], h[3], heads[i + 1][2] if i + 1 < len(heads) else len(body))
        for i, h in enumerate(heads)
    ]

    out: Dict[Tuple[str, str], Dict[str, str]] = {}
    current_h2: Optional[str] = None
    current_h3: Optional[str] = None

    for level, text, start, end in head_positions:
        text_clean = text.strip()
        if any(frag in text_clean for frag in SKIP_HEADINGS):
            current_h2 = current_h3 = None
            continue
        if level == 2:
            current_h2 = text_clean
            current_h3 = None
        elif level == 3:
            current_h3 = GROUP_COUNT_SUFFIX.sub("", text_clean).strip() or text_clean
        elif level == 4:
            # treat h4 as deepest group as well
            current_h3 = GROUP_COUNT_SUFFIX.sub("", text_clean).strip() or text_clean

        cat_name = current_h2 or category_label
        group_name = current_h3 or current_h2 or category_label

        chunk = body[start:end]

        # 1) Cyber-rich-table (camera-angle-prompt, etc.) — extracted first to
        #    avoid double-parsing via generic table regex.
        cyber_tables = list(CYBER_TABLE_RE.finditer(chunk))
        chunk_for_generic = chunk
        for cyber in cyber_tables:
            t = cyber.group(0)
            for row in CYBER_MAIN_ROW_RE.findall(t):
                tag_m = TAG_CODE_RE.search(row)
                jp_m = ALIAS_MAIN_RE.search(row)
                if not tag_m or not jp_m:
                    continue
                en = _clean_en(_strip_html(tag_m.group(1)))
                jp = _clean_jp(_strip_html(jp_m.group(1)))
                if not _is_useful_english(en) or not jp:
                    continue
                key = (cat_name, group_name)
                tags = out.setdefault(key, {})
                tags.setdefault(en, jp)
            # remove this table from the chunk so generic parser skips it
            chunk_for_generic = chunk_for_generic.replace(t, "")

        # 2) Generic ``<table>`` with two-or-three column layout.
        for table in TABLE_RE.findall(chunk_for_generic):
            rows = TR_RE.findall(table)
            for row in rows:
                cells = TD_RE.findall(row)
                if len(cells) < 2:
                    continue
                jp = _clean_jp(_strip_html(cells[0]))
                if not jp or jp in ("内容", "日本語", "プロンプト", "タグ", "ひとこと解説"):
                    continue
                en_lines = _cell_to_lines(cells[1])
                if not en_lines:
                    continue
                key = (cat_name, group_name)
                tags = out.setdefault(key, {})
                for raw_en in en_lines:
                    en = _clean_en(raw_en)
                    if not _is_useful_english(en):
                        continue
                    tags.setdefault(en, jp)
    return out


def build_yaml(
    all_results: Dict[str, Dict[Tuple[str, str], Dict[str, str]]],
) -> List[Dict]:
    """Build YAML hierarchy: section → article-category → group → tags."""
    section = {"name": SECTION_NAME, "categories": []}
    for cat_label in all_results:
        sections = all_results[cat_label]
        if not sections:
            continue
        cat_obj = {"name": cat_label, "groups": []}
        # Flatten internal (h2, h3) into deterministic group ordering.
        for (h2, h3), tags in sections.items():
            if not tags:
                continue
            group_name = h3 if h3 == h2 else f"{h2}｜{h3}" if h2 and h3 else (h2 or h3 or "一覧")
            cat_obj["groups"].append(
                {
                    "name": group_name,
                    "tags": dict(sorted(tags.items(), key=lambda kv: kv[0].lower())),
                }
            )
        if cat_obj["groups"]:
            section["categories"].append(cat_obj)
    return [section]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force-fetch", action="store_true")
    parser.add_argument(
        "--out",
        default=os.path.join(_SCRIPT_DIR, "..", "group_tags", "metacamp.yaml"),
    )
    args = parser.parse_args()

    all_results: Dict[str, Dict[Tuple[str, str], Dict[str, str]]] = {}
    grand_total = 0
    for cat_label, slug in ARTICLES:
        url = f"{BASE}/{slug}/"
        print(f"[metacamp] {cat_label}: {url}")
        try:
            html = fetch_url(url, cache_name=f"{slug}.html", force=args.force_fetch)
        except Exception as e:
            print(f"  [error] fetch failed: {e}")
            continue
        result = parse_article(cat_label, html)
        n_pairs = sum(len(v) for v in result.values())
        print(f"  parsed: {len(result)} sections | {n_pairs} pairs")
        grand_total += n_pairs
        all_results[cat_label] = result

    print(f"[metacamp] grand total pairs: {grand_total}")

    data = build_yaml(all_results)
    out_path = os.path.abspath(args.out)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(
            data,
            f,
            allow_unicode=True,
            sort_keys=False,
            default_flow_style=False,
            width=120,
        )
    print(f"[metacamp] wrote: {out_path}")


if __name__ == "__main__":
    main()
