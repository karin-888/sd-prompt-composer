#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""Import illustrationaiart.com (AIイラストの探究) prompts into a YAML dictionary.

Each article uses a SWELL-style layout with ``<h2>`` category headings
followed by ``<figure class="wp-block-image">`` blocks whose
``<figcaption>`` text follows the format::

    日本語
    english prompt 1
    english prompt 2

(newlines are represented as ``<br>``). The figure also carries a
``data-src``/``src`` JPEG that can be used as the preview image.

Output:
    extensions/sd-prompt-composer/group_tags/illustai.yaml
    Preview images downloaded into the standard tag-previews directory.
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

USER_AGENT = "Mozilla/5.0 (compatible; PromptComposerImporter/1.0; illustai)"
BASE = "https://illustrationaiart.com"
SECTION_NAME = "AIイラストの探究 (illustrationaiart.com)"
CACHE_DIR = "/tmp/pc-tag-import/illustai"
LISTING_URL = "https://illustrationaiart.com/category/prompt/"
REQUEST_DELAY = 0.4

HEADING_RE = re.compile(r"<h([234])[^>]*>([\s\S]*?)</h\1>", re.IGNORECASE)
FIGURE_RE = re.compile(r"<figure[^>]*>([\s\S]*?)</figure>", re.IGNORECASE)
FIGCAPTION_RE = re.compile(r"<figcaption[^>]*>([\s\S]*?)</figcaption>", re.IGNORECASE)
IMG_DATA_SRC_RE = re.compile(r'<img[^>]+data-src="([^"]+)"', re.IGNORECASE)
IMG_SRC_RE = re.compile(r'<img[^>]+\ssrc="([^"]+)"', re.IGNORECASE)
TAG_STRIP_RE = re.compile(r"<[^>]+>")

ENG_TAG_RE = re.compile(r"^[a-zA-Z0-9 _\-,'\.!?()/:]+$")

ARTICLE_LINK_RE = re.compile(
    r'<a\s+href="(https://illustrationaiart\.com/(?!category|wp-|tag|page|feed|privacypolicy|contact|profile|sitemap|anime/|real/|cyan/|r18/)[a-z0-9_\-]+/)"',
    re.IGNORECASE,
)

SKIP_HEADING_FRAGMENTS = (
    "コメント",
    "目次",
    "関連記事",
    "あわせて読みたい",
    "プロフィール",
    "この記事を書いた人",
    "新着",
    "人気",
    "サイドバー",
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


def _figcaption_to_lines(cap_html: str) -> List[str]:
    s = re.sub(r"<br\s*/?>", "\n", cap_html, flags=re.IGNORECASE)
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


def list_article_urls(force: bool = False) -> List[str]:
    urls: List[str] = []
    seen = set()
    for page in (1, 2, 3, 4):
        if page == 1:
            url = LISTING_URL
            cache = "listing-p1.html"
        else:
            url = f"{LISTING_URL}page/{page}/"
            cache = f"listing-p{page}.html"
        try:
            html = fetch_url(url, cache_name=cache, force=force)
        except Exception as e:
            print(f"  [warn] listing fetch failed page {page}: {e}")
            continue
        for m in ARTICLE_LINK_RE.finditer(html):
            u = m.group(1)
            # filter out trivial root pages
            if u in (BASE + "/", BASE):
                continue
            if u in seen:
                continue
            seen.add(u)
            urls.append(u)
    return urls


def _extract_title(html: str) -> str:
    m = re.search(r"<h1[^>]*>([\s\S]*?)</h1>", html, re.IGNORECASE)
    if m:
        return _strip_html(m.group(1))
    m = re.search(r"<title>([\s\S]*?)</title>", html, re.IGNORECASE)
    if m:
        title = _strip_html(m.group(1))
        return title.split("｜")[0].split("|")[0].strip()
    return ""


def parse_article(html: str) -> Tuple[str, Dict[str, Dict[str, Tuple[str, str]]]]:
    """Return (title, {group_name: {english_tag: (japanese, image_url)}})."""
    title = _extract_title(html)

    heads = list(HEADING_RE.finditer(html))
    head_positions = [
        (int(h.group(1)), _strip_html(h.group(2)), h.end(), heads[i + 1].start() if i + 1 < len(heads) else len(html))
        for i, h in enumerate(heads)
    ]

    out: Dict[str, Dict[str, Tuple[str, str]]] = {}
    current_group = title or "一覧"
    # Walk through ordered headings, but only h2 changes the group context.
    for level, text, start, end in head_positions:
        text_clean = text.strip()
        if any(frag in text_clean for frag in SKIP_HEADING_FRAGMENTS):
            current_group = None
            continue
        if level == 2:
            current_group = text_clean
        elif level == 3:
            current_group = text_clean
        if not current_group:
            continue
        chunk = html[start:end]
        for fig in FIGURE_RE.finditer(chunk):
            block = fig.group(1)
            cap_m = FIGCAPTION_RE.search(block)
            if not cap_m:
                continue
            lines = _figcaption_to_lines(cap_m.group(1))
            if len(lines) < 2:
                continue
            jp = _clean_jp(lines[0])
            if not jp:
                continue
            img_m = IMG_DATA_SRC_RE.search(block) or IMG_SRC_RE.search(block)
            image_url = img_m.group(1) if img_m else ""
            if image_url.startswith("data:"):
                # the inline placeholder gif; try other img attribute
                img_m2 = IMG_DATA_SRC_RE.search(block)
                image_url = img_m2.group(1) if img_m2 else ""
            tags = out.setdefault(current_group, {})
            for raw_en in lines[1:]:
                en = _clean_en(raw_en)
                if not _is_useful_english(en):
                    continue
                if en not in tags:
                    tags[en] = (jp, image_url)
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
        default=os.path.join(_SCRIPT_DIR, "..", "group_tags", "illustai.yaml"),
    )
    args = parser.parse_args()

    ext_dir = os.path.dirname(_SCRIPT_DIR)
    previews_dir = user_storage.tag_previews_dir(ext_dir)

    urls = list_article_urls(force=args.force_fetch)
    if args.limit:
        urls = urls[: args.limit]
    print(f"[illustai] article URLs: {len(urls)}")

    section = {"name": SECTION_NAME, "categories": []}
    img_ok = img_fail = total = 0
    for i, url in enumerate(urls, 1):
        slug = url.rstrip("/").rsplit("/", 1)[-1]
        cache = f"a-{slug}.html"
        print(f"[{i}/{len(urls)}] {url}")
        try:
            html = fetch_url(url, cache_name=cache, force=args.force_fetch)
        except Exception as e:
            print(f"  [error] fetch failed: {e}")
            continue
        title, groups = parse_article(html)
        n_pairs = sum(len(v) for v in groups.values())
        print(f"  title='{title}' | groups={len(groups)} | pairs={n_pairs}")
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

    print(f"[illustai] total tags: {total} | images ok/fail: {img_ok}/{img_fail}")

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
    print(f"[illustai] wrote: {out_path}")


if __name__ == "__main__":
    main()
