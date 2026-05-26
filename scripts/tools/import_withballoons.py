#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""Import withballoons.jp Stable Diffusion prompt articles into a YAML dictionary.

Each article hosts one large HTML ``<table>`` with four columns:
``区分 / 項目 / 表現内容 / プロンプト``. We use ``項目`` as the group name,
``表現内容`` as the Japanese label, and ``プロンプト`` as the English tag.

Output:
    extensions/sd-prompt-composer/group_tags/withballoons.yaml
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

USER_AGENT = "Mozilla/5.0 (compatible; PromptComposerImporter/1.0; withballoons)"
BASE = "https://withballoons.jp"
SECTION_NAME = "with balloons Stable Diffusion (withballoons.jp)"
CACHE_DIR = "/tmp/pc-tag-import/withballoons"
REQUEST_DELAY = 0.4

# (display_category, article_slug)
ARTICLES: List[Tuple[str, str]] = [
    ("NSFW呪文", "stable-diffusion-ero-prompt"),
    ("シチュエーション", "stable-diffusion-situation-prompt"),
    ("表情", "stable-diffusion-hyojyo-prompt02"),
    ("髪型(リアル)", "stable-diffusion-hair-prompt_real"),
    ("衣装", "stable-diffusion-isyou-prompt"),
    ("髪型(イラスト)", "stable-diffusion-hair-prompt_anime"),
]

TABLE_RE = re.compile(r"<table[\s\S]*?</table>", re.IGNORECASE)
TR_RE = re.compile(r"<tr[^>]*>([\s\S]*?)</tr>", re.IGNORECASE)
TD_RE = re.compile(r"<t[dh][^>]*>([\s\S]*?)</t[dh]>", re.IGNORECASE)
TAG_STRIP_RE = re.compile(r"<[^>]+>")

ENG_TAG_RE = re.compile(r"^[a-zA-Z0-9 _\-,'\.!?()/:]+$")


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


def parse_article(category_label: str, html: str) -> Dict[str, Dict[str, str]]:
    """Pick the largest table; treat rows as (区分, 項目, 表現内容, プロンプト)."""
    out: Dict[str, Dict[str, str]] = {}
    tables = TABLE_RE.findall(html)
    if not tables:
        return out
    # The biggest table is the prompt list.
    target = max(tables, key=len)
    rows = TR_RE.findall(target)
    # Determine column order from header if present.
    header_seen = False
    col_idx = {"item": 1, "jp": 2, "en": 3}
    for row in rows:
        cells = TD_RE.findall(row)
        if not cells:
            continue
        text_cells = [_strip_html(c) for c in cells]
        if not header_seen and any(h in text_cells for h in ("プロンプト", "項目", "表現内容")):
            for i, val in enumerate(text_cells):
                v = val.strip()
                if v in ("項目",):
                    col_idx["item"] = i
                elif v in ("表現内容",):
                    col_idx["jp"] = i
                elif v in ("プロンプト", "呪文"):
                    col_idx["en"] = i
            header_seen = True
            continue
        if len(cells) <= max(col_idx.values()):
            continue
        item = _clean_jp(text_cells[col_idx["item"]])
        jp = _clean_jp(text_cells[col_idx["jp"]])
        en_lines = _cell_to_lines(cells[col_idx["en"]])
        if not jp or not en_lines:
            continue
        group = item or category_label
        tags = out.setdefault(group, {})
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
        for group_name, tags in groups.items():
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
    parser.add_argument(
        "--out",
        default=os.path.join(_SCRIPT_DIR, "..", "group_tags", "withballoons.yaml"),
    )
    args = parser.parse_args()

    all_results: List[Tuple[str, Dict[str, Dict[str, str]]]] = []
    grand_total = 0
    for cat_label, slug in ARTICLES:
        url = f"{BASE}/{slug}/"
        cache = f"a-{slug}.html"
        print(f"[withballoons] {cat_label}: {url}")
        try:
            html = fetch_url(url, cache_name=cache, force=args.force_fetch)
        except Exception as e:
            print(f"  [error] fetch failed: {e}")
            continue
        groups = parse_article(cat_label, html)
        n = sum(len(v) for v in groups.values())
        print(f"  groups={len(groups)} pairs={n}")
        grand_total += n
        all_results.append((cat_label, groups))

    print(f"[withballoons] total pairs: {grand_total}")
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
    print(f"[withballoons] wrote: {out_path}")


if __name__ == "__main__":
    main()
