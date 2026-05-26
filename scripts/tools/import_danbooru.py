#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""Build a Danbooru tag dictionary YAML for sd-prompt-composer.

Sources:
- ``danbooru.csv`` from DominikDoom/a1111-sd-webui-tagcomplete (tag, type, count, aliases).
- ``danbooru-jp.csv`` from boorutan/booru-japanese-tag (hand-translated, ~400 entries).
- ``danbooru-machine-jp.csv`` from boorutan/booru-japanese-tag (machine-translated, ~100K).

Output: ``extensions/sd-prompt-composer/group_tags/danbooru.yaml`` organised by tag
type (general / meta / character / copyright) and post-count tier.
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
import urllib.request
from typing import Dict, List, Optional, Tuple

import yaml

_TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
_SCRIPT_DIR = os.path.dirname(_TOOLS_DIR)
for _p in (_SCRIPT_DIR, _TOOLS_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

USER_AGENT = "PromptComposerImporter/1.0 (personal local import)"

TAG_CSV_URL = "https://raw.githubusercontent.com/DominikDoom/a1111-sd-webui-tagcomplete/main/tags/danbooru.csv"
JP_HAND_URL = "https://raw.githubusercontent.com/boorutan/booru-japanese-tag/main/danbooru-jp.csv"
JP_MACHINE_URL = "https://raw.githubusercontent.com/boorutan/booru-japanese-tag/main/danbooru-machine-jp.csv"

TAG_TYPES = {0: "general", 1: "artist", 3: "copyright", 4: "character", 5: "meta"}

CACHE_DIR = "/tmp/pc-tag-import"


def fetch(url: str, dest: str, force: bool = False) -> str:
    if not force and os.path.isfile(dest) and os.path.getsize(dest) > 0:
        return dest
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = resp.read()
    with open(dest, "wb") as f:
        f.write(data)
    return dest


def load_translations(path: str) -> Dict[str, str]:
    out: Dict[str, str] = {}
    if not os.path.isfile(path):
        return out
    with open(path, encoding="utf-8") as f:
        for row in csv.reader(f):
            if len(row) < 2:
                continue
            tag, jp = row[0].strip(), row[1].strip()
            if tag and jp:
                out[tag] = jp
    return out


def load_tags(path: str) -> List[Tuple[str, int, int, str]]:
    rows: List[Tuple[str, int, int, str]] = []
    with open(path, encoding="utf-8") as f:
        for row in csv.reader(f):
            if not row:
                continue
            try:
                tag = row[0].strip()
                typ = int(row[1])
                cnt = int(row[2])
            except (IndexError, ValueError):
                continue
            aliases = row[3] if len(row) > 3 else ""
            if not tag:
                continue
            rows.append((tag, typ, cnt, aliases))
    return rows


def count_tier_general(count: int) -> Optional[str]:
    if count >= 10000:
        return "★★★ 超頻出 (10K+)"
    if count >= 1000:
        return "★★ 頻出 (1K-10K)"
    if count >= 100:
        return "★ 標準 (100-1K)"
    return None


def count_tier_character(count: int) -> Optional[str]:
    if count >= 5000:
        return "★★★ 大人気 (5K+)"
    if count >= 1000:
        return "★★ 人気 (1K-5K)"
    if count >= 500:
        return "★ 主要 (500-1K)"
    return None


def count_tier_copyright(count: int) -> Optional[str]:
    if count >= 5000:
        return "★★★ 大人気 (5K+)"
    if count >= 1000:
        return "★★ 人気 (1K-5K)"
    if count >= 500:
        return "★ 主要 (500-1K)"
    return None


def count_tier_meta(count: int) -> Optional[str]:
    if count >= 1000:
        return "★★ 主要 (1K+)"
    if count >= 100:
        return "★ 一般 (100-1K)"
    return None


TIER_FUNCS = {
    "general": count_tier_general,
    "character": count_tier_character,
    "copyright": count_tier_copyright,
    "meta": count_tier_meta,
}

CATEGORY_LABELS = {
    "general": "一般タグ",
    "meta": "メタタグ（品質・構図）",
    "character": "キャラクター",
    "copyright": "作品名",
}


def build_yaml(
    rows: List[Tuple[str, int, int, str]],
    jp_hand: Dict[str, str],
    jp_machine: Dict[str, str],
    *,
    include_artist: bool = False,
) -> List[Dict]:
    categories: Dict[str, Dict] = {}
    for tag, typ, count, _aliases in rows:
        type_label = TAG_TYPES.get(typ)
        if not type_label:
            continue
        if type_label == "artist" and not include_artist:
            continue
        tier_func = TIER_FUNCS.get(type_label)
        if not tier_func:
            continue
        tier = tier_func(count)
        if not tier:
            continue

        cat_label = CATEGORY_LABELS.get(type_label, type_label)
        cat = categories.setdefault(
            cat_label, {"name": cat_label, "_groups": {}}
        )
        group_label = tier
        group = cat["_groups"].setdefault(group_label, {"name": group_label, "tags": {}})

        jp = jp_hand.get(tag) or jp_machine.get(tag) or ""
        # safe_dump preserves underscores fine; keep tag key as-is (Danbooru uses '_')
        if not jp:
            group["tags"][tag] = tag
        else:
            group["tags"][tag] = jp

    cat_order = ["一般タグ", "メタタグ（品質・構図）", "キャラクター", "作品名"]
    ordered_categories: List[Dict] = []
    for cat_name in cat_order:
        cat = categories.get(cat_name)
        if not cat:
            continue
        groups_sorted = sorted(
            cat["_groups"].values(),
            key=lambda g: (g["name"].count("★") * -1, g["name"]),
        )
        for g in groups_sorted:
            g["tags"] = dict(sorted(g["tags"].items(), key=lambda kv: kv[0].lower()))
        ordered_categories.append({"name": cat_name, "groups": groups_sorted})

    return [{"name": "Danbooru", "categories": ordered_categories}]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=os.path.join(_SCRIPT_DIR, "..", "group_tags", "danbooru.yaml"))
    parser.add_argument("--cache", default=CACHE_DIR)
    parser.add_argument("--force", action="store_true", help="Re-download CSVs even if cached")
    parser.add_argument("--include-artist", action="store_true")
    args = parser.parse_args()

    tag_csv = fetch(TAG_CSV_URL, os.path.join(args.cache, "danbooru.csv"), force=args.force)
    jp_hand_csv = fetch(JP_HAND_URL, os.path.join(args.cache, "danbooru-jp.csv"), force=args.force)
    jp_mach_csv = fetch(JP_MACHINE_URL, os.path.join(args.cache, "danbooru-machine-jp.csv"), force=args.force)

    rows = load_tags(tag_csv)
    jp_hand = load_translations(jp_hand_csv)
    jp_mach = load_translations(jp_mach_csv)
    print(f"[danbooru-import] loaded: tags={len(rows)} jp_hand={len(jp_hand)} jp_machine={len(jp_mach)}")

    data = build_yaml(rows, jp_hand, jp_mach, include_artist=args.include_artist)

    total = 0
    for s in data:
        for c in s.get("categories") or []:
            for g in c.get("groups") or []:
                total += len(g.get("tags") or {})
    print(f"[danbooru-import] selected tags: {total}")

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
    print(f"[danbooru-import] wrote: {out_path}")


if __name__ == "__main__":
    main()
