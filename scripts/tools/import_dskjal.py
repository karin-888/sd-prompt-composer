#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""Import dskjal.com 'frequently searched words' (R-18 含む) into a YAML dictionary.

The source is a long markdown article that lists Japanese ↔ Danbooru-tag
mappings organized by ``## <category>`` and (optionally) ``#### <sub-group>``
headings, followed by markdown tables of ``| 日本語 | タグ |`` where the tag
column contains one or more ``[english_tag](danbooru_url)`` markdown links.

Single Japanese label may map to several English tags (comma separated).
We split each into its own tag, but they all share the same Japanese label.

Usage:
    python import_dskjal.py [--input <markdown>] [--url <url>]

Output:
    extensions/sd-prompt-composer/group_tags/dskjal.yaml
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import time
import urllib.request
from typing import Dict, List, Optional, Tuple

import yaml

_TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
_SCRIPT_DIR = os.path.dirname(_TOOLS_DIR)
for _p in (_SCRIPT_DIR, _TOOLS_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

USER_AGENT = "Mozilla/5.0 (compatible; PromptComposerImporter/1.0; dskjal)"
DEFAULT_URL = "https://dskjal.com/deeplearning/frequently-searched-words"
SECTION_NAME = "よく検索されているプロンプト (dskjal.com)"

H2_RE = re.compile(r"^##\s+(?P<title>.+?)\s*$")
H4_RE = re.compile(r"^####\s+(?P<title>.+?)\s*$")
TABLE_ROW_RE = re.compile(r"^\|\s*(?P<jp>[^|]*?)\s*\|\s*(?P<en>[^|]*?)\s*\|\s*$")
LINK_RE = re.compile(r"\[(?P<name>[^\]]+)\]\((?P<url>[^)]+)\)")
TABLE_SEP_RE = re.compile(r"^\|[\s:\-|]+\|\s*$")

ENG_TAG_RE = re.compile(r"^[a-zA-Z0-9 _\-,'\.!?()/]+$")

# Sections that are pure tables of contents or how-to-use prose, not prompts.
TOC_SECTIONS = {
    "このページの使い方",
    "NSFW",
    "一般タグ",
}


def fetch_url(url: str, timeout: int = 60) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def _clean_jp(text: str) -> str:
    text = text.strip()
    text = re.sub(r"\s+", " ", text)
    return text


def _clean_en(text: str) -> str:
    text = text.strip().strip("`")
    text = text.replace("\u2018", "'").replace("\u2019", "'")
    text = re.sub(r"\s+", " ", text)
    text = text.strip(",.;:!?")
    return text


def _is_useful_english(text: str) -> bool:
    if not text or len(text) > 100:
        return False
    return bool(ENG_TAG_RE.match(text))


def _extract_english_tags(cell: str) -> List[str]:
    """Pull english tags from a markdown table cell that may contain
    multiple markdown links interleaved with Japanese prose."""
    tags: List[str] = []
    seen = set()
    for m in LINK_RE.finditer(cell):
        name = _clean_en(m.group("name"))
        if not _is_useful_english(name):
            continue
        low = name.lower()
        if low in seen:
            continue
        seen.add(low)
        tags.append(name)
    return tags


def parse_markdown(text: str) -> Dict[Tuple[str, str], Dict[str, str]]:
    """Return ordered { (category, group): {english_tag: japanese} }.

    ``group`` is the most recent ``#### <name>`` heading; if none exists since
    the category started, the group equals the category name.
    """
    out: Dict[Tuple[str, str], Dict[str, str]] = {}
    current_cat: Optional[str] = None
    current_group: Optional[str] = None

    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        m2 = H2_RE.match(line)
        if m2:
            title = m2.group("title").strip()
            if title in TOC_SECTIONS:
                current_cat = None
                current_group = None
            else:
                current_cat = title
                current_group = None  # reset
            i += 1
            continue
        m4 = H4_RE.match(line)
        if m4:
            current_group = m4.group("title").strip()
            i += 1
            continue
        if not current_cat:
            i += 1
            continue
        # parse table rows
        if line.startswith("|") and TABLE_ROW_RE.match(line):
            # Skip header line if present (jp/タグ literal)
            # We rely on _extract_english_tags returning empty for the header.
            cells = TABLE_ROW_RE.match(line)
            jp_cell = cells.group("jp")
            en_cell = cells.group("en")
            # Skip rows that look like the markdown table separator (|---|---|)
            if TABLE_SEP_RE.match(line):
                i += 1
                continue
            jp = _clean_jp(jp_cell)
            if not jp or jp in ("日本語", "タグ", "プロンプト"):
                i += 1
                continue
            tags = _extract_english_tags(en_cell)
            if not tags:
                i += 1
                continue
            key = (current_cat, current_group or current_cat)
            group_map = out.setdefault(key, {})
            for tag in tags:
                if tag.lower() not in group_map:
                    group_map[tag] = jp
        i += 1

    return out


def build_yaml(sections: Dict[Tuple[str, str], Dict[str, str]]) -> List[Dict]:
    categories: Dict[str, Dict] = {}
    for (cat, grp), tags in sections.items():
        if not tags:
            continue
        cat_obj = categories.setdefault(cat, {"name": cat, "_groups": {}})
        existing = cat_obj["_groups"].setdefault(grp, {})
        for k, v in tags.items():
            existing.setdefault(k, v)

    section = {"name": SECTION_NAME, "categories": []}
    for cat_name in categories:
        cat = categories[cat_name]
        cat_obj = {"name": cat_name, "groups": []}
        for group_name, tags in cat["_groups"].items():
            cat_obj["groups"].append(
                {
                    "name": group_name,
                    "tags": dict(sorted(tags.items(), key=lambda kv: kv[0].lower())),
                }
            )
        section["categories"].append(cat_obj)
    return [section]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--input", help="Local markdown file to parse instead of fetching")
    parser.add_argument(
        "--out",
        default=os.path.join(_SCRIPT_DIR, "..", "group_tags", "dskjal.yaml"),
    )
    parser.add_argument("--cache-dir", default="/tmp/pc-tag-import/dskjal")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    if args.input:
        with open(args.input, encoding="utf-8") as f:
            text = f.read()
    else:
        os.makedirs(args.cache_dir, exist_ok=True)
        cache_path = os.path.join(args.cache_dir, "page.html")
        if args.force or not os.path.isfile(cache_path):
            text = fetch_url(args.url)
            with open(cache_path, "w", encoding="utf-8") as f:
                f.write(text)
            time.sleep(0.5)
        else:
            with open(cache_path, encoding="utf-8") as f:
                text = f.read()

    sections = parse_markdown(text)
    total_tags = sum(len(v) for v in sections.values())
    print(f"[dskjal] parsed sections: {len(sections)} | unique pairs: {total_tags}")
    by_cat: Dict[str, int] = {}
    for (cat, _), tags in sections.items():
        by_cat[cat] = by_cat.get(cat, 0) + len(tags)
    for cat, n in by_cat.items():
        print(f"  - {cat}: {n}")

    data = build_yaml(sections)
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
    print(f"[dskjal] wrote: {out_path}")


if __name__ == "__main__":
    main()
