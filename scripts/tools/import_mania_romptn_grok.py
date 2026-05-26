#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""Crawl the Grok hub article on mania.romptn.com and its linked sub-articles.

The hub article (article/grok/4977/) is a directory of prompt-collection pages.
Each linked sub-article uses HTML tables with a Japanese column and an English
column (with optional "ひとこと解説" / "効果" / etc.). The column order can
be either ``日本語 | プロンプト`` or ``プロンプト | 効果``; the parser figures
this out from the header row.

Outputs:
    extensions/sd-prompt-composer/group_tags/mania_romptn_grok.yaml
    Preview images saved into the standard tag-previews directory.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from html import unescape
from typing import Dict, List, Optional, Tuple

import yaml

_TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
_SCRIPT_DIR = os.path.dirname(_TOOLS_DIR)
for _p in (_SCRIPT_DIR, _TOOLS_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import user_storage
import preview_filenames
import preview_convert

USER_AGENT = "Mozilla/5.0 (compatible; PromptComposerImporter/1.0; mania-romptn)"
BASE = "https://mania.romptn.com"
HUB_URL = f"{BASE}/article/grok/4977/"
SECTION_NAME = "Grokエロプロンプト集 (mania.romptn.com)"
CACHE_DIR = "/tmp/pc-tag-import/mania-romptn"
REQUEST_DELAY = 0.35

POST_CONTENT_RE = re.compile(
    r'class="(?:entry-content|post_content|article-body|p-postContent|c-postContent)[^"]*"[^>]*>([\s\S]+?)(?=<footer|class="article_footer|class="post-end|<aside)',
    re.IGNORECASE,
)
HEADING_RE = re.compile(r"<h([234])[^>]*>([\s\S]*?)</h\1>", re.IGNORECASE)
TABLE_RE = re.compile(r"<table[\s\S]*?</table>", re.IGNORECASE)
TR_RE = re.compile(r"<tr[^>]*>([\s\S]*?)</tr>", re.IGNORECASE)
TD_RE = re.compile(r"<t[dh][^>]*>([\s\S]*?)</t[dh]>", re.IGNORECASE)
IMG_DATA_SRC_RE = re.compile(r'<img[^>]+data-src="([^"]+)"', re.IGNORECASE)
IMG_SRC_RE = re.compile(r'<img[^>]+\ssrc="([^"]+)"', re.IGNORECASE)
TAG_STRIP_RE = re.compile(r"<[^>]+>")

ENG_TAG_RE = re.compile(r"^[a-zA-Z0-9 _\-,'\.!?()/:]+$")

SUB_ARTICLE_RE = re.compile(
    r'href="(https://mania\.romptn\.com/article/(?:stable-diffusion|grok|uncategorized|image-generation|ai-use-cases|gemini)/\d+/)"',
    re.IGNORECASE,
)

SKIP_HEADING_FRAGMENTS = (
    "コメント",
    "目次",
    "関連記事",
    "あわせて読みたい",
    "人気記事",
    "新着記事",
    "監修者",
    "プロフィール",
    "セミナー",
    "まとめ",
    "おわりに",
    "はじめに",
    "ウェビナー",
)

# Header keywords mapped to the role of the column.
JP_HEADERS = {"日本語", "日本語訳", "内容", "効果", "意味", "見える範囲", "ニュアンス", "表現内容"}
EN_HEADERS = {"プロンプト", "呪文", "English Keyword", "english keyword", "タグ", "プロンプト例"}
DESC_HEADERS = {"ひとこと解説", "解説", "備考", "ポイント", "コツ", "メモ"}


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
    if text.startswith("(") and "weight" in text.lower():
        return False
    if "（" in text or "）" in text:
        # full-width parens often indicate annotation, not a real tag
        return False
    return bool(ENG_TAG_RE.match(text))


def extract_sub_article_urls(hub_html: str) -> List[str]:
    urls: List[str] = []
    seen = set()
    for m in SUB_ARTICLE_RE.finditer(hub_html):
        u = m.group(1)
        if u == HUB_URL or u in seen:
            continue
        # exclude category pages
        if "/category/" in u:
            continue
        seen.add(u)
        urls.append(u)
    return urls


def _classify_headers(cells: List[str]) -> Optional[Dict[str, int]]:
    """Inspect a header row's cells; return mapping {"jp": idx, "en": idx} or None."""
    jp_idx = -1
    en_idx = -1
    for i, val in enumerate(cells):
        v = val.strip()
        if jp_idx == -1 and v in JP_HEADERS:
            jp_idx = i
        if en_idx == -1 and v in EN_HEADERS:
            en_idx = i
    if jp_idx == -1 or en_idx == -1:
        return None
    return {"jp": jp_idx, "en": en_idx}


def _heuristic_pick_columns(rows_text: List[List[str]]) -> Optional[Dict[str, int]]:
    """If no header row, guess which column is English vs JP based on content."""
    if not rows_text:
        return None
    sample = rows_text[: min(5, len(rows_text))]
    if not sample or len(sample[0]) < 2:
        return None
    n_cols = min(len(r) for r in sample)
    scores: List[Tuple[int, int]] = []  # (en_score, idx)
    for c in range(n_cols):
        eng = 0
        for r in sample:
            cell = r[c]
            if cell and ENG_TAG_RE.match(cell.strip()) and re.search(r"[a-zA-Z]", cell):
                eng += 1
        scores.append((eng, c))
    scores.sort(reverse=True)
    if scores[0][0] < 2:
        return None
    en_idx = scores[0][1]
    # JP is the most non-English-looking column with japanese characters
    jp_idx = -1
    best = -1
    for c in range(n_cols):
        if c == en_idx:
            continue
        jp_score = 0
        for r in sample:
            cell = r[c]
            if re.search(r"[ぁ-んァ-ン一-龥]", cell):
                jp_score += 1
        if jp_score > best:
            best = jp_score
            jp_idx = c
    if jp_idx == -1 or best < 1:
        return None
    return {"jp": jp_idx, "en": en_idx}


def parse_article(html: str) -> Tuple[str, Dict[str, Dict[str, Tuple[str, str]]]]:
    """Return (title, {group: {english_tag: (japanese, image_url)}})."""
    title_m = re.search(r"<h1[^>]*>([\s\S]*?)</h1>", html, re.IGNORECASE)
    title = _strip_html(title_m.group(1)) if title_m else ""

    m = POST_CONTENT_RE.search(html)
    body = m.group(1) if m else html

    heads = list(HEADING_RE.finditer(body))
    head_positions = [
        (int(h.group(1)), _strip_html(h.group(2)), h.end(), heads[i + 1].start() if i + 1 < len(heads) else len(body))
        for i, h in enumerate(heads)
    ]

    out: Dict[str, Dict[str, Tuple[str, str]]] = {}
    current_h2: Optional[str] = None
    current_h3: Optional[str] = None
    default_group = title or "一覧"

    # Walk headings sequentially to know which is currently active.
    sections: List[Tuple[str, str, str]] = []  # (group_name, chunk, image_for_group)
    if not heads:
        sections.append((default_group, body, ""))
    else:
        pre_chunk = body[: heads[0].start()]
        if pre_chunk:
            sections.append((default_group, pre_chunk, ""))
        for level, text, start, end in head_positions:
            text_clean = text.strip()
            if any(frag in text_clean for frag in SKIP_HEADING_FRAGMENTS):
                current_h2 = current_h3 = None
                continue
            if level == 2:
                current_h2 = text_clean
                current_h3 = None
            elif level == 3:
                current_h3 = text_clean
            elif level == 4:
                current_h3 = text_clean
            if not current_h2 and not current_h3:
                continue
            group = current_h3 or current_h2 or default_group
            chunk = body[start:end]
            img_url = ""
            img_m = IMG_DATA_SRC_RE.search(chunk) or IMG_SRC_RE.search(chunk)
            if img_m:
                u = img_m.group(1).strip()
                if u and not u.startswith("data:") and "favicon" not in u.lower():
                    img_url = u
            sections.append((group, chunk, img_url))

    for group_name, chunk, group_image in sections:
        for table_html in TABLE_RE.findall(chunk):
            rows = TR_RE.findall(table_html)
            rows_text: List[List[str]] = []
            for row in rows:
                cells = TD_RE.findall(row)
                if not cells:
                    continue
                rows_text.append([_strip_html(c) for c in cells])
            if not rows_text:
                continue

            header_map: Optional[Dict[str, int]] = None
            data_start = 0
            if any(h in rows_text[0] for h in JP_HEADERS | EN_HEADERS):
                header_map = _classify_headers(rows_text[0])
                data_start = 1
            if not header_map:
                header_map = _heuristic_pick_columns(rows_text[data_start:])
                if not header_map:
                    continue

            jp_i = header_map["jp"]
            en_i = header_map["en"]
            for ridx, text_cells in enumerate(rows_text[data_start:], start=data_start):
                if len(text_cells) <= max(jp_i, en_i):
                    continue
                jp = _clean_jp(text_cells[jp_i])
                if not jp or jp in JP_HEADERS or jp in EN_HEADERS:
                    continue
                en_lines = _cell_to_lines(TD_RE.findall(rows[ridx])[en_i])
                if not en_lines:
                    continue
                tags = out.setdefault(group_name, {})
                for raw_en in en_lines:
                    en = _clean_en(raw_en)
                    if not _is_useful_english(en):
                        continue
                    if en not in tags:
                        tags[en] = (jp, group_image)
    return title, out


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
    req = urllib.request.Request(safe_url, headers={"User-Agent": USER_AGENT, "Referer": BASE + "/"})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = resp.read()
        return preview_convert.save_bytes_as_webp(data, dest_path)
    except Exception as e:
        print(f"  [warn] image download failed: {image_url} ({e})")
        return False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force-fetch", action="store_true")
    parser.add_argument("--skip-images", action="store_true")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument(
        "--out",
        default=os.path.join(_SCRIPT_DIR, "..", "group_tags", "mania_romptn_grok.yaml"),
    )
    args = parser.parse_args()

    ext_dir = os.path.dirname(_SCRIPT_DIR)
    previews_dir = user_storage.tag_previews_dir(ext_dir)

    print(f"[mania-romptn-grok] fetching hub: {HUB_URL}")
    hub_html = fetch_url(HUB_URL, cache_name="4977.html", force=args.force_fetch)
    urls = extract_sub_article_urls(hub_html)
    if args.limit:
        urls = urls[: args.limit]
    print(f"[mania-romptn-grok] sub-articles: {len(urls)}")

    section = {"name": SECTION_NAME, "categories": []}
    img_ok = img_fail = total = 0
    for i, url in enumerate(urls, 1):
        slug = url.rstrip("/").rsplit("/", 1)[-1]
        sub_kind = url.rstrip("/").rsplit("/", 2)[-2]  # stable-diffusion / grok / etc.
        cache = f"sub-{sub_kind}-{slug}.html"
        print(f"[{i}/{len(urls)}] {url}")
        try:
            html = fetch_url(url, cache_name=cache, force=args.force_fetch)
        except Exception as e:
            print(f"  [error] fetch failed: {e}")
            continue
        title, groups = parse_article(html)
        n_pairs = sum(len(v) for v in groups.values())
        print(f"  title='{title[:60]}' | groups={len(groups)} | pairs={n_pairs}")
        if n_pairs == 0:
            continue
        cat_obj = {"name": title or slug, "groups": []}
        for group_name, tags in groups.items():
            if not tags:
                continue
            sorted_tags: Dict[str, str] = {}
            for tag in sorted(tags.keys(), key=lambda x: x.lower()):
                jp, image_url = tags[tag]
                sorted_tags[tag] = jp
                if image_url and not args.skip_images:
                    dest = preview_filenames.preview_path_for_tag(previews_dir, tag, ".webp")
                    if download_image(image_url, dest):
                        img_ok += 1
                    else:
                        img_fail += 1
            cat_obj["groups"].append({"name": group_name, "tags": sorted_tags})
            total += len(sorted_tags)
        section["categories"].append(cat_obj)

    print(f"[mania-romptn-grok] total tags: {total} | images ok/fail: {img_ok}/{img_fail}")

    data = [section]
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
    print(f"[mania-romptn-grok] wrote: {out_path}")


if __name__ == "__main__":
    main()
