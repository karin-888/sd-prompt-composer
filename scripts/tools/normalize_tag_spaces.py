#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""Replace half-width spaces with underscores in group_tags YAML tag keys."""

from __future__ import annotations

import argparse
import os
import sys
from typing import Any, Dict, List, Tuple

import yaml

_TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
_SCRIPT_DIR = os.path.dirname(_TOOLS_DIR)
for _p in (_SCRIPT_DIR, _TOOLS_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import tag_text_utils
import preview_filenames
import user_storage


def prompt_key(text: str) -> str:
    """Normalize spaces inside each comma-separated clause to '_' and keep ', ' between clauses."""
    raw = (text or "").strip()
    if not raw:
        return raw
    clauses = []
    for clause in raw.split(","):
        c = clause.strip().strip("_").replace(" ", "_")
        if c:
            clauses.append(c)
    return ", ".join(clauses)


def jp_score(tag: str, jp: str) -> int:
    return tag_text_utils.jp_quality_score(tag, jp or "")


def merge_tag_values(tag: str, a: Any, b: Any) -> Any:
    if a == b:
        return a
    jp_a = a if isinstance(a, str) else str((a or {}).get("jp") or "")
    jp_b = b if isinstance(b, str) else str((b or {}).get("jp") or "")
    if jp_score(tag, jp_a) >= jp_score(tag, jp_b):
        return a
    return b


def normalize_tags_map(tags: Dict[str, Any]) -> Tuple[Dict[str, Any], int]:
    out: Dict[str, Any] = {}
    changed = 0
    for key, value in (tags or {}).items():
        new_key = prompt_key(key)
        if new_key != key:
            changed += 1
        if new_key in out:
            out[new_key] = merge_tag_values(new_key, out[new_key], value)
        else:
            out[new_key] = value
    return out, changed


def normalize_yaml_data(data: list) -> int:
    changed = 0
    for section in data:
        for cat in section.get("categories") or []:
            for group in cat.get("groups") or []:
                tags = group.get("tags")
                if not isinstance(tags, dict):
                    continue
                new_tags, n = normalize_tags_map(tags)
                group["tags"] = dict(sorted(new_tags.items(), key=lambda kv: kv[0].lower()))
                changed += n
    return changed


def process_file(path: str, dry_run: bool = False) -> int:
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, list):
        return 0
    changed = normalize_yaml_data(data)
    if changed and not dry_run:
        with open(path, "w", encoding="utf-8") as f:
            yaml.safe_dump(
                data,
                f,
                allow_unicode=True,
                sort_keys=False,
                default_flow_style=False,
                width=120,
            )
    return changed


def main():
    parser = argparse.ArgumentParser(description="Replace spaces with underscores in group_tags tag keys")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--dir",
        default=os.path.join(_SCRIPT_DIR, "..", "group_tags"),
        help="group_tags directory",
    )
    parser.add_argument(
        "--skip-previews",
        action="store_true",
        help="Do not rename preview image files to match underscore tags",
    )
    args = parser.parse_args()
    group_dir = os.path.abspath(args.dir)
    total = 0
    for name in sorted(os.listdir(group_dir)):
        if not name.endswith(".yaml"):
            continue
        path = os.path.join(group_dir, name)
        n = process_file(path, dry_run=args.dry_run)
        print(f"{name}: {n} keys updated")
        total += n
    print(f"total keys updated: {total}")

    if not args.skip_previews and not args.dry_run:
        ext_dir = os.path.dirname(group_dir)
        repo_root = os.path.dirname(os.path.dirname(ext_dir))
        candidates = []
        seen = set()
        for path in (
            user_storage.tag_previews_dir(ext_dir),
            os.path.join(repo_root, user_storage.USER_SUBDIR, "tag-previews"),
            os.path.join(ext_dir, "data", "tag-previews"),
        ):
            norm = os.path.normpath(path)
            if norm in seen or not os.path.isdir(path):
                continue
            seen.add(norm)
            candidates.append(path)
        for previews_dir in candidates:
            stats = preview_filenames.migrate_space_preview_filenames(previews_dir)
            print(f"preview rename ({previews_dir}): {stats}")


if __name__ == "__main__":
    main()
