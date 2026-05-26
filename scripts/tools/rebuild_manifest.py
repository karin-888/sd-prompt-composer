#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""Rebuild group_tags/manifest.json and search-index.pkl from section YAML files."""

from __future__ import annotations

import glob
import json
import os
import pickle
import sys

import yaml

_TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
_SCRIPT_DIR = os.path.dirname(_TOOLS_DIR)
_GROUP_TAGS_DIR = os.path.join(_SCRIPT_DIR, "..", "group_tags")

# Section YAML files kept on disk but omitted from UI / search index until migrated.
EXCLUDED_SECTION_FILES = frozenset({
    "028_e621.yaml",
    "035_wildcards.yaml",
    "036_ワイルドカード_タグ集.yaml",
})


def rebuild() -> dict:
    sys.path.insert(0, _TOOLS_DIR)
    from split_default_by_section import _collect_paths_and_index

    files = sorted(glob.glob(os.path.join(_GROUP_TAGS_DIR, "sections", "*.yaml")))
    manifest_sections = []
    search_index = []
    seen_index = set()
    all_paths = []
    all_path_counts = {}
    all_path_entries = []

    for rel_file in files:
        if os.path.basename(rel_file) in EXCLUDED_SECTION_FILES:
            continue
        rel = os.path.join("sections", os.path.basename(rel_file)).replace("\\", "/")
        with open(rel_file, encoding="utf-8") as f:
            data = yaml.safe_load(f) or []
        if not data:
            continue
        sec = data[0] if isinstance(data, list) else data
        paths, path_counts, path_entries, rows = _collect_paths_and_index(sec)
        tag_count = 0
        for row in rows:
            key = (row.get("tag") or "").strip().lower()
            if not key or key in seen_index:
                continue
            seen_index.add(key)
            search_index.append(row)
            tag_count += 1
        all_paths.extend(paths)
        for k, v in path_counts.items():
            all_path_counts[k] = all_path_counts.get(k, 0) + v
        all_path_entries.extend(path_entries)
        manifest_sections.append({
            "name": sec.get("name") or "",
            "file": rel,
            "tagCount": tag_count,
            "categoryCount": len(sec.get("categories") or []),
        })

    manifest = {
        "version": 2,
        "source": "default.yaml",
        "sectionCount": len(manifest_sections),
        "tagCount": len(search_index),
        "sections": manifest_sections,
        "paths": all_paths,
        "pathCounts": all_path_counts,
        "pathEntries": all_path_entries,
    }
    with open(os.path.join(_GROUP_TAGS_DIR, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    with open(os.path.join(_GROUP_TAGS_DIR, "search-index.pkl"), "wb") as f:
        pickle.dump({"version": 2, "source_mtime": 0, "rows": search_index}, f, protocol=pickle.HIGHEST_PROTOCOL)

    return {
        "sections": len(manifest_sections),
        "paths": len(all_paths),
        "tags": len(search_index),
    }


if __name__ == "__main__":
    print(json.dumps(rebuild(), ensure_ascii=False, indent=2))
