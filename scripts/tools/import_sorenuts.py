# -*- coding: UTF-8 -*-
"""
Import tags (prompt + Japanese label) from sorenuts.jp prompt list articles.

SoreNuts tables use a 4-column layout: JP description | EN tag | JP description | EN tag.
Preview images are not available on these pages, so only text is imported.

Usage:
  python import_sorenuts.py [--dry-run] [--limit N] [--article-url URL]

Outputs:
  group_tags/sorenuts.yaml
  {data_path}/sd-prompt-composer/sorenuts-import-manifest.json
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
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

USER_AGENT = "PromptComposerImporter/1.0 (personal local import)"
CATEGORY_BASE = "https://sorenuts.jp/category/prompts/"
SECTION_NAME = "sorenuts"
REQUEST_DELAY = 0.35
MAX_TAG_LEN = 200
MAX_TAG_COMMAS = 12

SKIP_TITLE_PARTS = (
    "タグ管理ツール",
    "プロンプト完全ガイド",
)

SKIP_GROUP_NAMES = (
    "概要",
    "タグ管理ツール移動しました",
    "おわりに",
    "はじめに",
)

SKIP_TAG_VALUES = {
    "?",
    "??",
    "!",
    "!!",
    "!?",
    "…",
    "…?",
    "copy",
    "プロンプト",
    "意味",
    "区分",
    "コピー",
}

HEADING_RE = re.compile(r"<h([23])[^>]*>([\s\S]*?)</h\1>", re.IGNORECASE)
TABLE_RE = re.compile(r"<table[\s\S]*?</table>", re.IGNORECASE)
TR_RE = re.compile(r"<tr[^>]*>([\s\S]*?)</tr>", re.IGNORECASE)
TD_RE = re.compile(r"<t[dh][^>]*>([\s\S]*?)</t[dh]>", re.IGNORECASE)
ARTICLE_URL_RE = re.compile(r"https://sorenuts\.jp/\d+/?$", re.IGNORECASE)
HEADER_EMOJI_RE = re.compile(r"[\U0001F300-\U0001FAFF\U00002600-\U000027BF]+")


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
    if t.lower() in SKIP_TAG_VALUES or t in SKIP_TAG_VALUES:
        return False
    if not tag_text_utils.looks_like_english_tag(t):
        return False
    if re.fullmatch(r"[\W_]+", t):
        return False
    return True


def short_jp_label(jp_cell: str, tag: str) -> str:
    jp = (jp_cell or "").strip()
    if not jp:
        return tag
    jp = re.split(r"\s*・|\s*タグ使用", jp, maxsplit=1)[0].strip()
    jp = HEADER_EMOJI_RE.sub("", jp).strip()
    if len(jp) > 60:
        cut = jp[:60]
        if "、" in cut:
            jp = cut.rsplit("、", 1)[0]
        else:
            jp = cut
    return jp or tag


def fetch(url: str, timeout: int = 60) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def should_skip_title(title: str) -> bool:
    return any(part in (title or "") for part in SKIP_TITLE_PARTS)


def is_article_url(url: str) -> bool:
    if not url.startswith("https://sorenuts.jp/"):
        return False
    return bool(ARTICLE_URL_RE.match(url.rstrip("/") + "/"))


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
        links = re.findall(r'href="(https://sorenuts\.jp/\d+/)"', html, flags=re.IGNORECASE)
        page_urls = []
        for link in links:
            link = link.rstrip("/") + "/"
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
        return unescape(m.group(1)).strip()
    m = re.search(r"<title>([^<]+)</title>", html, re.IGNORECASE)
    if m:
        title = unescape(m.group(1)).strip()
        return re.sub(r"\s*\|\s*SoreNuts\s*$", "", title).strip()
    return "未分類"


def extract_main_content(html: str) -> str:
    m = re.search(
        r'class="post_content"[^>]*>([\s\S]*?)<div class="w-singleBottom"',
        html,
        re.IGNORECASE,
    )
    return m.group(1) if m else html


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


def clean_table_group_name(name: str) -> str:
    name = HEADER_EMOJI_RE.sub("", name or "").strip()
    name = re.sub(r"\s*・\s*Danbooru語.*$", "", name, flags=re.IGNORECASE).strip()
    return name or "一覧"


def parse_table_rows(table_html: str, group_name: str) -> List[Tuple[str, str, str]]:
    rows: List[Tuple[str, str, str]] = []
    sub_group = group_name

    for tr in TR_RE.findall(table_html):
        cells = [strip_tags(c) for c in TD_RE.findall(tr)]
        if not cells:
            continue

        is_header = "<th" in tr.lower()
        if is_header and len(cells) == 1:
            sub_group = clean_table_group_name(cells[0])
            continue
        if is_header:
            continue

        pairs: List[Tuple[str, str]] = []
        if len(cells) >= 2:
            pairs.append((cells[0], cells[1]))
        if len(cells) >= 4:
            pairs.append((cells[2], cells[3]))

        for jp_cell, tag in pairs:
            tag = (tag or "").strip()
            tag, jp_cell = tag_text_utils.normalize_tag_jp(tag, jp_cell)
            if not is_plausible_tag(tag):
                continue
            jp = short_jp_label(jp_cell, tag)
            jp = tag_text_utils.sanitize_tag_jp(tag, jp) or jp
            rows.append((tag, jp, sub_group))

    return rows


def parse_article(url: str, html: str) -> Dict:
    title = parse_title(html)
    entries: List[Dict] = []
    by_tag: Dict[str, Dict] = {}

    if should_skip_title(title):
        return {"title": title, "url": url, "entries": [], "skipped": True}

    main = extract_main_content(html)
    for group_name, chunk in split_by_headings(main):
        if group_name in SKIP_GROUP_NAMES:
            continue
        for table_html in TABLE_RE.findall(chunk):
            for tag, jp, sub_group in parse_table_rows(table_html, group_name):
                tag, jp = tag_text_utils.normalize_tag_jp(tag, jp)
                rec = by_tag.get(tag) or {
                    "tag": tag,
                    "jp": "",
                    "group": sub_group,
                    "article": title,
                    "source_url": url,
                }
                if jp and not rec.get("jp"):
                    rec["jp"] = jp
                elif jp and tag_text_utils.jp_quality_score(tag, jp) > tag_text_utils.jp_quality_score(
                    tag, rec.get("jp") or ""
                ):
                    rec["jp"] = jp
                rec["group"] = sub_group
                by_tag[tag] = rec

    entries = list(by_tag.values())
    for entry in entries:
        if not entry.get("jp"):
            entry["jp"] = entry["tag"]
    return {"title": title, "url": url, "entries": entries, "skipped": False}


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
    yaml_path = os.path.join(ext_dir, "group_tags", "sorenuts.yaml")
    manifest_path = user_storage.bootstrap_json(ext_dir, "sorenuts-import-manifest.json")

    if article_urls is None:
        article_urls = list_category_articles()
    if limit:
        article_urls = article_urls[:limit]

    print(f"[sorenuts import] articles: {len(article_urls)}")
    parsed_articles: List[Dict] = []
    all_entries: List[Dict] = []
    skipped_articles = 0

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
        all_entries.extend(article["entries"])
        print(f"  title: {article['title']}  tags: {len(article['entries'])}")
        time.sleep(REQUEST_DELAY)

    yaml_data = build_yaml_structure(parsed_articles)
    tag_count = len({e["tag"] for e in all_entries})

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
            "skipped_articles": skipped_articles,
            "tag_count": tag_count,
            "yaml_path": yaml_path,
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
        "yaml_path": yaml_path,
    }
    print("[sorenuts import] done:", summary)
    return summary


def main():
    parser = argparse.ArgumentParser(description="Import sorenuts.jp prompt tags (text only)")
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
