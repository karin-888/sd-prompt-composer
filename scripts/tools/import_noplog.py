# -*- coding: UTF-8 -*-
"""
Import tags and preview images from noplog.com (プロンプトライブラリ category).

Usage:
  python import_noplog.py [--dry-run] [--limit N]

Outputs:
  group_tags/noplog.yaml
  {data_path}/sd-prompt-composer/tag-previews/{tag}.{ext}
  {data_path}/sd-prompt-composer/noplog-import-manifest.json
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
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
import tag_text_utils
import preview_filenames
import preview_convert

USER_AGENT = "PromptComposerImporter/1.0 (personal local import)"
CATEGORY_BASE = "https://noplog.com/blog/category/prompt-library/"
SECTION_NAME = "noplog"
REQUEST_DELAY = 0.35
MAX_TAG_LEN = 120
MAX_TAG_COMMAS = 8

ARTICLE_URL_RE = re.compile(
    r"https://noplog\.com/blog/\d{4}/\d{2}/\d{2}/[^/]+/?$",
    re.IGNORECASE,
)

TABLE_RE = re.compile(r"<table[\s\S]*?</table>", re.IGNORECASE)
TR_RE = re.compile(r"<tr[^>]*>([\s\S]*?)</tr>", re.IGNORECASE)
TD_RE = re.compile(r"<td[^>]*>([\s\S]*?)</td>", re.IGNORECASE)
TH_RE = re.compile(r"<t[dh][^>]*>([\s\S]*?)</t[dh]>", re.IGNORECASE)
HEADING_RE = re.compile(r"<h([23])[^>]*>([\s\S]*?)</h\1>", re.IGNORECASE)
SAMPLE_CARD_RE = re.compile(
    r'<div class="((?:style-atlas|facial|body|pose|pattern|color|onepiece)-sample-card)"([^>]*)>',
    re.IGNORECASE,
)
CLOTHING_CARD_RE = re.compile(
    r'<div class="sample-card"([^>]*)>[\s\S]*?<button class="view-sample-btn" data-image="([^"]+)"',
    re.IGNORECASE,
)
IMAGE_ITEM_RE = re.compile(
    r"<div class='image-item'[^>]*data-category='([^']*)'[^>]*>\s*<img([^>]+)/?>",
    re.IGNORECASE,
)
TEXT_CONT_RE = re.compile(r'<div id="textCont\d+">([^<]+)</div>', re.IGNORECASE)
ATTR_RE = re.compile(r'([\w-]+)="([^"]*)"')
IMG_SRC_RE = re.compile(r'src="(https://noplog\.com/wp-content/uploads/[^"]+)"', re.IGNORECASE)
COPY_AREA_RE = re.compile(r'class="copy-area">([^<]+)</div>', re.IGNORECASE)
HD_PALAM_RE = re.compile(r'class="hd-palam">([^<]+)</div>', re.IGNORECASE)

SKIP_TAG_VALUES = {
    "copy",
    "プロンプト",
    "意味",
    "区分",
    "コピー",
    "コピーボタン",
    "表情",
    "髪型の名称",
    "種類",
    "英語タグ例",
}


def is_plausible_tag(tag: str) -> bool:
    t = (tag or "").strip()
    if not t or len(t) > MAX_TAG_LEN:
        return False
    if t.count(",") > MAX_TAG_COMMAS:
        return False
    if t.lower() in SKIP_TAG_VALUES:
        return False
    if not tag_text_utils.looks_like_english_tag(t) and not re.search(r"[a-zA-Z]", t):
        return False
    return True


def extension_dir() -> str:
    return os.path.dirname(_SCRIPT_DIR)


def resolve_previews_dir(ext_dir: str) -> str:
    repo_root = os.path.dirname(os.path.dirname(ext_dir))
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)
    try:
        from modules.paths_internal import data_path

        path = os.path.join(data_path, user_storage.USER_SUBDIR, "tag-previews")
    except Exception:
        path = os.path.join(repo_root, user_storage.USER_SUBDIR, "tag-previews")
    os.makedirs(path, exist_ok=True)
    return path


def strip_tags(text: str) -> str:
    return tag_text_utils.strip_html(text)


def fetch(url: str, timeout: int = 60) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def list_category_articles(max_pages: int = 8) -> List[str]:
    found: List[str] = []
    seen = set()
    for page in range(1, max_pages + 1):
        url = CATEGORY_BASE if page == 1 else CATEGORY_BASE + f"page/{page}/"
        try:
            html = fetch(url)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                break
            raise
        links = re.findall(
            r'href="(https://noplog\.com/blog/\d{4}/\d{2}/\d{2}/[^"]+)"',
            html,
            flags=re.IGNORECASE,
        )
        page_urls = []
        for link in links:
            link = link.rstrip("/") + "/"
            if not ARTICLE_URL_RE.match(link) or link in seen:
                continue
            seen.add(link)
            page_urls.append(link)
        if not page_urls and page > 1:
            break
        found.extend(page_urls)
        time.sleep(REQUEST_DELAY)
    return sorted(set(found))


def parse_title(html: str) -> str:
    m = re.search(r'<meta\s+property="og:title"\s+content="([^"]+)"', html, re.IGNORECASE)
    if m:
        title = unescape(m.group(1)).strip()
        title = re.sub(r"\s*\|\s*のぷろぐ.*$", "", title)
        return title.strip()
    m = re.search(r"<title>([^<]+)</title>", html, re.IGNORECASE)
    if m:
        title = unescape(m.group(1)).strip()
        title = re.sub(r"\s*\|\s*のぷろぐ.*$", "", title)
        return title.strip()
    return "未分類"


def extract_entry_content(html: str) -> str:
    m = re.search(
        r'<div class="entry-content cf[^"]*"[^>]*>([\s\S]*?)</div>\s*<footer',
        html,
        re.IGNORECASE,
    )
    if m:
        return m.group(1)
    m = re.search(r'<div[^>]+class="[^"]*entry-content[^"]*"[^>]*>', html, re.IGNORECASE)
    if not m:
        return html
    start = m.end()
    end = html.find('<footer class="article-footer', start)
    if end == -1:
        end = html.find("</article>", start)
    if end == -1:
        end = len(html)
    return html[start:end]


def split_by_headings(html: str) -> List[Tuple[str, str]]:
    main = extract_entry_content(html)
    chunks: List[Tuple[str, str]] = []
    matches = list(HEADING_RE.finditer(main))
    if not matches:
        return [("一覧", main)]

    if matches[0].start() > 0:
        chunks.append(("概要", main[: matches[0].start()]))

    for i, match in enumerate(matches):
        group = strip_tags(match.group(2)) or "一覧"
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(main)
        chunks.append((group, main[start:end]))
    return chunks


def parse_atlas_attrs(attrs: str) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for key, val in ATTR_RE.findall(attrs or ""):
        out[key.lower()] = unescape(val).strip()
    return out


def atlas_group_name(attrs: Dict[str, str]) -> str:
    main = attrs.get("data-main-cat") or ""
    sub = attrs.get("data-sub-cat") or ""
    if main and sub:
        return f"{main} / {sub}"
    return main or sub or "一覧"


def parse_clothing_cards(html: str, group_hint: str = "") -> List[Dict]:
    items: List[Dict] = []
    for match in CLOTHING_CARD_RE.finditer(html):
        attrs = parse_atlas_attrs(match.group(1))
        tag = (attrs.get("data-prompt-generated") or "").strip()
        jp = (attrs.get("data-alt-text") or "").strip()
        image_url = (match.group(2) or "").strip()
        feature = (attrs.get("data-prompt-features") or "").strip()
        group = feature or group_hint or "一覧"
        tag, jp = tag_text_utils.normalize_tag_jp(tag, jp)
        if not is_plausible_tag(tag):
            continue
        items.append({"tag": tag, "jp": jp, "image_url": image_url, "group": group})
    return items


def parse_copy_text_prompts(html: str, group_hint: str = "") -> List[Dict]:
    items: List[Dict] = []
    for tag in TEXT_CONT_RE.findall(html):
        tag = strip_tags(tag)
        tag, jp = tag_text_utils.normalize_tag_jp(tag, "")
        if not is_plausible_tag(tag):
            continue
        items.append({"tag": tag, "jp": jp or tag, "image_url": "", "group": group_hint or "一覧"})
    return items


def normalize_image_url(url: str) -> str:
    url = (url or "").strip()
    if not url:
        return ""
    if re.search(r"-\d+x\d+(?=\.(webp|jpg|jpeg|png|gif)$)", url, re.IGNORECASE):
        url = re.sub(r"-\d+x\d+(?=\.(webp|jpg|jpeg|png|gif)$)", "", url, flags=re.IGNORECASE)
    return url


def parse_copy_area_table_pairs(html: str, group_hint: str = "") -> List[Dict]:
    """Extract prompt + sample image pairs from noplog copy-area table layouts."""
    items: List[Dict] = []
    pending_labels: List[str] = []

    for tr in TR_RE.findall(html):
        labels = [strip_tags(x) for x in HD_PALAM_RE.findall(tr) if strip_tags(x)]
        if labels:
            pending_labels = labels
            continue

        imgs = [
            normalize_image_url(u)
            for u in IMG_SRC_RE.findall(tr)
            if "-150x150" not in u and "-120x68" not in u
        ]
        prompts = [strip_tags(x) for x in COPY_AREA_RE.findall(tr)]
        prompts = [p for p in prompts if p and p.lower() != "copy"]
        if not prompts:
            continue

        for i, prompt in enumerate(prompts):
            tag, _jp = tag_text_utils.normalize_tag_jp(prompt, "")
            if not is_plausible_tag(tag):
                continue
            jp = pending_labels[i] if i < len(pending_labels) else ""
            image_url = imgs[i] if i < len(imgs) else ""
            items.append(
                {
                    "tag": tag,
                    "jp": jp,
                    "image_url": image_url,
                    "group": group_hint or "一覧",
                }
            )
        if imgs and prompts:
            pending_labels = []
    return items


def parse_sample_cards(html: str, group_hint: str = "") -> List[Dict]:
    """style-atlas-sample-card, facial-sample-card, etc."""
    items: List[Dict] = []
    for match in SAMPLE_CARD_RE.finditer(html):
        attrs = parse_atlas_attrs(match.group(2))
        chunk = html[match.end() : match.end() + 2500]
        image_url = (attrs.get("data-image-full") or "").strip()
        if not image_url:
            img_m = re.search(r'data-image="([^"]+)"', chunk, re.IGNORECASE)
            if img_m:
                image_url = normalize_image_url(img_m.group(1))
        tag = (attrs.get("data-prompt-generated") or "").strip()
        jp = (attrs.get("data-prompt-meaning") or "").strip()
        if not jp:
            alt_m = re.search(r'\salt="([^"]*)"', chunk, re.IGNORECASE)
            if alt_m:
                jp = tag_text_utils.jp_from_img_alt(alt_m.group(1))
        tag, jp = tag_text_utils.normalize_tag_jp(tag, jp)
        if not is_plausible_tag(tag):
            continue
        items.append(
            {
                "tag": tag,
                "jp": jp,
                "image_url": image_url,
                "group": atlas_group_name(attrs) or group_hint or "一覧",
            }
        )
    return items


def parse_image_grid_items(html: str, group_hint: str = "") -> List[Dict]:
    """Clothing gallery image-grid layout."""
    items: List[Dict] = []
    for category, img_attrs in IMAGE_ITEM_RE.findall(html):
        src_m = re.search(r"src='([^']+)'", img_attrs, re.IGNORECASE)
        if not src_m:
            continue
        image_url = normalize_image_url(src_m.group(1))
        gen_m = re.search(r"data-generated-prompt='([^']*)'", img_attrs, re.IGNORECASE)
        main_m = re.search(r"data-main-prompt='([^']*)'", img_attrs, re.IGNORECASE)
        alt_m = re.search(r"alt='([^']*)'", img_attrs, re.IGNORECASE)
        tag = (gen_m.group(1) if gen_m else main_m.group(1) if main_m else alt_m.group(1) if alt_m else "").strip()
        jp = (alt_m.group(1) if alt_m else category or "").strip()
        tag, jp = tag_text_utils.normalize_tag_jp(tag, jp)
        if not is_plausible_tag(tag):
            continue
        group = category.strip() or group_hint or "一覧"
        items.append({"tag": tag, "jp": jp or tag, "image_url": image_url, "group": group})
    return items


def parse_race_table_pairs(html: str, group_hint: str = "") -> List[Dict]:
    """Pair textCont prompts with table sample images (race/species articles)."""
    items: List[Dict] = []
    for table_html in TABLE_RE.findall(html):
        if "textCont" not in table_html:
            continue
        pending_imgs: List[str] = []
        for tr in TR_RE.findall(table_html):
            imgs = [
                normalize_image_url(u)
                for u in IMG_SRC_RE.findall(tr)
                if "-150x150" not in u and "-120x68" not in u
            ]
            prompts = [strip_tags(x) for x in TEXT_CONT_RE.findall(tr)]
            if imgs and not prompts:
                pending_imgs.extend(imgs)
                continue
            for i, prompt in enumerate(prompts):
                tag, jp = tag_text_utils.normalize_tag_jp(prompt, "")
                if not is_plausible_tag(tag):
                    continue
                image_url = imgs[i] if i < len(imgs) else ""
                if not image_url and pending_imgs:
                    image_url = pending_imgs.pop(0)
                items.append(
                    {
                        "tag": tag,
                        "jp": jp or tag,
                        "image_url": image_url,
                        "group": group_hint or "一覧",
                    }
                )
    return items


def parse_atlas_cards(html: str, group_hint: str = "") -> List[Dict]:
    return parse_sample_cards(html, group_hint=group_hint)


def parse_table_rows(table_html: str) -> List[Tuple[str, str]]:
    rows: List[Tuple[str, str]] = []
    tag_col, jp_col = 0, 1
    header_seen = False
    has_category_col = False

    for tr in TR_RE.findall(table_html):
        if "<th" in tr.lower() or (not header_seen and "プロンプト" in tr):
            headers = [strip_tags(c) for c in TH_RE.findall(tr)]
            if headers:
                if any("区分" in h for h in headers):
                    has_category_col = True
                tag_col, jp_col = tag_text_utils.detect_table_columns(headers)
                header_seen = True
            if "<th" in tr.lower():
                continue

        cells = [strip_tags(c) for c in TD_RE.findall(tr)]
        cells = [c for c in cells if c]
        if len(cells) < 2:
            continue

        tag = ""
        jp = ""
        if has_category_col:
            if len(cells) >= 4:
                tag = cells[1].strip()
                jp = cells[2].strip()
            elif len(cells) == 3 and cells[-1].lower() == "copy":
                tag = cells[0].strip()
                jp = cells[1].strip()
        else:
            tag = cells[tag_col].strip() if tag_col < len(cells) else ""
            jp = cells[jp_col].strip() if jp_col < len(cells) else ""

        tag, jp = tag_text_utils.normalize_tag_jp(tag, jp)
        if not tag or tag.lower() in SKIP_TAG_VALUES:
            continue
        if not is_plausible_tag(tag):
            continue
        rows.append((tag, jp))
    return rows


def _prefer_jp(tag: str, current: str, candidate: str) -> str:
    current = tag_text_utils.sanitize_tag_jp(tag, current or "")
    candidate = tag_text_utils.sanitize_tag_jp(tag, candidate or "")
    if not candidate:
        return current
    if not current or tag_text_utils.is_low_quality_jp(tag, current):
        return candidate
    return candidate if len(candidate) > len(current) else current


def parse_article(url: str, html: str) -> Dict:
    title = parse_title(html)
    by_tag: Dict[str, Dict] = {}

    def merge(entry: Dict) -> None:
        tag = entry["tag"]
        rec = by_tag.get(tag) or {
            "tag": tag,
            "jp": "",
            "image_url": "",
            "group": entry.get("group") or "一覧",
            "article": title,
            "source_url": url,
        }
        if entry.get("jp"):
            rec["jp"] = _prefer_jp(tag, rec.get("jp") or "", entry["jp"])
        if entry.get("image_url"):
            rec["image_url"] = entry["image_url"]
        if entry.get("group"):
            rec["group"] = entry["group"]
        by_tag[tag] = rec

    entry_html = extract_entry_content(html)
    for card in parse_sample_cards(entry_html):
        merge(card)
    for card in parse_clothing_cards(entry_html):
        merge(card)
    for card in parse_copy_area_table_pairs(entry_html):
        merge(card)
    for card in parse_image_grid_items(entry_html):
        merge(card)
    for card in parse_race_table_pairs(entry_html):
        merge(card)
    for card in parse_copy_text_prompts(entry_html):
        merge(card)

    for group_name, chunk in split_by_headings(html):
        for card in parse_sample_cards(chunk, group_hint=group_name):
            card["group"] = card.get("group") or group_name
            merge(card)
        for card in parse_clothing_cards(chunk, group_hint=group_name):
            card["group"] = card.get("group") or group_name
            merge(card)
        for card in parse_copy_area_table_pairs(chunk, group_hint=group_name):
            card["group"] = group_name
            merge(card)
        for card in parse_image_grid_items(chunk, group_hint=group_name):
            card["group"] = card.get("group") or group_name
            merge(card)
        for card in parse_race_table_pairs(chunk, group_hint=group_name):
            card["group"] = group_name
            merge(card)
        for card in parse_copy_text_prompts(chunk, group_hint=group_name):
            card["group"] = group_name
            merge(card)
        for table_html in TABLE_RE.findall(chunk):
            for tag, jp in parse_table_rows(table_html):
                merge({"tag": tag, "jp": jp, "image_url": "", "group": group_name})

    return {"title": title, "url": url, "entries": list(by_tag.values())}


def preview_path_for_tag(previews_dir: str, tag: str, image_url: str = "") -> str:
    return preview_filenames.preview_path_for_tag(previews_dir, tag, ".webp")


def download_image(image_url: str, dest_path: str, dry_run: bool = False) -> bool:
    dest_path = preview_convert.webp_dest_path(dest_path)
    if os.path.isfile(dest_path) and os.path.getsize(dest_path) > 0:
        return True
    if dry_run:
        return True
    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
    req = urllib.request.Request(image_url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = resp.read()
        return preview_convert.save_bytes_as_webp(data, dest_path)
    except Exception as e:
        print(f"  [warn] image download failed: {image_url} ({e})")
        return False


def build_yaml_structure(articles: List[Dict]) -> List[Dict]:
    categories: Dict[str, Dict] = {}
    lookup_items: List[Dict] = []
    for article in articles:
        for entry in article["entries"]:
            lookup_items.append({"tag": entry["tag"], "jp": entry.get("jp") or ""})
    jp_lookup = tag_text_utils.build_jp_lookup(lookup_items)

    for article in articles:
        cat_name = article["title"]
        cat = categories.setdefault(cat_name, {"name": cat_name, "groups": {}})
        groups = cat["groups"]
        for entry in article["entries"]:
            group_name = entry.get("group") or "一覧"
            grp = groups.setdefault(group_name, {"name": group_name, "tags": {}})
            tag = entry["tag"]
            jp = tag_text_utils.resolve_jp_label(tag, entry.get("jp") or "", jp_lookup)
            grp["tags"][tag] = jp or tag

    section = {"name": SECTION_NAME, "categories": []}
    for cat_name in sorted(categories.keys()):
        cat = categories[cat_name]
        cat_obj = {"name": cat_name, "groups": []}
        for group_name in sorted(cat["groups"].keys()):
            grp = cat["groups"][group_name]
            cat_obj["groups"].append(
                {
                    "name": group_name,
                    "tags": dict(sorted(grp["tags"].items(), key=lambda kv: kv[0].lower())),
                }
            )
        section["categories"].append(cat_obj)
    return [section]


def load_existing_yaml_entries(yaml_path: str) -> Dict[str, Dict]:
    """Return {article_title: {tag: entry_dict}} from existing noplog.yaml."""
    if not os.path.isfile(yaml_path):
        return {}
    try:
        with open(yaml_path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or []
    except Exception:
        return {}

    by_article: Dict[str, Dict[str, Dict]] = {}
    for section in data:
        if (section or {}).get("name") != SECTION_NAME:
            continue
        for cat in section.get("categories", []) or []:
            title = cat.get("name") or ""
            tags: Dict[str, Dict] = {}
            for group in cat.get("groups", []) or []:
                group_name = group.get("name") or "一覧"
                for tag, jp in (group.get("tags") or {}).items():
                    tags[str(tag)] = {
                        "tag": str(tag),
                        "jp": str(jp or tag),
                        "image_url": "",
                        "group": group_name,
                        "article": title,
                        "source_url": "",
                    }
            if title:
                by_article[title] = tags
    return by_article


def merge_article_entries(existing: Dict[str, Dict], article: Dict) -> None:
    title = article["title"]
    bucket = existing.setdefault(title, {})
    for entry in article["entries"]:
        tag = entry["tag"]
        prev = bucket.get(tag)
        if not prev:
            bucket[tag] = dict(entry)
            continue
        if entry.get("jp"):
            prev["jp"] = _prefer_jp(tag, prev.get("jp") or "", entry["jp"])
        if entry.get("image_url"):
            prev["image_url"] = entry["image_url"]
        if entry.get("group"):
            prev["group"] = entry["group"]
        if entry.get("source_url"):
            prev["source_url"] = entry["source_url"]
        bucket[tag] = prev


def articles_from_existing(existing: Dict[str, Dict]) -> List[Dict]:
    articles: List[Dict] = []
    for title, tags in sorted(existing.items()):
        if not tags:
            continue
        sample = next(iter(tags.values()))
        articles.append(
            {
                "title": title,
                "url": sample.get("source_url") or "",
                "entries": list(tags.values()),
            }
        )
    return articles


def run_import(
    dry_run: bool = False,
    limit: Optional[int] = None,
    article_urls: Optional[List[str]] = None,
    merge_existing: bool = False,
) -> Dict:
    ext_dir = extension_dir()
    previews_dir = resolve_previews_dir(ext_dir)
    yaml_path = os.path.join(ext_dir, "group_tags", "noplog.yaml")
    manifest_path = user_storage.bootstrap_json(ext_dir, "noplog-import-manifest.json")

    if article_urls is None:
        article_urls = list_category_articles()
    if limit:
        article_urls = article_urls[:limit]

    print(f"[noplog import] articles: {len(article_urls)}")
    parsed_articles: List[Dict] = []
    all_entries: List[Dict] = []
    images_ok = 0
    images_fail = 0
    partial_import = merge_existing
    existing_by_article = load_existing_yaml_entries(yaml_path) if partial_import else {}

    for i, url in enumerate(article_urls, 1):
        print(f"[{i}/{len(article_urls)}] {url}")
        try:
            html = fetch(url)
        except Exception as e:
            print(f"  [error] fetch failed: {e}")
            continue
        article = parse_article(url, html)
        parsed_articles.append(article)
        if partial_import:
            merge_article_entries(existing_by_article, article)
        print(f"  title: {article['title']}  tags: {len(article['entries'])}")

        for entry in article["entries"]:
            all_entries.append(entry)
            image_url = entry.get("image_url") or ""
            if not image_url:
                continue
            dest = preview_path_for_tag(previews_dir, entry["tag"], image_url)
            ok = download_image(image_url, dest, dry_run=dry_run)
            if ok:
                images_ok += 1
                entry["preview_file"] = os.path.basename(dest)
            else:
                images_fail += 1
            time.sleep(REQUEST_DELAY * 0.25)

        time.sleep(REQUEST_DELAY)

    if partial_import:
        parsed_articles = articles_from_existing(existing_by_article)
        all_entries = [entry for article in parsed_articles for entry in article["entries"]]
    yaml_data = build_yaml_structure(parsed_articles)
    tag_count = len({e["tag"] for e in all_entries})
    with_image = sum(1 for e in all_entries if e.get("image_url"))

    if not dry_run:
        os.makedirs(os.path.dirname(yaml_path), exist_ok=True)
        with open(yaml_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(
                yaml_data,
                f,
                allow_unicode=True,
                sort_keys=False,
                default_flow_style=False,
                width=120,
            )

        manifest = {
            "imported_at": time.time(),
            "source_category": CATEGORY_BASE,
            "article_count": len(parsed_articles),
            "tag_count": tag_count,
            "entries_with_image_url": with_image,
            "images_downloaded_ok": images_ok,
            "images_failed": images_fail,
            "yaml_path": yaml_path,
            "previews_dir": previews_dir,
            "articles": [
                {
                    "title": a["title"],
                    "url": a["url"],
                    "tag_count": len(a["entries"]),
                }
                for a in parsed_articles
            ],
        }
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)

    summary = {
        "articles": len(parsed_articles),
        "tags": tag_count,
        "with_image_url": with_image,
        "images_ok": images_ok,
        "images_fail": images_fail,
        "yaml_path": yaml_path,
        "previews_dir": previews_dir,
    }
    print("[noplog import] done:", summary)
    return summary


def main():
    parser = argparse.ArgumentParser(description="Import noplog.com prompt library tags and preview images")
    parser.add_argument("--dry-run", action="store_true", help="Parse only; do not write files")
    parser.add_argument("--limit", type=int, default=0, help="Limit number of articles (debug)")
    parser.add_argument(
        "--article-url",
        action="append",
        default=[],
        help="Import only specific article URL(s); can be repeated",
    )
    args = parser.parse_args()
    urls = [u.rstrip("/") + "/" for u in args.article_url] if args.article_url else None
    run_import(
        dry_run=args.dry_run,
        limit=args.limit or None,
        article_urls=urls,
        merge_existing=bool(args.article_url),
    )


if __name__ == "__main__":
    main()
