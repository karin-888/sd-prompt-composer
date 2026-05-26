#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""Replace noplog placeholder jp labels with dictionary translations."""

from __future__ import annotations

import argparse
import os
import sys

import yaml

_TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
_SCRIPT_DIR = os.path.dirname(_TOOLS_DIR)
for _p in (_SCRIPT_DIR, _TOOLS_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)
SCRIPT_DIR = _SCRIPT_DIR

import tag_text_utils


def _load_items(path: str) -> list[dict]:
    if not os.path.isfile(path):
        return []
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or []
    items: list[dict] = []
    for section in data:
        for cat in section.get("categories", []) or []:
            for group in cat.get("groups", []) or []:
                for tag, jp in (group.get("tags") or {}).items():
                    items.append({"tag": str(tag), "jp": str(jp or "")})
        for group in section.get("groups", []) or []:
            for tag, jp in (group.get("tags") or {}).items():
                items.append({"tag": str(tag), "jp": str(jp or "")})
    return items


def _rewrite_yaml(path: str, lookup: dict[str, str]) -> tuple[int, int]:
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or []

    changed = 0
    checked = 0
    for section in data:
        for cat in section.get("categories", []) or []:
            for group in cat.get("groups", []) or []:
                tags = group.get("tags") or {}
                for tag, jp in list(tags.items()):
                    checked += 1
                    old_jp = str(jp or "")
                    if not tag_text_utils.is_low_quality_jp(str(tag), old_jp):
                        continue
                    new_jp = tag_text_utils.resolve_jp_label(str(tag), old_jp, lookup)
                    if new_jp and new_jp != old_jp:
                        tags[tag] = new_jp
                        changed += 1
        for group in section.get("groups", []) or []:
            tags = group.get("tags") or {}
            for tag, jp in list(tags.items()):
                checked += 1
                old_jp = str(jp or "")
                if not tag_text_utils.is_low_quality_jp(str(tag), old_jp):
                    continue
                new_jp = tag_text_utils.resolve_jp_label(str(tag), old_jp, lookup)
                if new_jp and new_jp != old_jp:
                    tags[tag] = new_jp
                    changed += 1

    if changed:
        with open(path, "w", encoding="utf-8") as f:
            yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False, width=1000)
    return changed, checked


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--yaml",
        default=os.path.join(SCRIPT_DIR, "..", "group_tags", "noplog.yaml"),
        help="noplog yaml path to rewrite",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    group_dir = os.path.join(SCRIPT_DIR, "..", "group_tags")
    lookup_items: list[dict] = []
    for name in sorted(os.listdir(group_dir)):
        if not name.endswith(".yaml"):
            continue
        lookup_items.extend(_load_items(os.path.join(group_dir, name)))

    lookup = tag_text_utils.build_jp_lookup(lookup_items)
    if args.dry_run:
        changed = 0
        for item in _load_items(args.yaml):
            old = item["jp"]
            new = tag_text_utils.resolve_jp_label(item["tag"], old, lookup)
            if new != old:
                changed += 1
                print(f"{item['tag'][:60]}")
                print(f"  {old}")
                print(f"  -> {new}")
        print(f"Would change {changed} labels")
        return 0

    changed, checked = _rewrite_yaml(args.yaml, lookup)
    print(f"Updated {changed}/{checked} labels in {args.yaml}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
