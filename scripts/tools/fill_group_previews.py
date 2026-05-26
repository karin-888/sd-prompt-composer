#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""Fill missing tag previews by copying a representative image from the same group.

For each (category, group) in a group_tags YAML file, find any tag that already
has a preview file on disk and duplicate it to other tags in the same group that
have no preview yet. Useful for source articles that show one example image per
section but list many related prompts in a summary table.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from typing import Dict, List, Tuple

import yaml

_TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
_SCRIPT_DIR = os.path.dirname(_TOOLS_DIR)
for _p in (_SCRIPT_DIR, _TOOLS_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import preview_filenames
import user_storage


def resolve_previews_dirs(ext_dir: str) -> List[str]:
    repo_root = os.path.dirname(os.path.dirname(ext_dir))
    candidates = []
    seen = set()
    for path in (
        os.path.join(repo_root, user_storage.USER_SUBDIR, "tag-previews"),
        user_storage.tag_previews_dir(ext_dir),
        os.path.join(ext_dir, "data", "tag-previews"),
    ):
        norm = os.path.normpath(path)
        if norm in seen or not os.path.isdir(path):
            continue
        seen.add(norm)
        candidates.append(path)
    return candidates


def find_preview_file(previews_dir: str, tag: str) -> str:
    for variant in preview_filenames.preview_lookup_variants(tag):
        for ext in (".webp", ".png", ".jpg", ".jpeg", ".gif"):
            path = os.path.join(previews_dir, preview_filenames.tag_to_preview_basename(variant) + ext)
            if os.path.isfile(path) and os.path.getsize(path) > 0:
                return path
    return ""


def iter_groups(data) -> List[Tuple[str, str, str, Dict]]:
    """Yield (section_name, category_name, group_name, tags_dict)."""
    out = []
    for section in data or []:
        section_name = section.get("name") or ""
        for cat in section.get("categories") or []:
            cat_name = cat.get("name") or ""
            for group in cat.get("groups") or []:
                group_name = group.get("name") or ""
                tags = group.get("tags") or {}
                if isinstance(tags, dict):
                    out.append((section_name, cat_name, group_name, tags))
    return out


def fill_yaml(yaml_path: str, previews_dir: str, dry_run: bool = False) -> Dict[str, int]:
    stats = {"groups": 0, "filled": 0, "skipped": 0, "no_source_group": 0}
    if not os.path.isfile(yaml_path):
        return stats
    with open(yaml_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    for _sec, _cat, _grp, tags in iter_groups(data):
        stats["groups"] += 1
        source_path = ""
        for tag in tags.keys():
            path = find_preview_file(previews_dir, tag)
            if path:
                source_path = path
                break
        if not source_path:
            stats["no_source_group"] += 1
            continue
        for tag in tags.keys():
            existing = find_preview_file(previews_dir, tag)
            if existing:
                stats["skipped"] += 1
                continue
            dest = preview_filenames.preview_path_for_tag(previews_dir, tag, ".webp")
            if os.path.normpath(dest) == os.path.normpath(source_path):
                stats["skipped"] += 1
                continue
            try:
                if not dry_run:
                    os.makedirs(os.path.dirname(dest), exist_ok=True)
                    shutil.copy2(source_path, dest)
                stats["filled"] += 1
            except OSError:
                pass
    return stats


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--yaml",
        default=os.path.join(_SCRIPT_DIR, "..", "group_tags", "ai_nante.yaml"),
        help="YAML file to process",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    ext_dir = os.path.dirname(_SCRIPT_DIR)
    yaml_path = os.path.abspath(args.yaml)
    dirs = resolve_previews_dirs(ext_dir)
    if not dirs:
        print("[fill-group-previews] no previews directory found")
        return
    for previews_dir in dirs:
        stats = fill_yaml(yaml_path, previews_dir, dry_run=args.dry_run)
        print(f"[fill-group-previews] {previews_dir}: {stats}")


if __name__ == "__main__":
    main()
