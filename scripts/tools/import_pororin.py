#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""Import the pororingames.com NSFW-prompt article into a YAML dictionary.

The source page uses a WordPress (SWELL) layout with ``<h2>`` categories,
``<h3>`` sub-groups, and HTML tables with two columns ``内容 / プロンプト``.
Cells may contain multiple english prompts separated by ``<br>``; each line
becomes its own tag and shares the Japanese label of the row.

Article: https://pororingames.com/stable-diffusion-adult-prompt/

Output:
    extensions/sd-prompt-composer/group_tags/pororin.yaml
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

USER_AGENT = "Mozilla/5.0 (compatible; PromptComposerImporter/1.0; pororin)"
DEFAULT_URL = "https://pororingames.com/stable-diffusion-adult-prompt/"
SECTION_NAME = "ぽろりんげーむず NSFW (pororingames.com)"

POST_CONTENT_RE = re.compile(
    r'class="(?:entry-content|post_content)[^"]*"[^>]*>([\s\S]+?)(?=<footer|class="article_footer|class="post-end)',
    re.IGNORECASE,
)
HEADING_RE = re.compile(r"<h([234])[^>]*>([\s\S]*?)</h\1>", re.IGNORECASE)
TABLE_RE = re.compile(r"<table[\s\S]*?</table>", re.IGNORECASE)
TR_RE = re.compile(r"<tr[^>]*>([\s\S]*?)</tr>", re.IGNORECASE)
TD_RE = re.compile(r"<t[dh][^>]*>([\s\S]*?)</t[dh]>", re.IGNORECASE)
TAG_STRIP_RE = re.compile(r"<[^>]+>")

ENG_TAG_RE = re.compile(r"^[a-zA-Z0-9 _\-,'\.!?()/:]+$")

SKIP_H2 = {"関連記事", "コメント", "コメント一覧", "目次"}
SKIP_HEADING_FRAGMENTS = ("コメント", "目次", "関連記事", "あわせて読みたい")


def fetch_url(url: str, timeout: int = 60) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


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
    if not text or len(text) > 100:
        return False
    if "○" in text:
        return False
    if "<" in text and ">" in text:
        # placeholder template like ``<セックス全般プロンプト>``
        return False
    return bool(ENG_TAG_RE.match(text))


def parse_article(html: str) -> Dict[Tuple[str, str], Dict[str, str]]:
    m = POST_CONTENT_RE.search(html)
    if not m:
        return {}
    body = m.group(1)

    # Walk headings to determine current (h2 category, h3 group).
    heads = []
    for hm in HEADING_RE.finditer(body):
        level = int(hm.group(1))
        text = _strip_html(hm.group(2))
        heads.append((level, text, hm.start(), hm.end()))

    current_cat: Optional[str] = None
    current_grp: Optional[str] = None
    out: Dict[Tuple[str, str], Dict[str, str]] = {}

    # For each h-region (from heading end → next heading start), parse tables
    # found within that region.
    head_positions = [(h[0], h[1], h[3], heads[i + 1][2] if i + 1 < len(heads) else len(body)) for i, h in enumerate(heads)]

    for level, text, start, end in head_positions:
        text_clean = text.strip()
        if any(frag in text_clean for frag in SKIP_HEADING_FRAGMENTS):
            current_cat = current_grp = None
            continue
        if level == 2:
            if text_clean in SKIP_H2:
                current_cat = current_grp = None
                continue
            current_cat = text_clean
            current_grp = None
        elif level == 3:
            current_grp = text_clean

        if not current_cat:
            continue

        chunk = body[start:end]
        for table in TABLE_RE.findall(chunk):
            rows = TR_RE.findall(table)
            for row in rows:
                cells = TD_RE.findall(row)
                if len(cells) < 2:
                    continue
                jp = _clean_jp(_strip_html(cells[0]))
                if not jp or jp in ("内容", "日本語", "プロンプト", "タグ"):
                    continue
                lines = _cell_to_lines(cells[1])
                for raw_en in lines:
                    en = _clean_en(raw_en)
                    if not _is_useful_english(en):
                        continue
                    grp = current_grp or current_cat
                    key = (current_cat, grp)
                    tags = out.setdefault(key, {})
                    tags.setdefault(en, jp)
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
    parser.add_argument("--input", help="Local HTML file to parse")
    parser.add_argument(
        "--out",
        default=os.path.join(_SCRIPT_DIR, "..", "group_tags", "pororin.yaml"),
    )
    parser.add_argument("--cache-dir", default="/tmp/pc-tag-import/pororin")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    if args.input:
        with open(args.input, encoding="utf-8") as f:
            html = f.read()
    else:
        os.makedirs(args.cache_dir, exist_ok=True)
        cache_path = os.path.join(args.cache_dir, "index.html")
        if args.force or not os.path.isfile(cache_path):
            html = fetch_url(args.url)
            with open(cache_path, "w", encoding="utf-8") as f:
                f.write(html)
            time.sleep(0.5)
        else:
            with open(cache_path, encoding="utf-8") as f:
                html = f.read()

    sections = parse_article(html)
    total = sum(len(v) for v in sections.values())
    print(f"[pororin] parsed sections: {len(sections)} | unique pairs: {total}")
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
    print(f"[pororin] wrote: {out_path}")


if __name__ == "__main__":
    main()
