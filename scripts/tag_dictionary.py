""" -*- coding: UTF-8 -*-
Tag dictionary loader for Prompt Composer.

Reads tags from prompt-aio's YAML file and exposes a simple
in-memory search API for the FastAPI routes.
"""

import os
from typing import List, Dict

import yaml

_tags: List[Dict] = []
_loaded: bool = False


def init(extension_dir: str):
    """Load tag dictionary once at startup."""
    global _tags, _loaded
    if _loaded:
        return

    # default.yaml from prompt-aio enhanced
    base_path = os.path.dirname(os.path.dirname(extension_dir))
    yaml_path = os.path.join(
        base_path,
        "extensions",
        "sd-webui-prompt-aio-enhanced",
        "group_tags",
        "default.yaml",
    )

    if not os.path.isfile(yaml_path):
        print(f"[Prompt Composer] Tag dictionary YAML not found: {yaml_path}")
        _tags = []
        _loaded = True
        return

    try:
        with open(yaml_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except Exception as e:
        print(f"[Prompt Composer] Failed to load tag dictionary: {e}")
        _tags = []
        _loaded = True
        return

    items: List[Dict] = []

    # expected top-level: list of sections
    if not isinstance(data, list):
        data = []

    for section in data:
        section_name = section.get("name") or ""
        for cat in section.get("categories", []) or []:
            cat_name = cat.get("name") or ""
            for group in cat.get("groups", []) or []:
                group_name = group.get("name") or ""
                tags = group.get("tags", {}) or {}
                # tags is a mapping: {english_tag: japanese_desc}
                for key, jp in tags.items():
                    eng = str(key)
                    jp_text = str(jp) if jp is not None else ""
                    items.append(
                        {
                            "tag": eng,
                            "jp": jp_text,
                            "section": section_name,
                            "category": cat_name,
                            "group": group_name,
                        }
                    )

    _tags = items
    _loaded = True
    print(f"[Prompt Composer] Loaded {len(_tags)} prompt dictionary tags from default.yaml")


def search_tags(
    query: str = "",
    limit: int = 50,
    section: str | None = None,
    category: str | None = None,
    group: str | None = None,
) -> List[Dict]:
    """Simple case-insensitive search over english tag and jp text, with optional path filters."""
    if not _loaded:
        return []

    q = (query or "").strip().lower()

    def match_path(item: Dict) -> bool:
        if section and item["section"] != section:
            return False
        if category and item["category"] != category:
            return False
        if group and item["group"] != group:
            return False
        return True

    results: List[Dict] = []
    for item in _tags:
        if len(results) >= limit:
            break
        if not match_path(item):
            continue
        if not q or q in item["tag"].lower() or q in item["jp"].lower():
            results.append(item)

    # If we filtered everything out with path, but no query, try again without path to provide something
    if not results and not q and not any([section, category, group]):
        return _tags[: max(1, min(limit, 200))]

    return results


def list_paths() -> List[Dict]:
    """Return distinct (section, category, group) combinations."""
    if not _loaded:
        return []

    seen = set()
    paths: List[Dict] = []
    for item in _tags:
        key = (item["section"], item["category"], item["group"])
        if key in seen:
            continue
        seen.add(key)
        paths.append(
            {
                "section": item["section"],
                "category": item["category"],
                "group": item["group"],
            }
        )
    return paths

