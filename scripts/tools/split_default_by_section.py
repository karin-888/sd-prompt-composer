#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""Split group_tags/default.yaml into per-section YAML files for lazy loading.

Outputs:
  group_tags/sections/{idx:03d}_{slug}.yaml   one section per file (duplicate names merged)
  group_tags/manifest.json                   tree paths + section file map
  group_tags/search-index.pkl                lightweight global search index
"""

from __future__ import annotations

import argparse
import json
import os
import pickle
import re
import sys
from typing import Any, Dict, List, Tuple

import yaml

_TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
_SCRIPT_DIR = os.path.dirname(_TOOLS_DIR)
for _p in (_SCRIPT_DIR, _TOOLS_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

_PATH_SEP = "\x1f"


def _path_key(section: str, category: str = "", group: str = "") -> str:
    sec = (section or "").strip() or "(未分類)"
    cat = (category or "").strip()
    grp = (group or "").strip()
    parts = [sec]
    if cat:
        parts.append(cat)
        if grp:
            parts.append(grp)
    return _PATH_SEP.join(parts)


def _slugify(name: str, index: int) -> str:
    base = re.sub(r"[^\w\-]+", "_", (name or "section").strip(), flags=re.UNICODE)
    base = re.sub(r"_+", "_", base).strip("_").lower()[:72] or "section"
    return f"{index:03d}_{base}"


def _merge_sections(data: List[Dict]) -> List[Dict]:
    merged: Dict[str, Dict] = {}
    order: List[str] = []
    for sec in data:
        if not isinstance(sec, dict):
            continue
        name = (sec.get("name") or "").strip() or "(未分類)"
        if name not in merged:
            merged[name] = {"name": name, "categories": []}
            order.append(name)
        target = merged[name]
        for cat in sec.get("categories") or []:
            if not isinstance(cat, dict):
                continue
            target["categories"].append(cat)
    return [merged[name] for name in order]


def _collect_paths_and_index(section: Dict) -> Tuple[List[Dict], Dict[str, int], List[Dict], List[Dict]]:
    paths: List[Dict] = []
    path_counts: Dict[str, int] = {}
    search_rows: List[Dict] = []
    seen_paths = set()

    section_name = section.get("name") or ""
    for cat in section.get("categories") or []:
        if not isinstance(cat, dict):
            continue
        cat_name = cat.get("name") or ""
        for group in cat.get("groups") or []:
            if not isinstance(group, dict):
                continue
            group_name = group.get("name") or ""
            tags = group.get("tags") or {}
            if not tags:
                continue

            path_tuple = (section_name, cat_name, group_name)
            if path_tuple not in seen_paths:
                seen_paths.add(path_tuple)
                paths.append(
                    {
                        "section": section_name,
                        "category": cat_name,
                        "group": group_name,
                    }
                )

            keys = [_path_key(section_name)]
            if (cat_name or "").strip():
                keys.append(_path_key(section_name, cat_name))
                if (group_name or "").strip():
                    keys.append(_path_key(section_name, cat_name, group_name))
            for key in keys:
                path_counts[key] = path_counts.get(key, 0) + len(tags)

            for tag, value in tags.items():
                eng = str(tag)
                if isinstance(value, dict):
                    jp_text = str(value.get("jp") or value.get("label") or "")
                else:
                    jp_text = str(value) if value is not None else ""
                search_rows.append(
                    {
                        "tag": eng,
                        "jp": jp_text,
                        "section": section_name,
                        "category": cat_name,
                        "group": group_name,
                    }
                )

    path_entries = []
    for key, count in path_counts.items():
        parts = key.split(_PATH_SEP)
        sec = parts[0] if parts else "(未分類)"
        cat = parts[1] if len(parts) > 1 else ""
        grp = parts[2] if len(parts) > 2 else ""
        path_entries.append(
            {
                "section": sec,
                "category": cat,
                "group": grp,
                "count": count,
            }
        )

    return paths, path_counts, path_entries, search_rows


def split_default(
    default_path: str,
    group_tags_dir: str,
    *,
    backup: bool = True,
) -> Dict[str, Any]:
    with open(default_path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or []

    sections = _merge_sections(data)
    sections_dir = os.path.join(group_tags_dir, "sections")
    os.makedirs(sections_dir, exist_ok=True)

    manifest_sections: List[Dict] = []
    all_paths: List[Dict] = []
    all_path_counts: Dict[str, int] = {}
    all_path_entries: List[Dict] = []
    search_index: List[Dict] = []
    seen_tag_keys = set()
    total_tags = 0

    for idx, section in enumerate(sections):
        slug = _slugify(section.get("name") or "", idx)
        rel_file = os.path.join("sections", f"{slug}.yaml")
        out_path = os.path.join(group_tags_dir, rel_file)
        with open(out_path, "w", encoding="utf-8") as f:
            yaml.dump([section], f, allow_unicode=True, sort_keys=False, width=120)

        paths, path_counts, path_entries, rows = _collect_paths_and_index(section)
        tag_count = len(rows)

        for row in rows:
            key = (row["tag"] or "").strip().lower()
            if not key or key in seen_tag_keys:
                continue
            seen_tag_keys.add(key)
            search_index.append(row)

        total_tags += tag_count
        all_paths.extend(paths)
        for key, count in path_counts.items():
            all_path_counts[key] = all_path_counts.get(key, 0) + count
        all_path_entries.extend(path_entries)

        manifest_sections.append(
            {
                "name": section.get("name") or "",
                "file": rel_file.replace("\\", "/"),
                "tagCount": tag_count,
                "categoryCount": len(section.get("categories") or []),
            }
        )

    manifest = {
        "version": 2,
        "source": os.path.basename(default_path),
        "sectionCount": len(manifest_sections),
        "tagCount": len(search_index),
        "sections": manifest_sections,
        "paths": all_paths,
        "pathCounts": all_path_counts,
        "pathEntries": all_path_entries,
    }

    manifest_path = os.path.join(group_tags_dir, "manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    index_path = os.path.join(group_tags_dir, "search-index.pkl")
    with open(index_path, "wb") as f:
        pickle.dump(
            {
                "version": 2,
                "source_mtime": os.path.getmtime(default_path),
                "rows": search_index,
            },
            f,
            protocol=pickle.HIGHEST_PROTOCOL,
        )

    if backup:
        backup_path = default_path + ".bak"
        if not os.path.isfile(backup_path):
            os.replace(default_path, backup_path)
        elif os.path.isfile(default_path):
            os.remove(default_path)

    return {
        "sections": len(manifest_sections),
        "tags": len(search_index),
        "manifest": manifest_path,
        "index": index_path,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Split default.yaml into lazy-load section files")
    parser.add_argument(
        "--default",
        default=os.path.join(_SCRIPT_DIR, "..", "group_tags", "default.yaml"),
    )
    parser.add_argument(
        "--group-tags",
        default=os.path.join(_SCRIPT_DIR, "..", "group_tags"),
    )
    parser.add_argument("--no-backup", action="store_true")
    args = parser.parse_args()

    default_path = os.path.abspath(args.default)
    group_tags_dir = os.path.abspath(args.group_tags)
    if not os.path.isfile(default_path):
        raise SystemExit(f"default.yaml not found: {default_path}")

    result = split_default(default_path, group_tags_dir, backup=not args.no_backup)
    print(
        f"Split complete: {result['sections']} sections, {result['tags']} unique tags\n"
        f"  manifest: {result['manifest']}\n"
        f"  index:    {result['index']}"
    )


if __name__ == "__main__":
    main()
