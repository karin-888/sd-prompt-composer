#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""Remove duplicate English tag keys across group_tags/*.yaml files.

Processing order matches tag_dictionary.load order:
  1. default.yaml
  2. remaining *.yaml files sorted alphabetically

The first occurrence of each tag (case-insensitive) is kept; later duplicates
are removed. Empty groups / categories / sections are pruned afterward.
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Dict, List, Set, Tuple

import yaml

_TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
_SCRIPT_DIR = os.path.dirname(_TOOLS_DIR)
for _p in (_SCRIPT_DIR, _TOOLS_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _tag_key(tag: str) -> str:
    return (tag or "").strip().lower()


def _yaml_paths(group_dir: str) -> List[str]:
    paths: List[str] = []
    default = os.path.join(group_dir, "default.yaml")
    if os.path.isfile(default):
        paths.append(default)
    for name in sorted(os.listdir(group_dir)):
        if not name.endswith(".yaml") or name == "default.yaml":
            continue
        path = os.path.join(group_dir, name)
        if os.path.isfile(path) and path not in paths:
            paths.append(path)
    return paths


def _prune_structure(data: List[Dict]) -> List[Dict]:
    out_sections: List[Dict] = []
    for sec in data:
        if not isinstance(sec, dict):
            continue
        cats_out: List[Dict] = []
        for cat in sec.get("categories") or []:
            if not isinstance(cat, dict):
                continue
            groups_out: List[Dict] = []
            for grp in cat.get("groups") or []:
                if not isinstance(grp, dict):
                    continue
                tags = grp.get("tags") or {}
                if not tags:
                    continue
                new_grp = dict(grp)
                new_grp["tags"] = tags
                groups_out.append(new_grp)
            if not groups_out:
                continue
            new_cat = dict(cat)
            new_cat["groups"] = groups_out
            cats_out.append(new_cat)
        if not cats_out:
            continue
        new_sec = dict(sec)
        new_sec["categories"] = cats_out
        out_sections.append(new_sec)
    return out_sections


def dedupe_file(
    path: str,
    seen: Set[str],
    dry_run: bool,
) -> Tuple[int, int, int]:
    """Return (before_count, after_count, removed_count)."""
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if not isinstance(data, list):
        return 0, 0, 0

    before = 0
    removed = 0

    for sec in data:
        for cat in sec.get("categories") or []:
            for grp in cat.get("groups") or []:
                tags: Dict = grp.get("tags") or {}
                before += len(tags)
                drop_keys: List[str] = []
                for key in tags:
                    nk = _tag_key(str(key))
                    if not nk:
                        drop_keys.append(key)
                        continue
                    if nk in seen:
                        drop_keys.append(key)
                        removed += 1
                    else:
                        seen.add(nk)
                for key in drop_keys:
                    tags.pop(key, None)

    after = before - removed
    pruned = _prune_structure(data)

    if not dry_run and removed > 0:
        with open(path, "w", encoding="utf-8") as f:
            yaml.safe_dump(
                pruned,
                f,
                allow_unicode=True,
                sort_keys=False,
                default_flow_style=False,
                width=200,
            )

    return before, after, removed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dir",
        default=os.path.join(_SCRIPT_DIR, "..", "group_tags"),
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    group_dir = os.path.abspath(args.dir)
    if not os.path.isdir(group_dir):
        print(f"[dedupe] not found: {group_dir}")
        raise SystemExit(1)

    paths = _yaml_paths(group_dir)
    seen: Set[str] = set()
    total_before = 0
    total_after = 0
    total_removed = 0

    for path in paths:
        before, after, removed = dedupe_file(path, seen, args.dry_run)
        total_before += before
        total_after += after
        total_removed += removed
        if removed:
            print(f"[dedupe] {os.path.basename(path)}: {before} -> {after} (-{removed})")

    print(
        f"[dedupe] total: {total_before} -> {total_after} "
        f"(removed {total_removed}, unique {len(seen)})"
    )
    if args.dry_run:
        print("[dedupe] dry-run: no files written")


if __name__ == "__main__":
    main()
