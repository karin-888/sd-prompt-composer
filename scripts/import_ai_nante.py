# -*- coding: UTF-8 -*-
"""
Import tags and preview images from ai-nante.com (美少女イラスト設計 category).

Usage:
  python import_ai_nante.py [--dry-run] [--limit N]

Outputs:
  group_tags/ai_nante.yaml
  {data_path}/sd-prompt-composer/tag-previews/{tag}.{ext}
  {data_path}/sd-prompt-composer/ai-nante-import-manifest.json
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from html import unescape
from typing import Dict, List, Optional, Tuple

import yaml

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

import user_storage
import tag_text_utils
import preview_filenames

USER_AGENT = "PromptComposerImporter/1.0 (personal local import)"
CATEGORY_BASE = "https://ai-nante.com/category/ai-image-generator/girl-art-design/"
SECTION_NAME = "ai-nante"
REQUEST_DELAY = 0.35
MAX_TAG_LEN = 120
MAX_TAG_COMMAS = 8


def is_plausible_tag(tag: str) -> bool:
    t = (tag or "").strip()
    if not t or len(t) > MAX_TAG_LEN:
        return False
    if t.count(",") > MAX_TAG_COMMAS:
        return False
    return True


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

SKIP_URL_PARTS = (
    "/category/",
    "/tag/",
    "/page/",
    "/comments/",
    "contact-form",
    "privacy-policy",
    "sitemap",
    "profile-ai-tools",
    "basic-prompts-list",
    "/feed",
)

CARD_RE = re.compile(
    r"(?:<p[^>]*>(?P<jp>[^<]+)</p>\s*)?"
    r"<figure[^>]*>.*?<img(?P<imgattrs>[^>]+)>.*?</figure>\s*"
    r"<p[^>]*>(?P<tagbody>[\s\S]*?)</p>",
    re.DOTALL | re.IGNORECASE,
)

IMG_SRC_RE = re.compile(r'\ssrc="([^"]+)"', re.IGNORECASE)
IMG_ALT_RE = re.compile(r'\salt="([^"]*)"', re.IGNORECASE)

TABLE_RE = re.compile(r"<table[\s\S]*?</table>", re.IGNORECASE)
TR_RE = re.compile(r"<tr>([\s\S]*?)</tr>", re.IGNORECASE)
TD_RE = re.compile(r"<td[^>]*>([\s\S]*?)</td>", re.IGNORECASE)
TH_RE = re.compile(r"<t[dh][^>]*>([\s\S]*?)</t[dh]>", re.IGNORECASE)
HEADING_RE = re.compile(r"<h([23])[^>]*>([\s\S]*?)</h\1>", re.IGNORECASE)


def extension_dir() -> str:
    return os.path.dirname(_SCRIPT_DIR)


def strip_tags(text: str) -> str:
    text = unescape(re.sub(r"<[^>]+>", " ", text or ""))
    return re.sub(r"\s+", " ", text).strip()


def fetch(url: str, timeout: int = 45) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def is_article_url(url: str) -> bool:
    if not url.startswith("https://ai-nante.com/"):
        return False
    return not any(part in url for part in SKIP_URL_PARTS)


def list_category_articles(max_pages: int = 12) -> List[str]:
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
        links = re.findall(r'href="(https://ai-nante\.com/[a-z0-9\-]+/)"', html, flags=re.IGNORECASE)
        page_urls = []
        for link in links:
            if not is_article_url(link) or link in seen:
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
        title = re.sub(r"\s*\|\s*で、AIはなんて？.*$", "", title)
        return title.strip()
    m = re.search(r"<title>([^<]+)</title>", html, re.IGNORECASE)
    if m:
        title = unescape(m.group(1)).strip()
        title = re.sub(r"\s*\|\s*で、AIはなんて？.*$", "", title)
        return title.strip()
    return "未分類"


def split_by_headings(html: str) -> List[Tuple[str, str]]:
    """Return [(group_name, chunk_html), ...]"""
    main = html
    m = re.search(r'<div[^>]+class="[^"]*entry-content[^"]*"[^>]*>', html, re.IGNORECASE)
    if m:
        start = m.end()
        end = html.find('<div class="c-share-buttons', start)
        if end == -1:
            end = html.find('<!-- /entry-content -->', start)
        if end == -1:
            end = len(html)
        main = html[start:end]

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


def strip_tags(text: str) -> str:
    return tag_text_utils.strip_html(text)


def parse_table_rows(table_html: str) -> List[Tuple[str, str, str]]:
    rows: List[Tuple[str, str, str]] = []
    tag_col, jp_col = 0, 1
    header_seen = False

    for tr in TR_RE.findall(table_html):
        if "<th" in tr.lower() or (not header_seen and "プロンプト" in tr):
            headers = [strip_tags(c) for c in TH_RE.findall(tr)]
            if headers:
                tag_col, jp_col = tag_text_utils.detect_table_columns(headers)
                header_seen = True
            if "<th" in tr.lower():
                continue

        cells = [strip_tags(c) for c in TD_RE.findall(tr)]
        if len(cells) < 2:
            continue

        tag = cells[tag_col].strip() if tag_col < len(cells) else ""
        jp = cells[jp_col].strip() if jp_col < len(cells) else ""
        memo = cells[2].strip() if len(cells) > 2 else ""
        tag, jp = tag_text_utils.normalize_tag_jp(tag, jp)

        if not tag or tag in ("プロンプト", "表情", "髪型の名称", "種類", "英語タグ例"):
            continue
        if not is_plausible_tag(tag):
            continue
        rows.append((tag, jp, memo))
    return rows


def parse_cards(chunk: str) -> List[Dict]:
    items: List[Dict] = []
    for jp, imgattrs, tagbody in CARD_RE.findall(chunk):
        src_m = IMG_SRC_RE.search(imgattrs or "")
        if not src_m:
            continue
        tag = strip_tags(tagbody)
        tag, jp_text = tag_text_utils.normalize_tag_jp(tag, strip_tags(jp) if jp else "")
        if not jp_text:
            alt_m = IMG_ALT_RE.search(imgattrs or "")
            if alt_m:
                jp_text = tag_text_utils.jp_from_img_alt(alt_m.group(1))
        if not is_plausible_tag(tag):
            continue
        items.append(
            {
                "tag": tag,
                "jp": jp_text,
                "image_url": src_m.group(1).strip(),
            }
        )
    return items


def parse_article(url: str, html: str) -> Dict:
    title = parse_title(html)
    entries: List[Dict] = []
    by_tag: Dict[str, Dict] = {}

    for group_name, chunk in split_by_headings(html):
        for card in parse_cards(chunk):
            tag = card["tag"]
            tag, jp = tag_text_utils.normalize_tag_jp(tag, card.get("jp") or "")
            rec = by_tag.get(tag) or {
                "tag": tag,
                "jp": jp,
                "image_url": "",
                "group": group_name,
                "article": title,
                "source_url": url,
            }
            if card.get("jp"):
                rec["jp"] = jp or card["jp"]
            if card.get("image_url"):
                rec["image_url"] = card["image_url"]
            rec["group"] = group_name
            by_tag[tag] = rec

        for table_html in TABLE_RE.findall(chunk):
            for tag, jp, _memo in parse_table_rows(table_html):
                tag, jp = tag_text_utils.normalize_tag_jp(tag, jp)
                rec = by_tag.get(tag) or {
                    "tag": tag,
                    "jp": "",
                    "image_url": "",
                    "group": group_name,
                    "article": title,
                    "source_url": url,
                }
                if jp and not rec.get("jp"):
                    rec["jp"] = jp
                rec["group"] = group_name
                by_tag[tag] = rec

    entries = list(by_tag.values())
    return {"title": title, "url": url, "entries": finalize_entries(entries)}


def finalize_entries(entries: List[Dict]) -> List[Dict]:
    """Copy card preview URLs onto related table variants in the same article."""
    image_by_tag: Dict[str, str] = {}
    for entry in entries:
        tag = (entry.get("tag") or "").strip()
        url = (entry.get("image_url") or "").strip()
        if not tag or not url:
            continue
        image_by_tag[tag.lower()] = url
        first = tag.split(",", 1)[0].strip().lower()
        image_by_tag.setdefault(first, url)

    for entry in entries:
        if (entry.get("image_url") or "").strip():
            continue
        tag = (entry.get("tag") or "").strip()
        if not tag:
            continue
        tag_l = tag.lower()
        first = tag.split(",", 1)[0].strip().lower()
        inherited = image_by_tag.get(first)
        if not inherited:
            for key, url in image_by_tag.items():
                if tag_l.startswith(key + ","):
                    inherited = url
                    break
        if inherited:
            entry["image_url"] = inherited
    return entries


def copy_related_previews(previews_dir: str, entries: List[Dict]) -> int:
    """Duplicate preview files for compound tags that inherit a card image."""
    copied = 0
    existing: Dict[str, str] = {}
    for entry in entries:
        tag = (entry.get("tag") or "").strip()
        if not tag:
            continue
        for ext in (".webp", ".png", ".jpg", ".jpeg", ".gif"):
            path = preview_filenames.preview_path_for_tag(previews_dir, tag, ext)
            if os.path.isfile(path):
                existing[tag.lower()] = path
                break

    for entry in entries:
        tag = (entry.get("tag") or "").strip()
        if not tag or tag.lower() in existing:
            continue
        src = existing.get(tag.split(",", 1)[0].strip().lower())
        if not src:
            for key, path in existing.items():
                if tag.lower().startswith(key + ","):
                    src = path
                    break
        if not src:
            continue
        ext = os.path.splitext(src)[1]
        dest = preview_filenames.preview_path_for_tag(previews_dir, tag, ext)
        if os.path.isfile(dest):
            existing[tag.lower()] = dest
            continue
        try:
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            shutil.copy2(src, dest)
            existing[tag.lower()] = dest
            copied += 1
        except OSError:
            pass
    return copied


def preview_path_for_tag(previews_dir: str, tag: str, image_url: str) -> str:
    ext = os.path.splitext(urllib.parse.urlparse(image_url).path)[1].lower()
    if ext not in (".webp", ".png", ".jpg", ".jpeg", ".gif"):
        ext = ".webp"
    return preview_filenames.preview_path_for_tag(previews_dir, tag, ext)


def _encode_request_url(url: str) -> str:
    parts = urllib.parse.urlsplit(url)
    path = urllib.parse.quote(parts.path, safe="/:%")
    return urllib.parse.urlunsplit((parts.scheme, parts.netloc, path, parts.query, parts.fragment))


def download_image(image_url: str, dest_path: str, dry_run: bool = False) -> bool:
    if os.path.isfile(dest_path) and os.path.getsize(dest_path) > 0:
        return True
    if dry_run:
        return True
    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
    safe_url = _encode_request_url(image_url)
    req = urllib.request.Request(safe_url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = resp.read()
        if len(data) < 128:
            return False
        with open(dest_path, "wb") as f:
            f.write(data)
        return True
    except Exception as e:
        print(f"  [warn] image download failed: {image_url} ({e})")
        return False


def build_yaml_structure(articles: List[Dict]) -> List[Dict]:
    categories: Dict[str, Dict] = {}
    for article in articles:
        cat_name = article["title"]
        cat = categories.setdefault(cat_name, {"name": cat_name, "groups": {}})
        groups = cat["groups"]
        for entry in article["entries"]:
            group_name = entry.get("group") or "一覧"
            grp = groups.setdefault(group_name, {"name": group_name, "tags": {}})
            tag = entry["tag"]
            jp = entry.get("jp") or tag
            grp["tags"][tag] = jp

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


def strip_ai_nante_from_default(ext_dir: str) -> int:
    """Remove embedded ai-nante section from default.yaml after import to ai_nante.yaml."""
    default_path = os.path.join(ext_dir, "group_tags", "default.yaml")
    if not os.path.isfile(default_path):
        return 0
    with open(default_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, list):
        return 0
    before = len(data)
    data = [section for section in data if (section or {}).get("name") != SECTION_NAME]
    removed = before - len(data)
    if removed:
        with open(default_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(
                data,
                f,
                allow_unicode=True,
                sort_keys=False,
                default_flow_style=False,
                width=120,
            )
    return removed


def run_import(dry_run: bool = False, limit: Optional[int] = None) -> Dict:
    ext_dir = extension_dir()
    previews_dir = resolve_previews_dir(ext_dir)
    yaml_path = os.path.join(ext_dir, "group_tags", "ai_nante.yaml")
    manifest_path = user_storage.bootstrap_json(ext_dir, "ai-nante-import-manifest.json")

    article_urls = list_category_articles()
    if limit:
        article_urls = article_urls[:limit]

    print(f"[ai-nante import] articles: {len(article_urls)}")
    parsed_articles: List[Dict] = []
    all_entries: List[Dict] = []
    images_ok = 0
    images_fail = 0

    for i, url in enumerate(article_urls, 1):
        print(f"[{i}/{len(article_urls)}] {url}")
        try:
            html = fetch(url)
        except Exception as e:
            print(f"  [error] fetch failed: {e}")
            continue
        article = parse_article(url, html)
        parsed_articles.append(article)
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
            time.sleep(REQUEST_DELAY * 0.5)

        time.sleep(REQUEST_DELAY)

    preview_copied = 0
    if not dry_run:
        preview_copied = copy_related_previews(previews_dir, all_entries)
        if preview_copied:
            print(f"[ai-nante import] copied {preview_copied} related preview files for compound tags")

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

        known_tags = {e["tag"] for e in all_entries}
        mig = preview_filenames.migrate_preview_files(previews_dir, known_tags=known_tags)
        if mig.get("migrated") or mig.get("removed_dirs"):
            print(f"[ai-nante import] preview migration: {mig}")

        removed_from_default = strip_ai_nante_from_default(ext_dir)
        if removed_from_default:
            print(f"[ai-nante import] removed ai-nante section from default.yaml ({removed_from_default} categories)")

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
    print("[ai-nante import] done:", summary)
    return summary


def main():
    parser = argparse.ArgumentParser(description="Import ai-nante.com tags and preview images")
    parser.add_argument("--dry-run", action="store_true", help="Parse only; do not write files")
    parser.add_argument("--limit", type=int, default=0, help="Limit number of articles (debug)")
    args = parser.parse_args()
    run_import(dry_run=args.dry_run, limit=args.limit or None)


if __name__ == "__main__":
    main()
