#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""Import tags, Japanese translations, and preview images from aieroi.com.

The site uses a WordPress (SWELL) layout where each prompt entry is encoded as
an ``<h3>`` or ``<h4>`` heading whose text follows the pattern
``日本語名【english prompt】``. ``<h2>`` headings split the article into
sub-groups (e.g. 髪の長さ / 髪型 / 髪の特徴). The first ``<img>`` after each
prompt heading is treated as that prompt's preview.

Outputs:
    extensions/sd-prompt-composer/group_tags/aieroi.yaml
    {data_path}/sd-prompt-composer/tag-previews/{tag}.webp
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

USER_AGENT = "Mozilla/5.0 (compatible; PromptComposerImporter/1.0; aieroi)"
BASE = "https://aieroi.com"
SECTION_NAME = "AIエロイラスト.com (aieroi.com)"
CACHE_DIR = "/tmp/pc-tag-import/aieroi"
REQUEST_DELAY = 0.4

# (category_name, article_slug)
ARTICLES: List[Tuple[str, str]] = [
    ("髪型", "hair"),
    ("表情", "expression"),
    ("コスチューム", "costume"),
    ("下着", "underwear"),
    ("装飾品", "accessories-1"),
    ("ポーズ・基本", "posture-1"),
    ("ポーズ・手足", "posture-2"),
    ("背景・室内", "background-indoor"),
    ("背景・屋外", "background-outdoor"),
    ("着衣エロ", "non-nude-erotica"),
    ("R-18エロ強化", "etc-ero"),
    ("射精", "cumshot"),
    ("SEX体位", "sex"),
    ("前戯", "oral"),
]

POST_CONTENT_RE = re.compile(
    r'<div[^>]*class="[^"]*post_content[^"]*"[^>]*>([\s\S]+?)</article>',
    re.IGNORECASE,
)
HEADING_RE = re.compile(r"<h([234])[^>]*>([\s\S]*?)</h\1>", re.IGNORECASE)
BRACKET_RE = re.compile(r"^(?P<jp>[^【]+)【(?P<en>[^】]+)】(?:\s*(?P<extra>.*))?$")
IMG_RE = re.compile(r'<img[^>]+(?:data-src|src)="([^"]+)"', re.IGNORECASE)
TAG_STRIP_RE = re.compile(r"<[^>]+>")

# Names of h2 sections that should not contribute prompts even if they
# happen to contain matching headings (e.g. footers / comment areas).
SKIP_H2 = {
    "コメント",
    "目次",
    "関連記事",
    "コメント一覧",
    "コメントする",
}
SKIP_TITLE_FRAGMENTS = (
    "コメント",
    "目次",
    "関連記事",
    "返信",
    "プロフィール",
)

# Reject prompt tags that look like Japanese fragments instead of English tags.
ENG_TAG_RE = re.compile(r"^[a-zA-Z0-9 _\-,'/.!?]+$")


def extension_dir() -> str:
    return os.path.dirname(_SCRIPT_DIR)


def previews_root(ext_dir: str) -> str:
    return user_storage.tag_previews_dir(ext_dir)


def _cache_path(slug: str) -> str:
    os.makedirs(CACHE_DIR, exist_ok=True)
    return os.path.join(CACHE_DIR, f"{slug}.html")


def fetch(url: str, slug: Optional[str] = None, force: bool = False, timeout: int = 60) -> str:
    cache = _cache_path(slug) if slug else None
    if cache and not force and os.path.isfile(cache):
        with open(cache, encoding="utf-8") as f:
            return f.read()
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        text = resp.read().decode("utf-8", errors="replace")
    if cache:
        with open(cache, "w", encoding="utf-8") as f:
            f.write(text)
    time.sleep(REQUEST_DELAY)
    return text


def _strip_html(s: str) -> str:
    return unescape(TAG_STRIP_RE.sub("", s)).strip()


def is_valid_english_tag(text: str) -> bool:
    if not text or len(text) > 80:
        return False
    return bool(ENG_TAG_RE.match(text))


def normalize_english(text: str) -> str:
    text = text.strip().strip("`").strip()
    text = text.replace("\u2018", "'").replace("\u2019", "'")
    text = text.replace("\u201c", '"').replace("\u201d", '"')
    text = re.sub(r"\s+", " ", text)
    text = text.strip(",.;:!?")
    return text


def split_english_alts(text: str) -> List[str]:
    """Split slash-separated English prompts (e.g. ``a / b``) into a list."""
    out = []
    for part in text.split("/"):
        part = part.strip()
        if part:
            out.append(part)
    return out or [text]


def normalize_japanese(text: str) -> str:
    text = text.strip()
    text = re.sub(r"\s+", " ", text)
    text = text.strip("：:、,.;")
    text = re.sub(r"^[\-•・●▶▷>＞]+\s*", "", text)
    return text


def _is_thumbnail_or_icon(url: str) -> bool:
    low = url.lower()
    if any(s in low for s in ("favicon", "logo", "title", "/avatars/")):
        return True
    if any(s in low for s in ("aieroi-main", "aieroi_title", "cropped-aieroi")):
        return True
    return False


