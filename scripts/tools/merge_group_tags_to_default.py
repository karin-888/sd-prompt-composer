#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""Merge all group_tags/*.yaml sections into default.yaml and remove the rest."""

from __future__ import annotations

import argparse
import copy
import os
import sys
from typing import Dict, List, Set

import yaml

_TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
_SCRIPT_DIR = os.path.dirname(_TOOLS_DIR)
for _p in (_SCRIPT_DIR, _TOOLS_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)


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


def _tag_key(tag: str) -> str:
    return (tag or "").strip().lower()


def _filter_sections(
    sections: List[Dict],
    seen: Set[str],
) -> List[Dict]:
    """Drop duplicate tag keys (keep first) and prune empty groups/categories."""
    out_sections: List[Dict] = []

    for sec in sections:
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
                src_tags: Dict = grp.get("tags") or {}
                tags_out: Dict = {}
                for key, value in src_tags.items():
                    nk = _tag_key(str(key))
                    if not nk or nk in seen:
                        continue
                    seen.add(nk)
                    tags_out[str(key)] = value
                if not tags_out:
                    continue
                new_grp = copy.deepcopy(grp)
                new_grp["tags"] = tags_out
                groups_out.append(new_grp)
            if not groups_out:
                continue
            new_cat = copy.deepcopy(cat)
            new_cat["groups"] = groups_out
            cats_out.append(new_cat)
        if not cats_out:
            continue
        new_sec = copy.deepcopy(sec)
        new_sec["categories"] = cats_out
        out_sections.append(new_sec)
    return out_sections


def _count_tags(sections: List[Dict]) -> int:
    n = 0
    for sec in sections:
        for cat in sec.get("categories") or []:
            for grp in cat.get("groups") or []:
                n += len(grp.get("tags") or {})
    return n


def merge_into_default(group_dir: str, dry_run: bool = False) -> None:
    paths = _yaml_paths(group_dir)
    if not paths or os.path.basename(paths[0]) != "default.yaml":
        print("[merge-default] default.yaml not found")
        raise SystemExit(1)

    default_path = paths[0]
    with open(default_path, "r", encoding="utf-8") as f:
        merged = yaml.safe_load(f) or []

    if not isinstance(merged, list):
        merged = []

    seen: Set[str] = set()
    for sec in merged:
        for cat in sec.get("categories") or []:
            for grp in cat.get("groups") or []:
                for key in grp.get("tags") or {}:
                    nk = _tag_key(str(key))
                    if nk:
                        seen.add(nk)

    before = _count_tags(merged)

    added_sections = 0
    for path in paths[1:]:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or []
        if not isinstance(data, list) or not data:
            continue
        filtered = _filter_sections(data, seen)
        if not filtered:
            continue
        merged.extend(filtered)
        added_sections += len(filtered)
        print(f"[merge-default] +{len(filtered)} section(s) from {os.path.basename(path)}")

    after = _count_tags(merged)
    print(f"[merge-default] tags: {before} -> {after} (+{after - before})")
    print(f"[merge-default] sections total: {len(merged)}")

    if dry_run:
        print("[merge-default] dry-run: no files changed")
        return

    with open(default_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(
            merged,
            f,
            allow_unicode=True,
            sort_keys=False,
            default_flow_style=False,
            width=200,
        )

    removed_files = 0
    for path in paths[1:]:
        os.remove(path)
        removed_files += 1
        print(f"[merge-default] removed {os.path.basename(path)}")

    print(f"[merge-default] wrote {default_path}, removed {removed_files} files")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dir",
        default=os.path.join(_SCRIPT_DIR, "..", "group_tags"),
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    merge_into_default(os.path.abspath(args.dir), dry_run=args.dry_run)


if __name__ == "__main__":
    main()
