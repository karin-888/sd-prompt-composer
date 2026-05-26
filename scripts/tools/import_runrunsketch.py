# -*- coding: UTF-8 -*-
"""
Import tags and preview images from runrunsketch.net (プロンプト tag archive).

Usage:
  python import_runrunsketch.py [--dry-run] [--limit N] [--article-url URL]

Outputs:
  group_tags/runrunsketch.yaml
  {data_path}/sd-prompt-composer/tag-previews/{tag}.{ext}
  {data_path}/sd-prompt-composer/runrunsketch-import-manifest.json
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
TAG_BASE = "https://runrunsketch.net/tag/prompt/"
SECTION_NAME = "runrunsketch"
REQUEST_DELAY = 0.35
MAX_TAG_LEN = 120
MAX_TAG_COMMAS = 8

ENTRY_CARD_RE = re.compile(
    r'class="entry-card-wrap[^"]*"[\s\S]*?href="(https://runrunsketch\.net/[^"]+)"',
    re.IGNORECASE,
)
HEADING_RE = re.compile(r"<h([23])[^>]*>([\s\S]*?)</h\1>", re.IGNORECASE)
TABLE_RE = re.compile(r"<table[\s\S]*?</table>", re.IGNORECASE)
TR_RE = re.compile(r"<tr[^>]*>([\s\S]*?)</tr>", re.IGNORECASE)
TD_RE = re.compile(r"<t[dh][^>]*>([\s\S]*?)</t[dh]>", re.IGNORECASE)
IMG_TAG_RE = re.compile(r"<img([^>]+)>", re.IGNORECASE)
IMG_SRC_RE = re.compile(r'\ssrc="([^"]+)"', re.IGNORECASE)
IMG_ALT_RE = re.compile(r'\salt="([^"]*)"', re.IGNORECASE)
HEADING_PAIR_RE = re.compile(r"^(.+?)[：:]\s*(.+)$")
ALT_SPELL_RE = re.compile(r"【[^】]*呪文[^】]*】\s*(.+?)[：:]\s*(.+)$")
RELATED_PAIR_RE = re.compile(r"([\w][\w\s\-(),']*?)\s*（([^）]{1,60})）")
SKIP_TITLE_PARTS = (
    "Regional Prompter",
    "BREAK構文",
    "Eagle",
    "Interrogate",
    "解析する方法",
    "Stylesでプロンプト",
    "マルチキャラクタープロンプト",
    "プロンプト(呪文)のコツ",
    "強調」と「抑制",
)
SKIP_GROUP_NAMES = (
    "概要",
    "おわりに",
    "はじめに",
    "関連記事",
    "人気記事",
    "新着記事",
    "カテゴリー",
    "タグ",
    "コメント",
    "背景の修正方法",
    "背景がキマると絵に世界観が生まれる",
    "うまくいかないときは",
    "ポーズが決まるとキャラが輝く",
    "大量の生成画像の管理に困ったら",
)
SKIP_TAG_VALUES = {
    "copy",
    "プロンプト",
    "意味",
    "区分",
    "コピー",
}


def extension_dir() -> str:
    return os.path.dirname(_SCRIPT_DIR)


def strip_tags(text: str) -> str:
    return tag_text_utils.strip_html(text)


def is_plausible_tag(tag: str) -> bool:
    t = (tag or "").strip()
    if not t or len(t) > MAX_TAG_LEN:
        return False
    if t.count(",") > MAX_TAG_COMMAS:
        return False
    if t.lower() in SKIP_TAG_VALUES:
        return False
    if not tag_text_utils.looks_like_english_tag(t):
        return False
    if re.search(r"(になりがち|バリエーション|参考|解説|記事)", t):
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


def fetch(url: str, timeout: int = 60) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def normalize_image_url(url: str) -> str:
    url = (url or "").strip()
    if not url:
        return ""
    if re.search(r"-\d+x\d+(?=\.(webp|jpg|jpeg|png|gif)$)", url, re.IGNORECASE):
        url = re.sub(r"-\d+x\d+(?=\.(webp|jpg|jpeg|png|gif)$)", "", url, flags=re.IGNORECASE)
    return url


def list_tag_articles(max_pages: int = 8) -> List[str]:
    found: List[str] = []
    seen = set()
    for page in range(1, max_pages + 1):
        url = TAG_BASE if page == 1 else TAG_BASE + f"page/{page}/"
        try:
            html = fetch(url)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                break
            raise
        page_urls: List[str] = []
        for link in ENTRY_CARD_RE.findall(html):
            if "/tag/prompt" in link or link in seen:
                continue
            seen.add(link)
            page_urls.append(link.rstrip("/") + "/")
        if not page_urls and page > 1:
            break
        found.extend(page_urls)
        time.sleep(REQUEST_DELAY)
    return sorted(set(found))


def parse_title(html: str) -> str:
    m = re.search(r'<meta\s+property="og:title"\s+content="([^"]+)"', html, re.IGNORECASE)
    if m:
        title = unescape(m.group(1)).strip()
        title = re.sub(r"\s*\|\s*るんるんスケッチ\s*$", "", title)
        return title.strip()
    m = re.search(r"<title>([^<]+)</title>", html, re.IGNORECASE)
    if m:
        title = unescape(m.group(1)).strip()
        return re.sub(r"\s*\|\s*るんるんスケッチ\s*$", "", title).strip()
    return "未分類"


def should_skip_title(title: str) -> bool:
    return any(part in (title or "") for part in SKIP_TITLE_PARTS)


def extract_main_content(html: str) -> str:
    m = re.search(r'class="article-body[^"]*"[^>]*>([\s\S]*?)<footer', html, re.IGNORECASE)
    if m:
        return m.group(1)
    m = re.search(r'class="entry-content[^"]*"[^>]*>([\s\S]*?)<footer', html, re.IGNORECASE)
    if m:
        return m.group(1)
    return html


def split_by_headings(main_html: str) -> List[Tuple[str, str]]:
    chunks: List[Tuple[str, str]] = []
    matches = list(HEADING_RE.finditer(main_html))
    if not matches:
        return [("一覧", main_html)]

    if matches[0].start() > 0:
        chunks.append(("概要", main_html[: matches[0].start()]))

    for i, match in enumerate(matches):
        group = strip_tags(match.group(2)) or "一覧"
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(main_html)
        chunks.append((group, main_html[start:end]))
    return chunks


def parse_heading_pair(text: str) -> Optional[Tuple[str, str]]:
    text = strip_tags(text)
    m = HEADING_PAIR_RE.match(text)
    if not m:
        return None
    left, right = m.group(1).strip(), m.group(2).strip()
    tag, jp = tag_text_utils.normalize_tag_jp(left, right)
    if not is_plausible_tag(tag):
        return None
    if not jp:
        jp = tag
    return tag, jp


def parse_alt_spell(alt: str) -> Optional[Tuple[str, str]]:
    alt = unescape((alt or "").strip())
    if not alt or "呪文" not in alt:
        return None
    m = ALT_SPELL_RE.match(alt)
    if not m:
        return None
    tag, jp = tag_text_utils.normalize_tag_jp(m.group(1).strip(), m.group(2).strip())
    if not is_plausible_tag(tag):
        return None
    return tag, jp or tag


def parse_related_pairs(text: str) -> List[Tuple[str, str]]:
    items: List[Tuple[str, str]] = []
    if "関連" not in text:
        return items
    plain = strip_tags(text)
    for tag, jp in RELATED_PAIR_RE.findall(plain):
        tag, jp = tag_text_utils.normalize_tag_jp(tag.strip(), jp.strip())
        if is_plausible_tag(tag):
            items.append((tag, jp or tag))
    return items


def parse_table_rows(table_html: str) -> List[Tuple[str, str]]:
    rows: List[Tuple[str, str]] = []
    for tr in TR_RE.findall(table_html):
        if "<th" in tr.lower():
            continue
        cells = [strip_tags(c) for c in TD_RE.findall(tr)]
        if len(cells) < 2:
            continue
        tag, jp = tag_text_utils.normalize_tag_jp(cells[0], cells[1])
        if len(cells) >= 2:
            tag, jp = tag_text_utils.normalize_tag_jp(cells[1], cells[0])
            if not is_plausible_tag(tag):
                tag, jp = tag_text_utils.normalize_tag_jp(cells[0], cells[1])
        if not is_plausible_tag(tag):
            continue
        rows.append((tag, jp or tag))
    return rows


def parse_image_tags(chunk: str) -> List[Dict]:
    items: List[Dict] = []
    for img_attrs in IMG_TAG_RE.findall(chunk):
        alt_m = IMG_ALT_RE.search(img_attrs)
        src_m = IMG_SRC_RE.search(img_attrs)
        if not alt_m:
            continue
        parsed = parse_alt_spell(alt_m.group(1))
        if not parsed:
            continue
        tag, jp = parsed
        image_url = normalize_image_url(src_m.group(1)) if src_m else ""
        if image_url and not image_url.startswith("https://runrunsketch.net/wp-content/uploads/"):
            image_url = ""
        items.append({"tag": tag, "jp": jp, "image_url": image_url})
    return items


def parse_chunk(group_name: str, chunk: str, heading_text: str = "") -> List[Dict]:
    items: List[Dict] = []

    if heading_text:
        parsed = parse_heading_pair(heading_text)
        if parsed:
            tag, jp = parsed
            image_url = ""
            src_m = IMG_SRC_RE.search(chunk[:4000])
            if src_m:
                image_url = normalize_image_url(src_m.group(1))
            items.append({"tag": tag, "jp": jp, "image_url": image_url, "group": group_name})

    items.extend({**item, "group": group_name} for item in parse_image_tags(chunk))

    for table_html in TABLE_RE.findall(chunk):
        for tag, jp in parse_table_rows(table_html):
            items.append({"tag": tag, "jp": jp, "image_url": "", "group": group_name})

    for tag, jp in parse_related_pairs(chunk):
        items.append({"tag": tag, "jp": jp, "image_url": "", "group": group_name})

    return items


def parse_article(url: str, html: str) -> Dict:
    title = parse_title(html)
    if should_skip_title(title):
        return {"title": title, "url": url, "entries": [], "skipped": True}

    main = extract_main_content(html)
    by_tag: Dict[str, Dict] = {}

    matches = list(HEADING_RE.finditer(main))
    if not matches:
        for entry in parse_chunk("一覧", main):
            _merge_entry(by_tag, entry, title, url)
    else:
        if matches[0].start() > 0:
            pre = main[: matches[0].start()]
            for entry in parse_chunk("概要", pre):
                _merge_entry(by_tag, entry, title, url)

        for i, match in enumerate(matches):
            group_name = strip_tags(match.group(2)) or "一覧"
            if group_name in SKIP_GROUP_NAMES:
                continue
            start = match.end()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(main)
            chunk = main[start:end]
            heading_text = strip_tags(match.group(2))
            for entry in parse_chunk(group_name, chunk, heading_text=heading_text):
                _merge_entry(by_tag, entry, title, url)

    entries = finalize_entries(list(by_tag.values()))
    return {
        "title": title,
        "url": url,
        "entries": entries,
        "skipped": len(entries) == 0,
    }


def _merge_entry(by_tag: Dict[str, Dict], entry: Dict, article_title: str, url: str) -> None:
    tag = (entry.get("tag") or "").strip()
    if not tag:
        return
    tag, jp = tag_text_utils.normalize_tag_jp(tag, entry.get("jp") or "")
    jp = tag_text_utils.sanitize_tag_jp(tag, jp) or jp or tag
    rec = by_tag.get(tag) or {
        "tag": tag,
        "jp": "",
        "image_url": "",
        "group": entry.get("group") or "一覧",
        "article": article_title,
        "source_url": url,
    }
    if jp and (
        not rec.get("jp")
        or tag_text_utils.jp_quality_score(tag, jp) > tag_text_utils.jp_quality_score(tag, rec.get("jp") or "")
    ):
        rec["jp"] = jp
    if entry.get("image_url") and not rec.get("image_url"):
        rec["image_url"] = entry["image_url"]
    if entry.get("group"):
        rec["group"] = entry["group"]
    by_tag[tag] = rec


def finalize_entries(entries: List[Dict]) -> List[Dict]:
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
        inherited = image_by_tag.get(tag_l) or image_by_tag.get(first)
        if not inherited:
            for key, url in image_by_tag.items():
                if tag_l.startswith(key + ","):
                    inherited = url
                    break
        if inherited:
            entry["image_url"] = inherited
    return entries


def copy_related_previews(previews_dir: str, entries: List[Dict]) -> int:
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
        dest = preview_filenames.preview_path_for_tag(previews_dir, tag, ".webp")
        if os.path.isfile(dest):
            existing[tag.lower()] = dest
            continue
        try:
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            if ext.lower() == ".webp":
                shutil.copy2(src, dest)
            else:
                preview_convert.save_image_as_webp(src, dest)
            existing[tag.lower()] = dest
            copied += 1
        except OSError:
            pass
    return copied


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
    req = urllib.request.Request(safe_url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = resp.read()
        return preview_convert.save_bytes_as_webp(data, dest_path)
    except Exception as e:
        print(f"  [warn] image download failed: {image_url} ({e})")
        return False


def build_yaml_structure(articles: List[Dict]) -> List[Dict]:
    categories: Dict[str, Dict] = {}
    for article in articles:
        if not article.get("entries"):
            continue
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


def run_import(
    dry_run: bool = False,
    limit: Optional[int] = None,
    article_urls: Optional[List[str]] = None,
) -> Dict:
    ext_dir = extension_dir()
    previews_dir = resolve_previews_dir(ext_dir)
    yaml_path = os.path.join(ext_dir, "group_tags", "runrunsketch.yaml")
    manifest_path = user_storage.bootstrap_json(ext_dir, "runrunsketch-import-manifest.json")

    if article_urls is None:
        article_urls = list_tag_articles()
    if limit:
        article_urls = article_urls[:limit]

    print(f"[runrunsketch import] articles: {len(article_urls)}")
    parsed_articles: List[Dict] = []
    all_entries: List[Dict] = []
    skipped_articles = 0
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
        if article.get("skipped"):
            skipped_articles += 1
            print(f"  skipped: {article['title']}")
            continue
        parsed_articles.append(article)
        print(f"  title: {article['title']}  tags: {len(article['entries'])}")

        for entry in article["entries"]:
            all_entries.append(entry)
            image_url = entry.get("image_url") or ""
            if not image_url:
                continue
            dest = preview_filenames.preview_path_for_tag(previews_dir, entry["tag"], ".webp")
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
            print(f"[runrunsketch import] copied {preview_copied} related preview files for compound tags")

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
            print(f"[runrunsketch import] preview migration: {mig}")

        manifest = {
            "imported_at": time.time(),
            "source_category": TAG_BASE,
            "article_count": len(parsed_articles),
            "skipped_articles": skipped_articles,
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
        "skipped_articles": skipped_articles,
        "tags": tag_count,
        "with_image_url": with_image,
        "images_ok": images_ok,
        "images_fail": images_fail,
        "yaml_path": yaml_path,
        "previews_dir": previews_dir,
    }
    print("[runrunsketch import] done:", summary)
    return summary


def main():
    parser = argparse.ArgumentParser(description="Import runrunsketch.net prompt tags and preview images")
    parser.add_argument("--dry-run", action="store_true", help="Parse only; do not write files")
    parser.add_argument("--limit", type=int, default=0, help="Limit number of articles (debug)")
    parser.add_argument(
        "--article-url",
        action="append",
        default=[],
        help="Import a single article URL (repeatable)",
    )
    args = parser.parse_args()
    article_urls = args.article_url or None
    run_import(dry_run=args.dry_run, limit=args.limit or None, article_urls=article_urls)


if __name__ == "__main__":
    main()