def parse_article(category: str, slug: str, html: str) -> List[Dict]:
    """Return a list of entries: [{group, tag, jp, image_url}]."""
    m = POST_CONTENT_RE.search(html)
    if not m:
        return []
    body = m.group(1)

    parts: List[Tuple[str, str, int]] = []  # (level, text, end_offset)
    for hm in HEADING_RE.finditer(body):
        level = int(hm.group(1))
        text = _strip_html(hm.group(2))
        if not text:
            continue
        parts.append((level, text, hm.end()))
        # Mark heading boundaries by also recording the end position so we can
        # find the next image *between* this heading and the next.

    boundaries = [hm.end() for hm in HEADING_RE.finditer(body)]
    boundary_starts = [hm.start() for hm in HEADING_RE.finditer(body)]

    headings = []
    for idx, hm in enumerate(HEADING_RE.finditer(body)):
        level = int(hm.group(1))
        text = _strip_html(hm.group(2))
        if not text:
            continue
        next_start = boundary_starts[idx + 1] if idx + 1 < len(boundary_starts) else len(body)
        chunk = body[hm.end():next_start]
        headings.append((level, text, chunk))

    current_group = ""
    entries: List[Dict] = []
    used_images: set = set()
    for level, text, chunk in headings:
        cleaned = text.strip()
        if any(frag in cleaned for frag in SKIP_TITLE_FRAGMENTS):
            continue
        if cleaned in SKIP_H2:
            continue

        m2 = BRACKET_RE.match(cleaned)
        if not m2:
            # Treat as a group/section heading
            if level == 2 and cleaned not in SKIP_H2:
                current_group = cleaned
            elif level in (3, 4) and not cleaned.startswith("【"):
                # bare textual h3/h4 (e.g. introduction); keep last group
                pass
            continue

        jp = normalize_japanese(m2.group("jp"))
        en_raw = normalize_english(m2.group("en"))
        if not en_raw:
            continue
        # Skip placeholder/template prompts (e.g. ``○○ lift``).
        if "○" in en_raw or "○" in jp:
            continue

        # find first useful image in chunk
        image_url = ""
        for im in IMG_RE.finditer(chunk):
            url = im.group(1).strip()
            if not url:
                continue
            if url.startswith("//"):
                url = "https:" + url
            if not url.startswith("http"):
                continue
            if _is_thumbnail_or_icon(url):
                continue
            # SWELL lazy loads sometimes use placeholders that are 1x1 gifs
            if url.lower().endswith((".gif", ".svg")) and "thumbnail" not in url.lower():
                # accept gif/svg only if explicit thumbnail
                pass
            image_url = url
            break

        en_alts = split_english_alts(en_raw)
        added = False
        for en in en_alts:
            en = normalize_english(en)
            if not en or not is_valid_english_tag(en):
                continue
            jp_value = jp if jp else en
            entries.append(
                {
                    "group": current_group or category,
                    "tag": en,
                    "jp": jp_value,
                    "image_url": image_url,
                }
            )
            added = True
        if not added:
            # Single complex tag that doesn't fit ASCII validation;
            # still try the original if it is ASCII-only after stripping commas.
            collapsed = re.sub(r"\s+", " ", en_raw)
            if is_valid_english_tag(collapsed):
                entries.append(
                    {
                        "group": current_group or category,
                        "tag": collapsed,
                        "jp": jp or collapsed,
                        "image_url": image_url,
                    }
                )

    return entries


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


def build_yaml(article_results: Dict[str, Dict[str, Dict[str, str]]]) -> List[Dict]:
    section: Dict = {"name": SECTION_NAME, "categories": []}
    for cat_name, groups in article_results.items():
        cat_obj = {"name": cat_name, "groups": []}
        for group_name in sorted(groups.keys()):
            tags = groups[group_name]
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
    parser.add_argument("--dry-run", action="store_true", help="Parse but do not write outputs")
    parser.add_argument("--force-fetch", action="store_true", help="Bypass HTML cache")
    parser.add_argument("--skip-images", action="store_true", help="Do not download preview images")
    parser.add_argument(
        "--out",
        default=os.path.join(_SCRIPT_DIR, "..", "group_tags", "aieroi.yaml"),
    )
    args = parser.parse_args()

    ext_dir = extension_dir()
    previews_dir = previews_root(ext_dir)

    all_results: Dict[str, Dict[str, Dict[str, str]]] = {}
    img_ok = 0
    img_fail = 0
    total_entries = 0

    for cat_name, slug in ARTICLES:
        url = f"{BASE}/{slug}/"
        print(f"[aieroi] {cat_name}: fetching {url}")
        try:
            html = fetch(url, slug=slug, force=args.force_fetch)
        except Exception as e:
            print(f"  [error] fetch failed: {e}")
            continue
        entries = parse_article(cat_name, slug, html)
        print(f"  parsed: {len(entries)} entries")
        groups = all_results.setdefault(cat_name, {})
        for entry in entries:
            group_name = entry.get("group") or "一覧"
            tags = groups.setdefault(group_name, {})
            tag = entry["tag"]
            tags[tag] = entry.get("jp") or tag
            total_entries += 1
            if entry.get("image_url") and not args.skip_images and not args.dry_run:
                dest = preview_filenames.preview_path_for_tag(previews_dir, tag, ".webp")
                if download_image(entry["image_url"], dest):
                    img_ok += 1
                else:
                    img_fail += 1

    print(f"[aieroi] entries total: {total_entries}, images ok/fail: {img_ok}/{img_fail}")

    data = build_yaml(all_results)
    out_path = os.path.abspath(args.out)
    if not args.dry_run:
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
        print(f"[aieroi] wrote: {out_path}")
    else:
        print("[aieroi] dry-run: not writing YAML")


if __name__ == "__main__":
    main()
