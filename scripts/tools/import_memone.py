#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""Import memone-ro.com (AI生成メモネーロ) prompt dictionary into a YAML file.

The site's TOP page contains a table of links to ~100 prompt articles. Each
article is structured as ``<h2>section name</h2>`` followed by a clean
3-column ``<table>`` (``日本語 | 単語 | 説明``). Some pages may use 2 columns.

The crawler:
  1. Fetches the TOP page to harvest {article_url: article_label} pairs.
  2. Fetches each article (cached) and parses its h2 sections + tables.
  3. Uses the TOP-page label as the YAML category name; uses the article's
     own ``<h2>`` titles as group names within that category.

Output:
    extensions/sd-prompt-composer/group_tags/memone.yaml
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

USER_AGENT = "Mozilla/5.0 (compatible; PromptComposerImporter/1.0; memone)"
BASE = "https://memone-ro.com"
SECTION_NAME = "AI生成メモネーロ (memone-ro.com)"
CACHE_DIR = "/tmp/pc-tag-import/memone"
REQUEST_DELAY = 0.35

HEADING_RE = re.compile(r"<h([234])[^>]*>([\s\S]*?)</h\1>", re.IGNORECASE)
TABLE_RE = re.compile(r"<table[\s\S]*?</table>", re.IGNORECASE)
TR_RE = re.compile(r"<tr[^>]*>([\s\S]*?)</tr>", re.IGNORECASE)
TD_RE = re.compile(r"<t[dh][^>]*>([\s\S]*?)</t[dh]>", re.IGNORECASE)
TAG_STRIP_RE = re.compile(r"<[^>]+>")

ENG_TAG_RE = re.compile(r"^[a-zA-Z0-9 _\-,'\.!?()/:]+$")

ARTICLE_LINK_RE = re.compile(
    r'<a\s+href="(https://memone-ro\.com/archives/\d+)"[^>]*>([^<]+)</a>',
    re.IGNORECASE,
)
CONTENT_RE = re.compile(
    r'class="entry-content[^"]*"[^>]*>([\s\S]+?)(?=<div[^>]+class="(?:under-entry-content|sns-share|p-related|related-posts))',
    re.IGNORECASE,
)
SKIP_HEADING_FRAGMENTS = (
    "コメント",
    "目次",
    "関連記事",
    "あわせて読みたい",
    "プロフィール",
    "シェア",
    "サイトのお知らせ",
)


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
    return bool(ENG_TAG_RE.match(text))


def list_articles(force_top: bool = False) -> List[Tuple[str, str]]:
    html = fetch_url(BASE + "/", cache_name="index.html", force=force_top)
    pairs = ARTICLE_LINK_RE.findall(html)
    seen = set()
    out: List[Tuple[str, str]] = []
    for url, label in pairs:
        if url in seen:
            continue
        seen.add(url)
        label = re.sub(r"\s+", " ", label).strip()
        if not label:
            continue
        out.append((url, label))
    return out


def parse_article(category_label: str, html: str) -> Dict[str, Dict[str, str]]:
    """Return {group_name: {english_tag: japanese}} for one article."""
    m = CONTENT_RE.search(html)
    body = m.group(1) if m else html

    heads = list(HEADING_RE.finditer(body))
    head_positions = [
        (int(h.group(1)), _strip_html(h.group(2)), h.end(), heads[i + 1].start() if i + 1 < len(heads) else len(body))
        for i, h in enumerate(heads)
    ]

    out: Dict[str, Dict[str, str]] = {}
    # Default group = article label (for content above the first heading).
    default_group = category_label

    # First, look for tables that appear before the first heading.
    chunks: List[Tuple[str, str]] = []  # (group, chunk_html)
    if heads:
        first_h_start = heads[0].start()
        pre_chunk = body[:first_h_start]
        if pre_chunk:
            chunks.append((default_group, pre_chunk))
        for level, text, start, end in head_positions:
            text_clean = text.strip()
            if any(frag in text_clean for frag in SKIP_HEADING_FRAGMENTS):
                continue
            group_name = text_clean or default_group
            chunks.append((group_name, body[start:end]))
    else:
        chunks.append((default_group, body))

    for group_name, chunk in chunks:
        for table in TABLE_RE.findall(chunk):
            rows = TR_RE.findall(table)
            for row in rows:
                cells = TD_RE.findall(row)
                if len(cells) < 2:
                    continue
                jp = _clean_jp(_strip_html(cells[0]))
                if not jp or jp in ("内容", "日本語", "プロンプト", "タグ", "単語", "意味", "説明"):
                    continue
                en_lines = _cell_to_lines(cells[1])
                if not en_lines:
                    continue
                tags = out.setdefault(group_name, {})
                for raw_en in en_lines:
                    en = _clean_en(raw_en)
                    if not _is_useful_english(en):
                        continue
                    tags.setdefault(en, jp)
    return out


def build_yaml(all_results: List[Tuple[str, Dict[str, Dict[str, str]]]]) -> List[Dict]:
    section = {"name": SECTION_NAME, "categories": []}
    for cat_label, groups in all_results:
        if not groups:
            continue
        cat_obj = {"name": cat_label, "groups": []}
        for group_name in groups:
            tags = groups[group_name]
            if not tags:
                continue
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
    parser.add_argument("--limit", type=int, default=0, help="Only crawl first N articles (debug)")
    parser.add_argument(
        "--out",
        default=os.path.join(_SCRIPT_DIR, "..", "group_tags", "memone.yaml"),
    )
    args = parser.parse_args()

    articles = list_articles(force_top=args.force_fetch)
    if args.limit:
        articles = articles[: args.limit]
    print(f"[memone] articles to crawl: {len(articles)}")

    all_results: List[Tuple[str, Dict[str, Dict[str, str]]]] = []
    grand_total = 0
    for i, (url, label) in enumerate(articles, 1):
        slug = url.rsplit("/", 1)[-1] or url.rsplit("/", 2)[-2]
        cache = f"a-{slug}.html"
        print(f"[{i}/{len(articles)}] {label}: {url}")
        try:
            html = fetch_url(url, cache_name=cache, force=args.force_fetch)
        except Exception as e:
            print(f"  [error] fetch failed: {e}")
            continue
        groups = parse_article(label, html)
        n_pairs = sum(len(v) for v in groups.values())
        print(f"  groups: {len(groups)} | pairs: {n_pairs}")
        grand_total += n_pairs
        all_results.append((label, groups))

    print(f"[memone] grand total pairs: {grand_total}")
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
    print(f"[memone] wrote: {out_path}")


if __name__ == "__main__":
    main()
