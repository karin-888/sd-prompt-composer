#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""Parse "JP → ENG_PROMPT" style Japanese AI prompt dictionaries (note.com etc).

The articles use a recurring shape::

    ## 第N章：<category>
    ### <subsection>
    日本語ラベル → english_prompt, alt_english[, ...]
    ...

This importer downloads the markdown/text rendering of each configured URL via
WebFetch-style HTTP, parses the headings and arrow lines, and writes the result
into ``group_tags/jp_blogs.yaml``.
"""

from __future__ import annotations

import argparse
import html
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
REQUEST_DELAY = 1.0

# Articles to import. Each tuple: (label, url).
ARTICLES = [
    (
        "AI美女プロンプト辞典 (note.com/ai_image_goat)",
        "https://note.com/ai_image_goat/n/nea2d6788ed48",
    ),
    (
        "画像生成プロンプト一覧 (note.com/uzuki_create)",
        "https://note.com/uzuki_create/n/n78809d32624f",
    ),
    (
        "Illustriousタグ集543選 (note.com/kana48nft)",
        "https://note.com/kana48nft/n/n871623f726d5",
    ),
]

ARROW_RE = re.compile(r"^(?P<jp>[^→]{1,60}?)\s*→\s*(?P<en>[^（()]+?)(?:\s*[（(](?P<memo>[^)）]*)[)）])?\s*$")
H2_RE = re.compile(r"^##\s+(?P<title>.+?)\s*$")
H3_RE = re.compile(r"^###\s+(?P<title>.+?)\s*$")
H1_RE = re.compile(r"^#\s+(?P<title>.+?)\s*$")

ENG_TAG_RE = re.compile(r"^[a-zA-Z0-9 _\-,'/.!?:]+$")


def fetch_url(url: str, timeout: int = 60) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
    text = raw.decode("utf-8", errors="replace")
    return text


_HTML_RE = re.compile(r"<[^>]+>")
_BR_RE = re.compile(r"<br\s*/?>", re.IGNORECASE)
_BLOCK_END_RE = re.compile(r"</(?:p|li|div|tr|td|h[1-6])\s*>", re.IGNORECASE)
_HEADER_RE = re.compile(r"<h([1-3])[^>]*>([\s\S]*?)</h\1>", re.IGNORECASE)
_NOTE_BODY_RE = re.compile(
    r'<div[^>]+class="[^"]*note-common-styles__textnote-body[^"]*"[^>]*>([\s\S]+?)(?:</article>|<footer)',
    re.IGNORECASE,
)


def html_to_markdown(html_text: str) -> str:
    body_match = _NOTE_BODY_RE.search(html_text)
    body = body_match.group(1) if body_match else html_text

    def header_repl(match: re.Match) -> str:
        level = int(match.group(1))
        text = _HTML_RE.sub("", match.group(2))
        text = html.unescape(text)
        prefix = "#" * level
        return f"\n{prefix} {text.strip()}\n"

    body = _HEADER_RE.sub(header_repl, body)
    body = _BR_RE.sub("\n", body)
    body = _BLOCK_END_RE.sub("\n", body)
    body = _HTML_RE.sub("", body)
    body = html.unescape(body)
    body = re.sub(r"[ \t]+", " ", body)
    body = re.sub(r"\n{3,}", "\n\n", body)
    return body.strip()


def looks_like_english_prompt(text: str) -> bool:
    text = text.strip()
    if not text or len(text) > 200:
        return False
    return bool(ENG_TAG_RE.match(text))


def clean_jp(jp: str) -> str:
    jp = jp.strip().strip("：:・　").strip()
    jp = re.sub(r"^\d+[\.．、）)\s]+", "", jp)  # leading list numbers
    jp = re.sub(r"\s+", " ", jp)
    return jp


def split_english(en: str) -> List[str]:
    parts = [p.strip() for p in re.split(r"[、,]", en) if p.strip()]
    out: List[str] = []
    seen = set()
    for p in parts:
        if not looks_like_english_prompt(p):
            continue
        key = p.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(p)
    return out


def parse_article(label: str, text: str) -> List[Tuple[str, str, str, str]]:
    """Return list of (category, group, jp, en_prompt) entries."""
    out: List[Tuple[str, str, str, str]] = []
    category = ""
    group = ""
    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        if not line:
            continue
        if m := H1_RE.match(line):
            continue
        if m := H2_RE.match(line):
            title = m.group("title").strip()
            if title.startswith("第") or "プロンプト" in title or "章" in title:
                category = title
                group = ""
            else:
                category = title
                group = ""
            continue
        if m := H3_RE.match(line):
            group = m.group("title").strip()
            continue
        if "→" not in line:
            continue
        # truncate trailing memo "（注釈）" but keep the arrow split
        m = ARROW_RE.match(line)
        if not m:
            # try a looser parse
            parts = line.split("→", 1)
            jp_part = parts[0].strip()
            en_part = parts[1].strip() if len(parts) > 1 else ""
        else:
            jp_part = m.group("jp")
            en_part = m.group("en")
        jp_clean = clean_jp(jp_part)
        if not jp_clean:
            continue
        for en in split_english(en_part):
            out.append((category, group, jp_clean, en))
    return out


def build_yaml(article_label: str, entries: List[Tuple[str, str, str, str]]) -> Optional[Dict]:
    if not entries:
        return None
    categories: Dict[str, Dict] = {}
    for cat, group, jp, en in entries:
        cat_key = cat or "未分類"
        grp_key = group or "一覧"
        c = categories.setdefault(cat_key, {"name": cat_key, "_groups": {}})
        g = c["_groups"].setdefault(grp_key, {"name": grp_key, "tags": {}})
        en_key = en.strip()
        if not en_key:
            continue
        existing = g["tags"].get(en_key)
        if existing and existing != en_key:
            continue  # keep first JP
        g["tags"][en_key] = jp

    cats_out: List[Dict] = []
    for cat in categories.values():
        groups = []
        for g in cat["_groups"].values():
            g["tags"] = dict(sorted(g["tags"].items(), key=lambda kv: kv[0].lower()))
            groups.append(g)
        cats_out.append({"name": cat["name"], "groups": groups})
    return {"name": article_label, "categories": cats_out}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=os.path.join(_SCRIPT_DIR, "..", "group_tags", "jp_blogs.yaml"))
    parser.add_argument(
        "--cache-dir",
        default="/tmp/pc-tag-import/jp-blogs",
        help="Local cache directory for downloaded HTML",
    )
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    os.makedirs(args.cache_dir, exist_ok=True)

    sections: List[Dict] = []
    for label, url in ARTICLES:
        slug = re.sub(r"\W+", "_", url)[-80:]
        cache_path = os.path.join(args.cache_dir, slug + ".html")
        if args.force or not os.path.isfile(cache_path):
            try:
                html_text = fetch_url(url)
                with open(cache_path, "w", encoding="utf-8") as f:
                    f.write(html_text)
                time.sleep(REQUEST_DELAY)
            except Exception as e:
                print(f"[jp-blogs] fetch failed: {url} ({e})")
                continue
        with open(cache_path, encoding="utf-8") as f:
            html_text = f.read()
        text = html_to_markdown(html_text)
        entries = parse_article(label, text)
        print(f"[jp-blogs] {label}: {len(entries)} entries")
        section = build_yaml(label, entries)
        if section:
            sections.append(section)

    if not sections:
        print("[jp-blogs] no entries collected; aborting")
        return

    total = 0
    for s in sections:
        for c in s.get("categories") or []:
            for g in c.get("groups") or []:
                total += len(g.get("tags") or {})
    print(f"[jp-blogs] total tags: {total}")

    out_path = os.path.abspath(args.out)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(
            sections,
            f,
            allow_unicode=True,
            sort_keys=False,
            default_flow_style=False,
            width=120,
        )
    print(f"[jp-blogs] wrote: {out_path}")


if __name__ == "__main__":
    main()
