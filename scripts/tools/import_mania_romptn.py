#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""Import the Mania AI (mania.romptn.com) prompt-list article into a YAML tag dictionary.

The source uses a clean structure: ``## <category>`` followed by markdown tables
with columns ``No | English Keyword | 日本語訳``.  Some entries have multiple
English keywords separated by ``/`` and JP labels separated by ``/`` — both are
expanded into individual tag pairs.

Default source article:
    https://mania.romptn.com/article/image-generation/5218/

Output:
    extensions/sd-prompt-composer/group_tags/mania_romptn.yaml
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from typing import Dict, List, Optional, Tuple

import yaml

_TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
_SCRIPT_DIR = os.path.dirname(_TOOLS_DIR)
for _p in (_SCRIPT_DIR, _TOOLS_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

USER_AGENT = "Mozilla/5.0 (compatible; PromptComposerImporter/1.0)"
DEFAULT_URL = "https://mania.romptn.com/article/image-generation/5218/"
DEFAULT_TITLE = "エロ系プロンプト一覧 (mania.romptn.com)"

H2_RE = re.compile(r"^##\s+(?P<title>.+?)\s*$")
H3_RE = re.compile(r"^###\s+(?P<title>.+?)\s*$")
TABLE_ROW_RE = re.compile(r"^\|\s*(?P<n>[^|]*?)\s*\|\s*(?P<en>[^|]*?)\s*\|\s*(?P<jp>[^|]*?)\s*\|\s*$")
TABLE_SEP_RE = re.compile(r"^\|\s*-+[\s|:-]*\|\s*$")

ENG_TAG_RE = re.compile(r"^[a-zA-Z0-9 _\-,'/.!?]+$")

# Categories that aren't real prompt sections in the source article.
SKIP_CATEGORIES = {
    "関連記事",
    "人気記事",
    "新着記事",
    "目次",
    "プロフィール",
    "Mania AI",
}


def fetch_url(url: str, timeout: int = 60) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def normalize_english(text: str) -> str:
    text = text.strip().strip("`").strip()
    text = re.sub(r"\s+", " ", text)
    return text


def normalize_jp(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^[\-•\u2022\s]+", "", text)
    text = re.sub(r"\s+", " ", text)
    return text


def split_alts(text: str, separator: str = "/") -> List[str]:
    parts = [p.strip() for p in text.split(separator) if p.strip()]
    return parts


def is_valid_english(text: str) -> bool:
    if not text or len(text) > 80:
        return False
    if text.lower().startswith(("english keyword", "no.")):
        return False
    if text in ("---", ""):
        return False
    return bool(ENG_TAG_RE.match(text))


def parse_markdown(text: str) -> Dict[str, Dict[str, str]]:
    """Return ordered {category: {english_tag: japanese}}."""
    sections: Dict[str, Dict[str, str]] = {}
    current_section: Optional[str] = None

    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        if not line:
            continue
        m = H2_RE.match(line)
        if m:
            title = m.group("title").strip().rstrip(":：").strip()
            if title in SKIP_CATEGORIES:
                current_section = None
            else:
                current_section = title
                sections.setdefault(current_section, {})
            continue
        if H3_RE.match(line):
            # ignore sub-headings within an active section
            continue
        if not current_section:
            continue
        if TABLE_SEP_RE.match(line):
            continue
        m = TABLE_ROW_RE.match(line)
        if not m:
            continue
        n = m.group("n").strip()
        en_raw = m.group("en").strip()
        jp_raw = m.group("jp").strip()
        # skip header row
        if not n or not n.isdigit():
            continue
        for en in split_alts(en_raw):
            en = normalize_english(en)
            if not is_valid_english(en):
                continue
            jp_parts = split_alts(jp_raw) or [jp_raw]
            jp_value = normalize_jp(jp_parts[0]) if jp_parts else en
            if not jp_value:
                jp_value = en
            sections[current_section][en] = jp_value
    return sections


def build_yaml(sections: Dict[str, Dict[str, str]], title: str, source_url: str) -> List[Dict]:
    cats: List[Dict] = []
    for cat_name, tags in sections.items():
        if not tags:
            continue
        sorted_tags = dict(sorted(tags.items(), key=lambda kv: kv[0].lower()))
        cats.append(
            {
                "name": cat_name,
                "groups": [{"name": "一覧", "tags": sorted_tags}],
            }
        )
    return [{"name": title, "categories": cats}]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--title", default=DEFAULT_TITLE)
    parser.add_argument(
        "--input",
        help="Local markdown/HTML file to parse instead of fetching the URL",
    )
    parser.add_argument(
        "--out",
        default=os.path.join(_SCRIPT_DIR, "..", "group_tags", "mania_romptn.yaml"),
    )
    parser.add_argument("--cache-dir", default="/tmp/pc-tag-import/mania-romptn")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    if args.input:
        with open(args.input, encoding="utf-8") as f:
            text = f.read()
    else:
        os.makedirs(args.cache_dir, exist_ok=True)
        slug = re.sub(r"\W+", "_", args.url)[-80:]
        cache_path = os.path.join(args.cache_dir, slug + ".md")
        if not args.force and os.path.isfile(cache_path):
            with open(cache_path, encoding="utf-8") as f:
                text = f.read()
        else:
            html = fetch_url(args.url)
            text = html  # let parser tolerate html too via markdown patterns
            with open(cache_path, "w", encoding="utf-8") as f:
                f.write(text)
            time.sleep(0.5)

    sections = parse_markdown(text)
    total = sum(len(v) for v in sections.values())
    print(f"[mania-romptn] parsed: {len(sections)} sections, {total} entries")
    for cat_name, tags in sections.items():
        print(f"  - {cat_name}: {len(tags)} tags")

    data = build_yaml(sections, title=args.title, source_url=args.url)
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
    print(f"[mania-romptn] wrote: {out_path}")


if __name__ == "__main__":
    main()
