#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""Fetch fallback preview images from Safebooru for prompt tags missing previews.

Strategy:
- Iterate group_tags YAML; collect tags without an existing preview file.
- Skip tags with non-ASCII, very long, or weight-syntax (parentheses) content.
- For each tag, query Safebooru with progressively relaxed token combinations
  (full tag → first/last pair → trailing token), then download the first sample
  image and convert to webp.
- Sleep ``REQUEST_DELAY`` between queries to be polite.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import time
import json
import urllib.error
import urllib.parse
import urllib.request
from typing import List, Optional, Tuple

import yaml

_TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
_SCRIPT_DIR = os.path.dirname(_TOOLS_DIR)
for _p in (_SCRIPT_DIR, _TOOLS_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import preview_convert
import preview_filenames
import user_storage

USER_AGENT = "Mozilla/5.0 (PromptComposer personal fill)"
SAFEBOORU_URL = "https://safebooru.org/index.php"
REQUEST_DELAY = 0.7  # be polite
DEFAULT_LIMIT = 0  # 0 = no limit (process all)
DEFAULT_OFFSET = 0


_BAD_CHARS = re.compile(r"[\(\)\[\]\{\}:：；;]|[0-9]+(?:\.[0-9]+)?$")
_ASCII_RE = re.compile(r"^[\x20-\x7e,_\- ]+$")
MAX_TAG_LEN = 60


def is_simple_searchable_tag(tag: str) -> bool:
    if not tag or not _ASCII_RE.match(tag):
        return False
    if len(tag) > MAX_TAG_LEN:
        return False
    if "(" in tag or ")" in tag or "[" in tag or "]" in tag or ":" in tag or "：" in tag:
        return False
    return True


def normalize_token(token: str) -> str:
    t = token.strip().strip(",").strip().replace(" ", "_")
    t = re.sub(r"_+", "_", t)
    t = t.lower()
    return t


def split_tokens(tag: str) -> List[str]:
    parts = []
    for chunk in tag.split(","):
        nt = normalize_token(chunk)
        if nt:
            parts.append(nt)
    return parts


def has_preview(previews_dir: str, tag: str) -> bool:
    for v in preview_filenames.preview_lookup_variants(tag):
        for ext in (".webp", ".png", ".jpg", ".jpeg", ".gif"):
            p = os.path.join(previews_dir, preview_filenames.tag_to_preview_basename(v) + ext)
            if os.path.isfile(p) and os.path.getsize(p) > 0:
                return True
    return False


def collect_missing(yaml_path: str, previews_dir: str) -> List[str]:
    data = yaml.safe_load(open(yaml_path, "r", encoding="utf-8"))
    out: List[str] = []
    seen = set()
    for section in data or []:
        for cat in section.get("categories") or []:
            for group in cat.get("groups") or []:
                for tag in (group.get("tags") or {}).keys():
                    if tag in seen:
                        continue
                    seen.add(tag)
                    if not is_simple_searchable_tag(tag):
                        continue
                    if has_preview(previews_dir, tag):
                        continue
                    out.append(tag)
    return out


QUERY_ERR = "error"
QUERY_EMPTY = "empty"


def _safebooru_call(query: str, timeout: int = 25) -> Tuple[str, Optional[List[dict]]]:
    params = {
        "page": "dapi",
        "s": "post",
        "q": "index",
        "json": "1",
        "tags": query,
        "limit": "5",
    }
    url = f"{SAFEBOORU_URL}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace").strip()
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError):
        return QUERY_ERR, None
    if not raw or raw.startswith("<"):
        return QUERY_EMPTY, None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return QUERY_EMPTY, None
    if not isinstance(data, list) or not data:
        return QUERY_EMPTY, None
    return "ok", data


def _candidate_queries(tokens: List[str]) -> List[str]:
    """Generate progressively relaxed Safebooru queries for a tag."""
    if not tokens:
        return []
    queries: List[str] = []
    seen: set[str] = set()

    def add(q: str) -> None:
        q = q.strip()
        if q and q not in seen:
            seen.add(q)
            queries.append(q)

    if len(tokens) == 1:
        tok = tokens[0]
        add(tok)
        parts = tok.split("_")
        if len(parts) >= 3:
            add(" ".join(parts[-2:]))
            add("_".join(parts[-2:]))
            add(parts[-1])
        elif len(parts) == 2:
            add(parts[-1])
    else:
        add(" ".join(tokens[:2]))
        add(tokens[0])
        if tokens[-1] != tokens[0]:
            add(tokens[-1])
    return queries


def search_for_tag(tokens: List[str], delay: float = REQUEST_DELAY) -> Tuple[str, Optional[dict]]:
    """Return (status, post_dict) where status in ('ok', 'no_result', 'error')."""
    if not tokens:
        return "no_result", None
    saw_error = False
    for query in _candidate_queries(tokens):
        status, data = _safebooru_call(query)
        time.sleep(delay)
        if status == "ok" and data:
            return "ok", data[0]
        if status == QUERY_ERR:
            saw_error = True
    return ("error" if saw_error else "no_result"), None


def pick_image_url(post: dict) -> str:
    """Return a downloadable image url from a Safebooru post dict."""
    for key in ("sample_url", "file_url", "preview_url"):
        url = post.get(key)
        if url and isinstance(url, str) and url.startswith("http"):
            return url
    image = post.get("image")
    directory = post.get("directory")
    if image and directory is not None:
        return f"https://safebooru.org/images/{directory}/{image}"
    return ""


def download_to_webp(image_url: str, dest_path: str, timeout: int = 60) -> bool:
    safe = urllib.parse.quote(image_url, safe=":/?&=%")
    req = urllib.request.Request(safe, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read()
    except (urllib.error.HTTPError, urllib.error.URLError) as e:
        return False
    return preview_convert.save_bytes_as_webp(data, dest_path)


def resolve_previews_dir(ext_dir: str) -> str:
    repo_root = os.path.dirname(os.path.dirname(ext_dir))
    candidate = os.path.join(repo_root, user_storage.USER_SUBDIR, "tag-previews")
    if os.path.isdir(candidate):
        return candidate
    return user_storage.tag_previews_dir(ext_dir)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--yaml",
        default=os.path.join(_SCRIPT_DIR, "..", "group_tags", "ai_nante.yaml"),
        help="YAML path (default ai_nante.yaml)",
    )
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT, help="0 = no limit")
    parser.add_argument("--offset", type=int, default=DEFAULT_OFFSET)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--delay", type=float, default=REQUEST_DELAY)
    args = parser.parse_args()

    ext_dir = os.path.dirname(_SCRIPT_DIR)
    previews_dir = resolve_previews_dir(ext_dir)
    yaml_path = os.path.abspath(args.yaml)
    print(f"[fetch-missing] previews_dir={previews_dir}")
    print(f"[fetch-missing] yaml={yaml_path}")

    missing = collect_missing(yaml_path, previews_dir)
    print(f"[fetch-missing] simple tags missing preview: {len(missing)}")

    todo = missing[args.offset :]
    if args.limit > 0:
        todo = todo[: args.limit]
    print(f"[fetch-missing] processing {len(todo)} tags (offset={args.offset}, limit={args.limit})")

    ok = 0
    skipped = 0
    failed_query = 0
    failed_download = 0
    no_result = 0

    for i, tag in enumerate(todo, 1):
        if has_preview(previews_dir, tag):
            skipped += 1
            continue
        tokens = split_tokens(tag)
        status, post = search_for_tag(tokens, delay=args.delay)
        if status == "error":
            failed_query += 1
            print(f"[{i}/{len(todo)}] {tag!r} -> query failed")
            continue
        if status == "no_result" or not post:
            no_result += 1
            print(f"[{i}/{len(todo)}] {tag!r} -> no results")
            continue
        url = pick_image_url(post)
        if not url:
            no_result += 1
            print(f"[{i}/{len(todo)}] {tag!r} -> post has no file_url")
            continue
        dest = preview_filenames.preview_path_for_tag(previews_dir, tag, ".webp")
        if args.dry_run:
            print(f"[{i}/{len(todo)}] {tag!r} -> would download {url}")
            ok += 1
            continue
        success = download_to_webp(url, dest)
        time.sleep(args.delay * 0.4)
        if success:
            ok += 1
            print(f"[{i}/{len(todo)}] {tag!r} -> {os.path.basename(dest)}")
        else:
            failed_download += 1
            print(f"[{i}/{len(todo)}] {tag!r} -> download failed: {url}")
        if i % 25 == 0:
            print(
                f"[progress {i}/{len(todo)}] ok={ok} no_result={no_result} "
                f"fail_q={failed_query} fail_dl={failed_download}"
            )

    print(
        "[fetch-missing] done:",
        {
            "downloaded": ok,
            "skipped_already": skipped,
            "no_result": no_result,
            "failed_query": failed_query,
            "failed_download": failed_download,
        },
    )


if __name__ == "__main__":
    main()
